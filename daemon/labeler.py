"""Topic-summary resolver.

Two strategies, picked based on the topic key:
  - Ticket-shaped (`COR-144` etc.) → query Jira via the local `acli` CLI
    and use the issue's summary field. Deterministic, free.
  - Anything else (unclassified buckets, false-positive matches like GAD-7,
    soft theme topics) → call `claude -p` and ask for a 5–10 word
    description from a sample of user prompts.

Both shell-outs have timeouts and fail gracefully — if the tool isn't
installed, login is expired, network blips, etc., we return None and the
caller leaves the cache entry unset (will retry on the next tick).

This module is pure functions; the Labeler class that owns the cache and
background thread lives elsewhere.
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
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from daemon.rollup import Rollup, SessionInfo

logger = logging.getLogger(__name__)

# Same shape as topics.TICKET_RE but anchored to the whole string — we use
# this on a topic_id, not free text.
TICKET_KEY_RE = re.compile(r"^[A-Z]{2,5}-\d+$")

ACLI_TIMEOUT_SEC = 8.0
CLAUDE_TIMEOUT_SEC = 30.0
PROMPTS_SAMPLE_CAP = 20

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


def fetch_claude_summary(topic_id: str, prompts_sample: list[str]) -> str | None:
    """Ask the local Claude Code CLI for a 5–10 word summary of a topic.

    Feeds it a few representative user prompts. Returns None if claude
    isn't installed, the call times out, or the output is empty.
    """
    if not prompts_sample:
        return None
    sample_text = "\n---\n".join(p[:500] for p in prompts_sample[:PROMPTS_SAMPLE_CAP])
    instruction = (
        "Summarize what this Claude Code topic was about in 5 to 10 words. "
        f"Topic key: {topic_id}. Below are user prompts from sessions in "
        "this topic. Reply with ONLY the summary, no quotes, no trailing "
        "punctuation, no preamble:\n\n" + sample_text
    )
    try:
        r = subprocess.run(
            ["claude", "-p", instruction],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SEC,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    summary = r.stdout.strip()
    return summary or None


def summarize_topic(topic_id: str, prompts_sample: list[str]) -> str | None:
    """Resolve a summary for `topic_id`. None on any failure.

    Strategy: ticket-shaped → Jira via acli (preferred); fall through to
    claude -p when Jira returns nothing or the topic isn't ticket-shaped.
    """
    if is_ticket_topic(topic_id):
        title = fetch_jira_summary(topic_id)
        if title:
            return title
    return fetch_claude_summary(topic_id, prompts_sample)


# --- background labeler ---------------------------------------------------


DEFAULT_INTERVAL_SEC = 600.0   # 10 min between ticks
DEFAULT_MAX_PER_TICK = 25      # cap subprocess load per tick


class Labeler:
    """Background thread that resolves topic summaries off the request path.

    The watcher thread feeds the rollup; this thread reads the rollup,
    calls `summarize_topic` for any topic missing or past TTL, and writes
    results to the on-disk cache. Route handlers read summaries via the
    non-blocking `get_summary` accessor (briefly takes a Lock).
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
        """Run one labeling pass; return number of topics labeled this tick.
        Public so tests can drive it without spinning a thread."""
        topics = [t.topic_id for t in self.rollup.snapshot_topics()]
        pending: list[str] = []
        with self._cache_lock:
            for tid in topics:
                entry = self._cache.get(tid)
                if entry is None or not is_fresh(entry):
                    pending.append(tid)
        pending = pending[: self.max_per_tick]
        if not pending:
            return 0

        sessions = self.rollup.snapshot_sessions()
        labeled = 0
        for tid in pending:
            if self._stop.is_set():
                break
            prompts = self._collect_prompts(tid, sessions)
            summary = summarize_topic(tid, prompts)
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

    def _collect_prompts(
        self, topic_id: str, sessions: "Iterable[SessionInfo]",
    ) -> list[str]:
        """Up to PROMPTS_SAMPLE_CAP early prompts from sessions touching
        this topic. Used as the LLM context when ticket lookup falls back."""
        out: list[str] = []
        for s in sessions:
            if topic_id in s.segments and s.early_user_prompts:
                out.extend(s.early_user_prompts[:2])
                if len(out) >= PROMPTS_SAMPLE_CAP:
                    break
        return out
