"""FastAPI routes: /api/usage/* JSON endpoints + /api/stream SSE.

The Broadcaster is the bridge between the watcher (which fires on_change
in a watchdog thread) and SSE subscribers (async generators in event-loop
threads). It coalesces rapid-fire change events into at most one push
every COALESCE_INTERVAL seconds.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import pathlib
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from daemon.labeler import Labeler
from daemon.rollup import Rollup
from daemon.topics import infer_session_ticket, topic_display_label

logger = logging.getLogger(__name__)

COALESCE_INTERVAL = 0.5  # seconds between SSE pushes per subscriber

# Claude Developer Hub writes a JSON sidecar per spawned session here,
# keyed by session_id. We use it to recover a ticket the prompt-scan
# heuristic missed (e.g. sessions where the ticket only appears in the
# branch name or worktree path). The sidecar value wins over inferred.
SIDECAR_DIR = pathlib.Path.home() / ".cache" / "claude-token-monitor" / "session-meta"

# Keyed by session_id. Stored as (mtime, parsed_dict_or_None). Stale
# entries are evicted lazily on the next read when mtime changes or the
# file disappears.
_sidecar_cache: dict[str, tuple[float, dict | None]] = {}


def read_session_sidecar(session_id: str) -> dict | None:
    """Return CDH-written sidecar metadata for `session_id`, or None.

    Cached by file mtime so steady-state requests don't re-parse JSON.
    Malformed JSON is logged and treated as 'no sidecar' rather than
    raised — a broken sidecar should never take down the API.
    """
    path = SIDECAR_DIR / f"{session_id}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _sidecar_cache.pop(session_id, None)
        return None
    cached = _sidecar_cache.get(session_id)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = None
    except (OSError, ValueError) as e:
        logger.warning("failed to parse sidecar %s: %s", path, e)
        data = None
    _sidecar_cache[session_id] = (mtime, data)
    return data


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if is_dataclass(obj):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


class Broadcaster:
    """Fan-out for change notifications. Watcher calls notify() (sync, from a
    watchdog thread); SSE handlers iterate subscribe() (async)."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[None]] = set()
        self._last_push: float = 0.0

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def notify(self) -> None:
        """Called from the watcher thread. Schedules a push on the event loop,
        coalesced so we send at most one event every COALESCE_INTERVAL.
        """
        if self._loop is None:
            return
        now = time.monotonic()
        if now - self._last_push < COALESCE_INTERVAL:
            return
        self._last_push = now
        self._loop.call_soon_threadsafe(self._fanout)

    def _fanout(self) -> None:
        for q in list(self._subscribers):
            # drop if subscriber is full — they'll catch up on the next event
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> "asyncio.Queue[None]":
        q: asyncio.Queue[None] = asyncio.Queue(maxsize=4)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[None]") -> None:
        self._subscribers.discard(q)


def make_router(
    rollup: Rollup,
    broadcaster: Broadcaster,
    labeler: Labeler | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/usage/windows")
    def windows() -> dict:
        return _jsonable(rollup.snapshot_windows())

    @router.get("/usage/groups")
    def groups(
        by: str = Query("topic", pattern="^(topic|session|project)$"),
        window: str = Query("1h", alias="range", pattern="^(1h|4h|1d|7d|30d)$"),
    ) -> dict:
        # Range maps to a sliding window in minutes; rollup filters its
        # raw record list to that window before grouping.
        range_minutes = {
            "1h": 60, "4h": 240, "1d": 1440,
            "7d": 7 * 1440, "30d": 30 * 1440,
        }[window]
        # Heuristic re-attribution: any session whose dominant topic is
        # unclassified but whose early prompts mention a Jira ticket gets
        # overridden to that ticket. Cheap regex, recomputed each request.
        session_overrides: dict[str, str] = {}
        for s in rollup.snapshot_sessions():
            if not s.topic_id or not s.topic_id.startswith("unclassified:"):
                continue
            inferred = infer_session_ticket(s.early_user_prompts)
            if inferred:
                session_overrides[s.session_id] = inferred
            sidecar = read_session_sidecar(s.session_id)
            if sidecar:
                # A free-text `topic` (e.g. a CVI chat title) re-labels the
                # session as `custom:<topic>`; topic_display_label strips the
                # prefix. Precedence: ticket > topic > prompt-inferred, so the
                # ticket assignment stays last and wins when both are present.
                topic = sidecar.get("topic")
                if isinstance(topic, str) and topic.strip():
                    session_overrides[s.session_id] = f"custom:{topic.strip()}"
                if sidecar.get("ticket"):
                    session_overrides[s.session_id] = sidecar["ticket"]
        rows = [
            _jsonable(r)
            for r in rollup.windowed_groups(
                by, range_minutes, session_overrides=session_overrides
            )
        ]
        if by == "topic":
            for r in rows:
                r["label"] = topic_display_label(r["topic_id"])
                r["summary"] = (
                    labeler.get_summary(r["topic_id"]) if labeler else None
                )
        rows.sort(key=lambda r: r.get("output", 0), reverse=True)
        return {"by": by, "range": window, "rows": rows}

    @router.get("/usage/timeseries")
    def timeseries(
        window: str = Query("1h", alias="range", pattern="^(1h|4h|1d|7d|30d)$"),
        tz: str = Query("local", pattern="^(local|utc)$"),
    ) -> dict:
        # 1h/4h show every minute (60/240 bars). 1d aggregates per-minute
        # data to 10-minute buckets (144 bars) — minute-level was too noisy
        # at this zoom. 7d uses 1-hour buckets (168 bars), 30d uses 4-hour
        # buckets (180 bars). tz controls whether bucket boundaries land
        # on local or UTC midnight.
        minute_windows = {"1h": 60, "4h": 240}
        if window in minute_windows:
            data = rollup.snapshot_timeseries(minute_windows[window], tz=tz)
            granularity = "minute"
        elif window == "1d":
            minute_data = rollup.snapshot_timeseries(1440, tz=tz)
            data = _aggregate_buckets(minute_data, 10)
            granularity = "10min"
        else:
            total_min = 7 * 1440 if window == "7d" else 30 * 1440
            bucket_min = 60 if window == "7d" else 240
            minute_data = rollup.snapshot_timeseries(total_min, tz=tz)
            data = _aggregate_buckets(minute_data, bucket_min)
            granularity = "hour" if window == "7d" else "4hour"
        return {
            "range": window,
            "tz": tz,
            "granularity": granularity,
            "buckets": [{"t": t, "output": v} for t, v in data],
        }

    @router.get("/stream")
    async def stream(request: Request) -> StreamingResponse:
        broadcaster.attach_loop(asyncio.get_running_loop())
        q = await broadcaster.subscribe()

        async def gen():
            try:
                # send initial snapshot immediately on connect
                yield _sse({"type": "snapshot",
                            "windows": _jsonable(rollup.snapshot_windows())})
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        await asyncio.wait_for(q.get(), timeout=15.0)
                        yield _sse({"type": "snapshot",
                                    "windows": _jsonable(rollup.snapshot_windows())})
                    except asyncio.TimeoutError:
                        # heartbeat keeps proxies / browsers from closing
                        yield ": ping\n\n"
            finally:
                broadcaster.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    return router


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _aggregate_buckets(
    minute_data: list[tuple[str, int]], bucket_size_min: int,
) -> list[tuple[str, int]]:
    """Round each minute timestamp DOWN to the nearest bucket_size_min
    boundary (anchored at midnight), then sum outputs in each bucket."""
    out: dict[str, int] = {}
    for ts_iso, output in minute_data:
        try:
            dt = datetime.datetime.fromisoformat(ts_iso)
        except ValueError:
            continue
        sec_of_day = dt.hour * 3600 + dt.minute * 60
        bucket_sec = (sec_of_day // (bucket_size_min * 60)) * (bucket_size_min * 60)
        bucket_dt = dt.replace(
            hour=bucket_sec // 3600,
            minute=(bucket_sec % 3600) // 60,
            second=0,
            microsecond=0,
        )
        key = bucket_dt.isoformat()
        out[key] = out.get(key, 0) + output
    return sorted(out.items(), key=lambda kv: kv[0])
