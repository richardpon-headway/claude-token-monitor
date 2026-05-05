"""Filesystem watcher that feeds the rollup.

Wraps watchdog.Observer. On any `.jsonl` change under ~/.claude/projects/,
reads only the tail of the file from the last known byte offset (Rollup
remembers it), parses new records, ingests them, then fires an optional
callback so the SSE layer can broadcast a snapshot.

Also exposes `initial_scan` — a one-time pass over every existing log used
by main.py at startup, before the observer starts. After that, watchdog
events drive everything.
"""
from __future__ import annotations

import datetime
import pathlib
import threading
from typing import Callable

from watchdog.events import (
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from daemon.parser import parse_file
from daemon.rollup import Rollup


def _is_jsonl(path: str) -> bool:
    return path.endswith(".jsonl")


def initial_scan(
    rollup: Rollup,
    projects_dir: pathlib.Path,
    *,
    mtime_cutoff_days: int = 35,
) -> int:
    """Ingest every recent .jsonl in projects_dir into the rollup.

    Returns number of files ingested. Skips files older than mtime_cutoff_days
    so we don't spend startup time on logs that have rolled out of the live
    window (the cache covers them).
    """
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=mtime_cutoff_days)
    ).timestamp()
    count = 0
    for path in projects_dir.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        result = parse_file(
            path,
            projects_dir=projects_dir,
            seen_message_ids=rollup.seen_message_ids,
            start_offset=rollup.file_offset(str(path)),
            current_prompt_ticket=rollup.prompt_ticket_for(path.stem),
        )
        rollup.ingest(result, file_path=str(path))
        count += 1
    return count


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        rollup: Rollup,
        projects_dir: pathlib.Path,
        on_change: Callable[[], None] | None,
    ) -> None:
        self.rollup = rollup
        self.projects_dir = projects_dir
        self.on_change = on_change
        # Coalesce rapid same-file events: a single assistant turn can fire
        # multiple `on_modified` events as buffers flush. We re-parse from
        # the saved offset each time, so duplicates are cheap, but we still
        # want to avoid pegging on bursty writes.
        self._lock = threading.Lock()

    def _handle(self, path_str: str) -> None:
        if not _is_jsonl(path_str):
            return
        path = pathlib.Path(path_str)
        if not path.exists():
            return
        with self._lock:
            result = parse_file(
                path,
                projects_dir=self.projects_dir,
                seen_message_ids=self.rollup.seen_message_ids,
                start_offset=self.rollup.file_offset(path_str),
                current_prompt_ticket=self.rollup.prompt_ticket_for(path.stem),
            )
            if result.records or result.early_user_prompts:
                self.rollup.ingest(result, file_path=path_str)
                if self.on_change is not None:
                    self.on_change()
            elif result.bytes_read != self.rollup.file_offset(path_str):
                # advance offset even if nothing meaningful was added
                # (e.g. lines without a usage block) so we don't keep
                # re-reading them.
                self.rollup.set_file_offset(path_str, result.bytes_read)

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_moved(self, event: FileMovedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._handle(event.dest_path)


class Watcher:
    def __init__(
        self,
        rollup: Rollup,
        projects_dir: pathlib.Path,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.rollup = rollup
        self.projects_dir = projects_dir
        self.on_change = on_change
        self._observer: Observer | None = None

    def start(self) -> None:
        if self._observer is not None:
            return
        observer = Observer()
        observer.schedule(
            _Handler(self.rollup, self.projects_dir, self.on_change),
            str(self.projects_dir),
            recursive=True,
        )
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5.0)
        self._observer = None
