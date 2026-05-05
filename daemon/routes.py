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
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from daemon.labeler import Labeler
from daemon.rollup import Rollup
from daemon.topics import topic_display_label

COALESCE_INTERVAL = 0.5  # seconds between SSE pushes per subscriber


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
    def groups(by: str = Query("topic", pattern="^(topic|session|project)$")) -> dict:
        if by == "topic":
            rows = [
                {
                    **_jsonable(t),
                    "label": topic_display_label(t.topic_id),
                    "summary": labeler.get_summary(t.topic_id) if labeler else None,
                }
                for t in rollup.snapshot_topics()
            ]
        elif by == "project":
            rows = [_jsonable(p) for p in rollup.snapshot_projects()]
        else:
            rows = [_jsonable(s) for s in rollup.snapshot_sessions()]
        rows.sort(key=lambda r: r.get("output", 0), reverse=True)
        return {"by": by, "rows": rows}

    @router.get("/usage/timeseries")
    def timeseries(
        window: str = Query("1h", alias="range", pattern="^(1h|24h|7d|30d)$"),
    ) -> dict:
        if window == "1h":
            data = rollup.snapshot_timeseries(60)
            granularity = "minute"
        elif window == "24h":
            data = rollup.snapshot_timeseries(1440)
            granularity = "minute"
        else:
            days = 7 if window == "7d" else 30
            today = datetime.datetime.now(datetime.timezone.utc).astimezone().date()
            with rollup._lock:
                day_data = []
                for i in range(days):
                    d = (today - datetime.timedelta(days=days - 1 - i)).isoformat()
                    bucket = rollup.by_day_local.get(d)
                    day_data.append((d, bucket.output if bucket else 0))
            data = day_data
            granularity = "day"
        return {
            "range": window,
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
