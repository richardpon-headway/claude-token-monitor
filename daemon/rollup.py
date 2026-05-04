"""In-memory rollup of Claude Code usage.

Single writer (the watcher thread feeds ParseResults via ingest()).
Many readers (FastAPI route handlers call snapshot_*() methods).
A single Lock protects all mutable state.

State held here:
  - by_day_local      : dict[date_iso, DayBucket]
  - by_day_utc        : dict[date_iso, DayBucket]
  - by_session        : dict[session_id, SessionInfo]
  - seen_message_ids  : set[str]                   (passed to parser; persists across calls)
  - file_offsets      : dict[str, int]             (per-file resume point for the watcher)
  - by_minute_local   : dict[minute_iso, int]      (output tokens per local-time minute)
  - prompt_ticket_state : dict[session_id, str|None]
        Per-session "most recent user-prompt ticket mention" — passed in/out
        of parse_file() so per-record topic resolution survives incremental
        reads of the same session file.

Project-level and topic-level views are derived on demand from by_session,
so we don't have to keep them in sync on every ingest.
"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field, replace

from daemon.parser import ParseResult, UsageRecord

LOCAL_TZ = datetime.datetime.now().astimezone().tzinfo


@dataclass
class DayBucket:
    output: int = 0
    input: int = 0
    messages: int = 0


@dataclass
class SegmentTotals:
    """Per-(session, topic) totals. A session has one of these per topic
    it touched. Sum across segments gives session totals; sum across
    sessions for a given topic_id gives topic totals."""
    output: int = 0
    input: int = 0
    messages: int = 0
    last_at: datetime.datetime | None = None


@dataclass
class SessionInfo:
    session_id: str
    project: str
    output: int = 0  # cached sum across segments — kept in sync on ingest
    input: int = 0
    messages: int = 0
    started_at: datetime.datetime | None = None
    last_at: datetime.datetime | None = None
    early_user_prompts: list[str] = field(default_factory=list)
    topic_id: str | None = None  # dominant topic, recomputed on each ingest
    segments: dict[str, SegmentTotals] = field(default_factory=dict)


@dataclass
class ProjectInfo:
    project: str
    sessions: int
    output: int
    input: int
    messages: int
    last_at: datetime.datetime | None


@dataclass
class TopicInfo:
    topic_id: str
    sessions: int
    output: int
    input: int
    messages: int
    last_at: datetime.datetime | None


def _minute_iso(dt: datetime.datetime) -> str:
    return dt.replace(second=0, microsecond=0).isoformat()


class Rollup:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_day_local: dict[str, DayBucket] = {}
        self.by_day_utc: dict[str, DayBucket] = {}
        self.by_session: dict[str, SessionInfo] = {}
        self.seen_message_ids: set[str] = set()
        self.file_offsets: dict[str, int] = {}
        # local-time minute_iso -> output tokens that minute. Unbounded but tiny:
        # at most one entry per minute of actual activity (~minutes/day usage).
        self.by_minute_local: dict[str, int] = {}
        # session_id -> running "current_prompt_ticket" used for per-record
        # topic resolution. Persisted across incremental parses.
        self.prompt_ticket_state: dict[str, str | None] = {}

    # --- writer side ----------------------------------------------------

    def file_offset(self, path: str) -> int:
        with self._lock:
            return self.file_offsets.get(path, 0)

    def set_file_offset(self, path: str, offset: int) -> None:
        with self._lock:
            self.file_offsets[path] = offset

    def prompt_ticket_for(self, session_id: str) -> str | None:
        with self._lock:
            return self.prompt_ticket_state.get(session_id)

    def load_cache_days(
        self,
        by_utc_date: dict[str, dict],
        by_local_date: dict[str, dict],
    ) -> None:
        """Fill in day buckets from the token-usage skill's cache.

        Only writes days NOT already present in the rollup, so logs win for
        any day they cover. Call AFTER ingesting all live JSONL files.
        Matches usage.py's "logs are authoritative" rule.
        """
        with self._lock:
            for d, data in by_utc_date.items():
                if d in self.by_day_utc:
                    continue
                self.by_day_utc[d] = DayBucket(
                    output=data.get("output", 0),
                    input=data.get("input", 0),
                    messages=data.get("messages", 0),
                )
            for d, data in by_local_date.items():
                if d in self.by_day_local:
                    continue
                self.by_day_local[d] = DayBucket(
                    output=data.get("output", 0),
                    input=data.get("input", 0),
                    messages=data.get("messages", 0),
                )

    def ingest(self, result: ParseResult, *, file_path: str | None = None) -> None:
        """Merge a ParseResult into the rollup."""
        with self._lock:
            session = self.by_session.get(result.session_id)
            if session is None:
                session = SessionInfo(
                    session_id=result.session_id,
                    project=result.project,
                )
                self.by_session[result.session_id] = session

            # session-level metadata: keep earliest started_at, latest last_at,
            # and accumulate early prompts up to the parser's cap.
            if result.started_at is not None:
                if session.started_at is None or result.started_at < session.started_at:
                    session.started_at = result.started_at
            if result.last_at is not None:
                if session.last_at is None or result.last_at > session.last_at:
                    session.last_at = result.last_at
            if result.early_user_prompts and len(session.early_user_prompts) < 5:
                room = 5 - len(session.early_user_prompts)
                session.early_user_prompts.extend(result.early_user_prompts[:room])

            for rec in result.records:
                self._apply_record(rec, session)

            # Recompute dominant topic from the now-updated segments.
            if session.segments:
                session.topic_id = max(
                    session.segments.items(),
                    key=lambda kv: kv[1].output,
                )[0]

            # Persist the parser's ending prompt-ticket state for the next call.
            self.prompt_ticket_state[result.session_id] = result.current_prompt_ticket

            if file_path is not None and result.bytes_read:
                self.file_offsets[file_path] = result.bytes_read

    def _apply_record(self, rec: UsageRecord, session: SessionInfo) -> None:
        session.output += rec.output_tokens
        session.input += rec.input_tokens
        session.messages += 1

        # Per-(session, topic) segment — drives the topic-level rollup.
        seg = session.segments.setdefault(rec.topic_id, SegmentTotals())
        seg.output += rec.output_tokens
        seg.input += rec.input_tokens
        seg.messages += 1
        if seg.last_at is None or rec.timestamp_utc > seg.last_at:
            seg.last_at = rec.timestamp_utc

        utc_d = rec.timestamp_utc.date().isoformat()
        local_d = rec.timestamp_utc.astimezone(LOCAL_TZ).date().isoformat()
        b_utc = self.by_day_utc.setdefault(utc_d, DayBucket())
        b_utc.output += rec.output_tokens
        b_utc.input += rec.input_tokens
        b_utc.messages += 1
        b_loc = self.by_day_local.setdefault(local_d, DayBucket())
        b_loc.output += rec.output_tokens
        b_loc.input += rec.input_tokens
        b_loc.messages += 1

        local_dt = rec.timestamp_utc.astimezone(LOCAL_TZ)
        m = _minute_iso(local_dt)
        self.by_minute_local[m] = self.by_minute_local.get(m, 0) + rec.output_tokens

    # --- reader side ---------------------------------------------------

    def snapshot_windows(self) -> dict:
        """Today / 7d / 30d output totals (local + UTC).

        Window semantics mirror usage.py:
          - Local windows are "Last N days" inclusive of today (still ticking).
          - UTC windows are "Last N complete UTC days" — today_utc EXCLUDED,
            because the leaderboard reports completed UTC days only.
        """
        with self._lock:
            today_local = datetime.datetime.now(LOCAL_TZ).date()
            today_utc = datetime.datetime.now(datetime.timezone.utc).date()
            yesterday_utc = today_utc - datetime.timedelta(days=1)
            return {
                "today_local": _window_totals(
                    self.by_day_local, today_local, today_local
                ),
                "last_7d_local": _window_totals(
                    self.by_day_local,
                    today_local - datetime.timedelta(days=6),
                    today_local,
                ),
                "last_30d_local": _window_totals(
                    self.by_day_local,
                    today_local - datetime.timedelta(days=29),
                    today_local,
                ),
                "last_7d_utc": _window_totals(
                    self.by_day_utc,
                    today_utc - datetime.timedelta(days=7),
                    yesterday_utc,
                ),
                "last_30d_utc": _window_totals(
                    self.by_day_utc,
                    today_utc - datetime.timedelta(days=30),
                    yesterday_utc,
                ),
            }

    def snapshot_sessions(self) -> list[SessionInfo]:
        with self._lock:
            return [
                replace(
                    s,
                    early_user_prompts=list(s.early_user_prompts),
                    segments={tid: replace(seg) for tid, seg in s.segments.items()},
                )
                for s in self.by_session.values()
            ]

    def snapshot_projects(self) -> list[ProjectInfo]:
        with self._lock:
            agg: dict[str, dict] = {}
            for s in self.by_session.values():
                a = agg.setdefault(s.project, {
                    "sessions": 0, "output": 0, "input": 0,
                    "messages": 0, "last_at": None,
                })
                a["sessions"] += 1
                a["output"] += s.output
                a["input"] += s.input
                a["messages"] += s.messages
                if s.last_at is not None and (
                    a["last_at"] is None or s.last_at > a["last_at"]
                ):
                    a["last_at"] = s.last_at
            return [ProjectInfo(project=k, **v) for k, v in agg.items()]

    def snapshot_topics(self) -> list[TopicInfo]:
        """Aggregate segments across all sessions. Each session contributes
        once per topic it touched, so a single multi-topic session lifts
        multiple topic rows."""
        with self._lock:
            agg: dict[str, dict] = {}
            for s in self.by_session.values():
                for tid, seg in s.segments.items():
                    a = agg.setdefault(tid, {
                        "sessions": 0, "output": 0, "input": 0,
                        "messages": 0, "last_at": None,
                    })
                    a["sessions"] += 1
                    a["output"] += seg.output
                    a["input"] += seg.input
                    a["messages"] += seg.messages
                    if seg.last_at is not None and (
                        a["last_at"] is None or seg.last_at > a["last_at"]
                    ):
                        a["last_at"] = seg.last_at
            return [TopicInfo(topic_id=k, **v) for k, v in agg.items()]

    def snapshot_timeseries(self, minutes: int) -> list[tuple[str, int]]:
        """Last `minutes` 1-minute buckets, oldest first.

        Returns only minutes for which we recorded activity; missing minutes
        are not zero-filled here — the UI fills gaps. Caller picks the window
        size (e.g. 60 for 1h, 1440 for 24h).
        """
        cutoff_dt = datetime.datetime.now(LOCAL_TZ).replace(
            second=0, microsecond=0
        ) - datetime.timedelta(minutes=minutes)
        cutoff = _minute_iso(cutoff_dt)
        with self._lock:
            return sorted(
                ((m, v) for m, v in self.by_minute_local.items() if m >= cutoff),
                key=lambda x: x[0],
            )


def _window_totals(
    day_dict: dict[str, DayBucket],
    start: datetime.date,
    end_inclusive: datetime.date,
) -> dict:
    out = inp = msgs = 0
    d = start
    while d <= end_inclusive:
        b = day_dict.get(d.isoformat())
        if b is not None:
            out += b.output
            inp += b.input
            msgs += b.messages
        d += datetime.timedelta(days=1)
    return {"output": out, "input": inp, "messages": msgs}
