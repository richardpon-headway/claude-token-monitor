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
DEFAULT_CLASSIFICATION_CACHE_PATH = (
    pathlib.Path.home()
    / ".cache"
    / "claude-token-monitor"
    / "session-classifications.json"
)
# Refresh a session classification when output has grown by this factor
# since the cached classification (B refresh policy from PR #32 design).
CLASSIFICATION_GROWTH_REFRESH = 2.0
# Only classify sessions in this rolling window (matches the B
# refresh window — older sessions stay locked at whatever the cache says).
CLASSIFICATION_WINDOW_DAYS = 7


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


def load_classification_cache(
    path: pathlib.Path = DEFAULT_CLASSIFICATION_CACHE_PATH,
) -> dict[str, SessionClassification]:
    """Load the on-disk session-classification cache. Returns {} on
    missing/corrupt file (same forgiving behavior as load_cache)."""
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
    out: dict[str, SessionClassification] = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        try:
            out[k] = SessionClassification(
                ticket=v.get("ticket") if isinstance(v.get("ticket"), str) or v.get("ticket") is None else None,
                summary=v.get("summary") if isinstance(v.get("summary"), str) or v.get("summary") is None else None,
                confidence=float(v.get("confidence", 0.0)),
                output_at_classification=int(v.get("output_at_classification", 0)),
            )
        except (TypeError, ValueError):
            continue
    return out


def save_classification_cache(
    cache: dict[str, SessionClassification],
    path: pathlib.Path = DEFAULT_CLASSIFICATION_CACHE_PATH,
) -> None:
    """Atomic write of the session-classification cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        k: {
            "ticket": v.ticket,
            "summary": v.summary,
            "confidence": v.confidence,
            "output_at_classification": v.output_at_classification,
        }
        for k, v in cache.items()
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)


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


# --- session classification (LLM-based unclassified resolution) -----------


@dataclass
class SessionClassification:
    """Result of classifying an unclassified session via claude -p.

    `ticket` is set only when the LLM is confident (>= 0.8) the session
    is about that ticket. `summary` is always populated when the call
    succeeds. `output_at_classification` is the session's total output
    tokens at the time we classified — refresh policy compares this
    against current totals to decide if we re-classify (B: refresh on
    >= 2x growth)."""
    ticket: str | None
    summary: str | None
    confidence: float
    output_at_classification: int


def classify_session(
    session_id: str,
    prompts_sample: list[str],
    candidate_tickets: list[tuple[str, str | None]],
    assistant_text_sample: str | None = None,
    *,
    output_at_classification: int = 0,
    confidence_threshold: float = 0.8,
) -> SessionClassification | None:
    """Ask `claude -p` to classify a session into one of the candidate
    tickets, or return a 5-10 word summary if no ticket fits.

    `candidate_tickets` is a list of (ticket_id, jira_summary | None)
    pairs — the LLM matches against IDs AND summaries when available.
    `assistant_text_sample` is an optional snippet from the first
    assistant turn for sessions where the user prompts are vague.

    Returns None on any subprocess failure (missing CLI, timeout,
    malformed JSON, etc.) so the caller leaves the cache unset and
    retries on the next tick.
    """
    if not prompts_sample:
        return None

    ticket_lines: list[str] = []
    for tid, summary in candidate_tickets:
        if summary:
            ticket_lines.append(f"  - {tid}: {summary}")
        else:
            ticket_lines.append(f"  - {tid}")
    candidates_block = "\n".join(ticket_lines) if ticket_lines else "  (none known)"

    prompt_block = "\n".join(
        f"  {i+1}. {p[:500]}" for i, p in enumerate(prompts_sample[:5])
    )
    assistant_block = (
        f"\n\nA snippet of the first assistant turn:\n{assistant_text_sample[:500]}"
        if assistant_text_sample
        else ""
    )

    instruction = (
        "You're classifying a Claude Code session by which Jira ticket "
        "it's most likely about. Below is the candidate ticket list "
        "(with summaries when available) and the user's first prompts.\n\n"
        f"Candidate tickets:\n{candidates_block}\n\n"
        f"User's first prompts:\n{prompt_block}"
        f"{assistant_block}\n\n"
        "Reply ONLY with a JSON object — no other text — in this shape:\n"
        '{"ticket": "COR-144" | null, "summary": "5-10 word description", "confidence": 0.0-1.0}\n\n'
        "Rules:\n"
        f"- Only set 'ticket' if you're at least {confidence_threshold} confident "
        "the session matches one of the candidates.\n"
        "- 'summary' should describe what the session was about, regardless of ticket match.\n"
        "- 'confidence' is your self-reported confidence in the ticket assignment "
        "(if ticket is null, confidence applies to that judgement)."
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

    raw = r.stdout.strip()
    if not raw:
        return None
    # The LLM may wrap JSON in ```json``` fences or add stray text. Try
    # to find the first {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None

    ticket = data.get("ticket")
    if not isinstance(ticket, str) or not TICKET_KEY_RE.match(ticket):
        ticket = None
    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    # Apply the threshold: only return a ticket assignment if confident.
    if ticket is not None and confidence < confidence_threshold:
        ticket = None

    # Don't fail outright if the candidate list didn't include the
    # returned ticket — the LLM might pick a real Jira ticket that
    # just wasn't in the snapshot. Trust the regex-validated value.

    return SessionClassification(
        ticket=ticket,
        summary=summary,
        confidence=confidence,
        output_at_classification=output_at_classification,
    )


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
        classification_cache_path: pathlib.Path = DEFAULT_CLASSIFICATION_CACHE_PATH,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
        max_per_tick: int = DEFAULT_MAX_PER_TICK,
    ) -> None:
        self.rollup = rollup
        self.cache_path = cache_path
        self.classification_cache_path = classification_cache_path
        self.interval_sec = interval_sec
        self.max_per_tick = max_per_tick
        self._cache_lock = threading.Lock()
        self._cache: dict[str, CachedSummary] = load_cache(cache_path)
        self._classification_lock = threading.Lock()
        self._classifications: dict[str, SessionClassification] = (
            load_classification_cache(classification_cache_path)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- read side (called by HTTP handlers) ------------------------------

    def get_summary(self, topic_id: str) -> str | None:
        with self._cache_lock:
            entry = self._cache.get(topic_id)
            return entry.summary if entry else None

    def get_classification(self, session_id: str) -> SessionClassification | None:
        """Read-only accessor for the rollup's override layer. Returns
        None if the session has no cached classification."""
        with self._classification_lock:
            return self._classifications.get(session_id)

    def all_classifications(self) -> dict[str, SessionClassification]:
        """Snapshot of every cached classification — used by the rollup
        when computing windowed group rows so it can override unclassified
        records with the LLM's verdict in a single pass."""
        with self._classification_lock:
            return dict(self._classifications)

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
        """Run one labeling pass; returns total number of topics labeled
        + sessions classified this tick. Public so tests can drive it
        without spinning a thread."""
        # Re-sync the topic-summary cache from disk so external writes
        # (a previous daemon run, smoke test) don't get clobbered.
        with self._cache_lock:
            for k, v in load_cache(self.cache_path).items():
                existing = self._cache.get(k)
                if existing is None or v.fetched_at > existing.fetched_at:
                    self._cache[k] = v
        # Same for the classification cache. Sessions are identified by
        # session_id (immutable), so taking the higher
        # output_at_classification (most recent re-classification) wins.
        with self._classification_lock:
            for k, v in load_classification_cache(
                self.classification_cache_path
            ).items():
                existing = self._classifications.get(k)
                if (
                    existing is None
                    or v.output_at_classification >= existing.output_at_classification
                ):
                    self._classifications[k] = v

        labeled = self._tick_topics()
        classified = self._tick_classifications()
        return labeled + classified

    def _tick_topics(self) -> int:
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

    def _tick_classifications(self) -> int:
        """Classify unclassified sessions in the last
        CLASSIFICATION_WINDOW_DAYS that don't have a cached
        classification (or whose output has grown >= 2x since the
        cached one — B refresh policy)."""
        # Candidate ticket list: tickets that touched the rollup at all
        # — windowed_groups respects the time window, but here we want
        # the full ticket vocabulary the rollup knows about.
        snapshot = self.rollup.snapshot_topics()
        candidate_tickets: list[tuple[str, str | None]] = []
        with self._cache_lock:
            for t in snapshot:
                if not is_ticket_topic(t.topic_id):
                    continue
                cached = self._cache.get(t.topic_id)
                candidate_tickets.append(
                    (t.topic_id, cached.summary if cached else None)
                )

        # Walk current sessions; pick unclassified ones in the window
        # that need classification.
        import datetime as _dt
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(
            days=CLASSIFICATION_WINDOW_DAYS
        )
        sessions = self.rollup.snapshot_sessions()
        pending: list = []
        with self._classification_lock:
            for s in sessions:
                # Only sessions whose dominant topic is unclassified.
                if not s.topic_id or not s.topic_id.startswith("unclassified:"):
                    continue
                # Only sessions active in the window.
                if s.last_at is None or s.last_at < cutoff:
                    continue
                cached = self._classifications.get(s.session_id)
                if cached is None:
                    pending.append(s)
                elif s.output >= cached.output_at_classification * CLASSIFICATION_GROWTH_REFRESH:
                    pending.append(s)
                # else: cached + hasn't grown 2x — skip
        # Cap per-tick to avoid bursts.
        pending = pending[: self.max_per_tick]
        if not pending:
            return 0

        classified = 0
        for s in pending:
            if self._stop.is_set():
                break
            prompts = list(s.early_user_prompts)
            if not prompts:
                continue
            result = classify_session(
                session_id=s.session_id,
                prompts_sample=prompts,
                candidate_tickets=candidate_tickets,
                output_at_classification=s.output,
            )
            if result is None:
                continue
            with self._classification_lock:
                self._classifications[s.session_id] = result
            self._save_classifications()
            classified += 1
        return classified

    def _save(self) -> None:
        with self._cache_lock:
            cache_copy = dict(self._cache)
        save_cache(cache_copy, self.cache_path)

    def _save_classifications(self) -> None:
        with self._classification_lock:
            cache_copy = dict(self._classifications)
        save_classification_cache(cache_copy, self.classification_cache_path)

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
