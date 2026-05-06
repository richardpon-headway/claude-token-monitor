"""Topic-summary resolver.

Ticket-shaped topics (`COR-144` etc.) get their summary from Jira via the
local `acli` CLI. Anything else (`unclassified:<project>#<branch>`, soft
themes) is left without a summary — the display label generated in
`daemon/topics.topic_display_label` already conveys the project/branch.

The shell-out has a timeout and fails gracefully — if the tool isn't
installed, login is expired, network blips, etc., we return None and the
caller leaves the cache entry unset (will retry on the next tick).

This module is pure functions; the Labeler class that owns the cache and
background thread lives at the bottom.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from daemon.rollup import Rollup

logger = logging.getLogger(__name__)

# Same shape as topics.TICKET_RE but anchored to the whole string — we use
# this on a topic_id, not free text.
TICKET_KEY_RE = re.compile(r"^[A-Z]{2,5}-\d+$")

ACLI_TIMEOUT_SEC = 8.0

CACHE_TTL_SEC = 7 * 86400  # refresh entries older than 7 days
DEFAULT_CACHE_PATH = (
    pathlib.Path.home() / ".cache" / "claude-token-monitor" / "topic-summaries.json"
)


@dataclass
class CachedSummary:
    summary: str
    fetched_at: float  # unix epoch seconds


def is_fresh(cached: CachedSummary, *, now: float | None = None) -> bool:
    """True if `cached` is still within the TTL window."""
    n = now if now is not None else time.time()
    return (n - cached.fetched_at) < CACHE_TTL_SEC


def load_cache(path: pathlib.Path = DEFAULT_CACHE_PATH) -> dict[str, CachedSummary]:
    """Load the on-disk cache. Returns {} if the file is missing or unreadable."""
    try:
        raw = path.read_text()
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, CachedSummary] = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        s = v.get("summary")
        ts = v.get("fetched_at")
        if isinstance(s, str) and isinstance(ts, (int, float)):
            out[k] = CachedSummary(summary=s, fetched_at=float(ts))
    return out


def save_cache(
    cache: dict[str, CachedSummary],
    path: pathlib.Path = DEFAULT_CACHE_PATH,
) -> None:
    """Atomic write: dump to a sibling tempfile, then os.replace.

    Avoids leaving a half-written cache on crash. The labeler tick may
    write hundreds of entries, so a partial write would corrupt the
    next startup's load.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        k: {"summary": v.summary, "fetched_at": v.fetched_at}
        for k, v in cache.items()
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)


def is_ticket_topic(topic_id: str) -> bool:
    return bool(TICKET_KEY_RE.match(topic_id))


def fetch_jira_summary(ticket: str) -> str | None:
    """Return the Jira issue summary for `ticket`, or None on any failure.

    Shells out to `acli jira issue view <ticket> --json`. Unset/missing CLI,
    auth failures, missing tickets, malformed JSON — all return None.
    """
    try:
        r = subprocess.run(
            ["acli", "jira", "workitem", "view", ticket,
             "--fields", "summary", "--json"],
            capture_output=True,
            text=True,
            timeout=ACLI_TIMEOUT_SEC,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    fields = data.get("fields") or {}
    summary = fields.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return None


def summarize_topic(topic_id: str) -> str | None:
    """Resolve a summary for `topic_id`. None for non-ticket topics or any
    Jira failure — the display label already covers the project/branch case.
    """
    if not is_ticket_topic(topic_id):
        return None
    return fetch_jira_summary(topic_id)


# --- background labeler ---------------------------------------------------


DEFAULT_INTERVAL_SEC = 600.0   # 10 min between ticks
DEFAULT_MAX_PER_TICK = 25      # cap subprocess load per tick


class Labeler:
    """Background thread that resolves Jira summaries off the request path.

    The watcher thread feeds the rollup; this thread reads the rollup,
    calls `summarize_topic` for any ticket-shaped topic missing or past
    TTL, and writes results to the on-disk cache. Route handlers read
    summaries via the non-blocking `get_summary` accessor (briefly takes
    a Lock).
    """

    def __init__(
        self,
        rollup: "Rollup",
        *,
        cache_path: pathlib.Path = DEFAULT_CACHE_PATH,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
        max_per_tick: int = DEFAULT_MAX_PER_TICK,
    ) -> None:
        self.rollup = rollup
        self.cache_path = cache_path
        self.interval_sec = interval_sec
        self.max_per_tick = max_per_tick
        self._cache_lock = threading.Lock()
        self._cache: dict[str, CachedSummary] = load_cache(cache_path)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- read side (called by HTTP handlers) ------------------------------

    def get_summary(self, topic_id: str) -> str | None:
        with self._cache_lock:
            entry = self._cache.get(topic_id)
            return entry.summary if entry else None

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="labeler", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None

    # --- internals --------------------------------------------------------

    def _run(self) -> None:
        # Initial tick happens immediately on start so summaries appear
        # without waiting interval_sec for the first one.
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("labeler tick failed")
            self._stop.wait(self.interval_sec)

    def tick(self) -> int:
        """Run one labeling pass; returns number of topics labeled this
        tick. Public so tests can drive it without spinning a thread."""
        # Re-sync the topic-summary cache from disk so external writes
        # (a previous daemon run, smoke test) don't get clobbered.
        with self._cache_lock:
            for k, v in load_cache(self.cache_path).items():
                existing = self._cache.get(k)
                if existing is None or v.fetched_at > existing.fetched_at:
                    self._cache[k] = v

        topics = [t.topic_id for t in self.rollup.snapshot_topics()]
        pending: list[str] = []
        with self._cache_lock:
            for tid in topics:
                if not is_ticket_topic(tid):
                    continue
                entry = self._cache.get(tid)
                if entry is None or not is_fresh(entry):
                    pending.append(tid)
        pending = pending[: self.max_per_tick]
        if not pending:
            return 0

        labeled = 0
        for tid in pending:
            if self._stop.is_set():
                break
            summary = summarize_topic(tid)
            if summary:
                with self._cache_lock:
                    self._cache[tid] = CachedSummary(
                        summary=summary, fetched_at=time.time(),
                    )
                self._save()
                labeled += 1
        return labeled

    def _save(self) -> None:
        with self._cache_lock:
            cache_copy = dict(self._cache)
        save_cache(cache_copy, self.cache_path)
