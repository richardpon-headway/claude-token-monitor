# claude-token-monitor

[![tests](https://github.com/richardpon-headway/claude-token-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/richardpon-headway/claude-token-monitor/actions/workflows/tests.yml)

Local daemon + (planned) web UI for monitoring Claude Code token usage in real time.
Reads JSONL transcripts under `~/.claude/projects/`, exposes a localhost web
app that mirrors the `token-usage` skill's output and adds an Activity
Monitor-style live view.

Plan: `~/plans/plan-16-claude_token_monitor_app.md`.

## Status

- ✅ Daemon (FastAPI) — parser, in-memory rollup, watchdog file watcher, REST + SSE
- ✅ Pytest suite + GitHub Actions CI (Python tests + UI typecheck/build)
- ✅ Web UI (Vite + React 19 + Tailwind 4 + Recharts) — windows tiles, quota bar,
     sortable group table (Topic / Session / Project), live time-series chart
- ⏳ launchd autostart — out of v1 scope

## Quick start

```bash
make install   # uv sync + pnpm install
make dev       # daemon (:47821) + vite dev (:5173 with /api proxy)
# or:
make build-ui && make run   # production: daemon serves built bundle at /
```

In dev mode point your browser at http://localhost:5173 (Vite, hot-reload).
In production mode point it at http://127.0.0.1:47821 (daemon serves the
built static bundle).

The daemon scans `~/.claude/projects/` at startup, fills in older days from
`~/.claude/skills/token-usage/usage-cache.json`, then watches for changes
and pushes them to the UI over SSE.

Hit the API directly if you want:

```bash
curl http://127.0.0.1:47821/api/usage/windows
curl 'http://127.0.0.1:47821/api/usage/groups?by=topic'
curl 'http://127.0.0.1:47821/api/usage/timeseries?range=1h'
curl http://127.0.0.1:47821/api/stream   # SSE; pushes a snapshot per change
```

## Tests

```bash
make test
```

Numbers are verified to match the existing `~/.claude/skills/token-usage`
skill to-the-token (UTC windows exact; local windows match modulo
ongoing-usage drift between snapshots).

## Configuration

- `CLAUDE_TOKEN_MONITOR_HOST` — bind address (default `127.0.0.1`)
- `CLAUDE_TOKEN_MONITOR_PORT` — port (default `47821`)
