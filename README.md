# claude-token-monitor

[![tests](https://github.com/richardpon-headway/claude-token-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/richardpon-headway/claude-token-monitor/actions/workflows/tests.yml)

Local daemon + (planned) web UI for monitoring Claude Code token usage in real time.
Reads JSONL transcripts under `~/.claude/projects/`, exposes a localhost web
app that mirrors the `token-usage` skill's output and adds an Activity
Monitor-style live view.

Plan: `~/plans/plan-16-claude_token_monitor_app.md`.

## Status

- ✅ Daemon (FastAPI) — parser, in-memory rollup, watchdog file watcher, REST + SSE
- ✅ Pytest suite + GitHub Actions CI
- ⏳ Web UI (Vite + React + Tailwind + Recharts) — not yet scaffolded
- ⏳ launchd autostart — out of v1 scope

## Quick start

```bash
make install   # uv sync (pins python; skips pnpm until ui/ is scaffolded)
make run       # boots the daemon on http://127.0.0.1:47821
```

The daemon scans `~/.claude/projects/` at startup, fills in older days from
`~/.claude/skills/token-usage/usage-cache.json`, then watches for changes.

Until the UI is built, hit the API directly:

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
