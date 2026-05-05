"""Daemon entrypoint.

`uv run python -m daemon.main` (via `make run`) does:
  1. Build a Rollup.
  2. Run initial_scan over ~/.claude/projects/ to populate it.
  3. Fill older days from ~/.claude/skills/token-usage/usage-cache.json.
  4. Start the Watcher (watchdog Observer) so live changes flow into the rollup.
  5. Mount /api/* routes (and the built UI at /, if it exists).
  6. Run uvicorn on 127.0.0.1:47821 (override host/port via env vars).
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from daemon.labeler import Labeler
from daemon.routes import Broadcaster, make_router
from daemon.rollup import Rollup
from daemon.watcher import Watcher, initial_scan

PROJECTS_DIR = pathlib.Path.home() / ".claude" / "projects"
CACHE_FILE = (
    pathlib.Path.home() / ".claude" / "skills" / "token-usage" / "usage-cache.json"
)
STATIC_DIR = pathlib.Path(__file__).parent / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47821
# How many days back to scan ~/.claude/projects/ at startup. Defaults to 35
# (Claude Code's default cleanupPeriodDays is 30 + 5-day buffer). Users who
# raise cleanupPeriodDays in ~/.claude/settings.json (e.g. 180, 365) should
# raise this too to see the full history they've retained.
DEFAULT_HISTORY_DAYS = 35


def _load_cache_into(rollup: Rollup) -> int:
    if not CACHE_FILE.exists():
        return 0
    try:
        cache = json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"warn: could not read cache file: {e}", file=sys.stderr)
        return 0
    by_utc = cache.get("by_utc_date", {})
    by_local = cache.get("by_local_date", {})
    rollup.load_cache_days(by_utc, by_local)
    return len(by_local)


def build_app() -> tuple[FastAPI, Watcher]:
    rollup = Rollup()

    history_days = int(
        os.environ.get("CLAUDE_TOKEN_MONITOR_HISTORY_DAYS", DEFAULT_HISTORY_DAYS)
    )
    print(
        f"scanning {PROJECTS_DIR} (last {history_days} days) ...",
        file=sys.stderr,
    )
    n_files = initial_scan(rollup, PROJECTS_DIR, mtime_cutoff_days=history_days)
    n_cache = _load_cache_into(rollup)
    print(
        f"  ingested {n_files} files, {len(rollup.by_session)} sessions, "
        f"{len(rollup.by_day_local)} local days "
        f"({n_cache} from cache)",
        file=sys.stderr,
    )

    broadcaster = Broadcaster()
    watcher = Watcher(rollup, PROJECTS_DIR, on_change=broadcaster.notify)
    labeler = Labeler(rollup)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        watcher.start()
        labeler.start()
        print("watcher + labeler started", file=sys.stderr)
        try:
            yield
        finally:
            labeler.stop()
            watcher.stop()

    app = FastAPI(title="claude-token-monitor", lifespan=lifespan)
    app.include_router(make_router(rollup, broadcaster, labeler))

    if STATIC_DIR.exists():
        # Built UI bundle present — serve it at /. Register AFTER /api/* so
        # API routes win.
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
    else:
        @app.get("/")
        def root() -> dict:
            return {
                "service": "claude-token-monitor",
                "ui": "not built (run `make build-ui`); meanwhile use /api/* directly",
                "endpoints": [
                    "/api/usage/windows",
                    "/api/usage/groups?by=topic|session|project",
                    "/api/usage/timeseries?range=1h|24h|7d|30d",
                    "/api/stream",
                ],
            }

    return app, watcher


def main() -> int:
    host = os.environ.get("CLAUDE_TOKEN_MONITOR_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CLAUDE_TOKEN_MONITOR_PORT", DEFAULT_PORT))

    app, _watcher = build_app()
    print(f"listening on http://{host}:{port}", file=sys.stderr)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except OSError as e:
        if "Address already in use" in str(e) or e.errno == 48:
            print(
                f"error: port {port} is already in use. "
                f"Set CLAUDE_TOKEN_MONITOR_PORT=<other> to override.",
                file=sys.stderr,
            )
            return 2
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
