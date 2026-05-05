# claude-token-monitor

[![tests](https://github.com/richardpon-headway/claude-token-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/richardpon-headway/claude-token-monitor/actions/workflows/tests.yml)

Local daemon + web UI for monitoring Claude Code token usage in real time.
Reads the JSONL transcripts under `~/.claude/projects/`, exposes a
`127.0.0.1`-only web app that mirrors the `token-usage` skill's totals
exactly and adds an Activity Monitor-style live view.

## Features

- **Today / 7d / 30d tiles** with per-tile sparklines (today: hourly bars;
  longer windows: daily bars + dashed 1× / 2× / N× quota lines).
- **Quota bar** that auto-scales past 100% with vertical tick marks at every
  100% increment, so 244% looks distinctly different from 105%.
- **Activity chart** with adjustable range (`1h` / `4h` / `1d` / `7d` / `30d`)
  and a `LOCAL ↔ UTC` toggle. Bars use sub-day buckets at the longer ranges
  (1-hour buckets for 7d, 4-hour for 30d) — Datadog-style density.
- **Topic / Session / Project table** that follows the same range selector.
  Topics are extracted by regex from gitBranch, recent user prompts, and
  project-folder names. Real Jira ticket summaries (via `acli`) plus
  `claude -p` fallback for unticketed buckets.
- **Live updates over SSE** — 100–600 ms typical latency from a token
  landing on disk to the UI reflecting it. Falls back to 10 s polling
  if SSE drops.

## Quick start

```bash
mise trust && mise install   # installs uv, node, pnpm at versions in mise.toml
make install                 # uv sync + pnpm install
make dev                     # daemon (:47821) + vite dev (:5173 with /api proxy)
# or:
make build-ui && make run    # production: daemon serves built bundle at /
```

In dev mode point your browser at <http://localhost:5173> (Vite, hot-reload).
In production mode point it at <http://127.0.0.1:47821> (daemon serves the
built static bundle).

To stop, `Ctrl-C` the `make dev` / `make run` process. To restart after
pulling new code, kill the daemon and re-run; the daemon reads its on-disk
caches at startup so no state is lost.

## Long history (Claude Code retention setting)

By default Claude Code only keeps transcripts for **30 days** and rotates
older ones out. You can extend that via `~/.claude/settings.json`:

```json
{
  "cleanupPeriodDays": 365
}
```

Bump it to 90, 180, 365, or whatever makes sense — older transcripts will
stick around in `~/.claude/projects/` and show up in the daemon's longer
windows. The daemon scans the last **365 days** at startup (no env var
needed), so anything you retain shows up automatically. Startup takes a
few seconds for a year of transcripts; after that, watchdog handles new
data incrementally.

## API

Direct calls if you want to build something on top, or for debugging:

```bash
curl http://127.0.0.1:47821/api/usage/windows
curl 'http://127.0.0.1:47821/api/usage/groups?by=topic&range=1h'
curl 'http://127.0.0.1:47821/api/usage/timeseries?range=4h&tz=local'
curl http://127.0.0.1:47821/api/stream    # SSE; pushes a snapshot per change
```

`range` accepts `1h | 4h | 1d | 7d | 30d`. `tz` accepts `local | utc`.

## Tests

```bash
make test             # pytest
cd ui && pnpm test    # vitest
```

Numbers are verified against the existing `~/.claude/skills/token-usage`
skill (UTC windows match exactly to-the-token; local windows match modulo
ongoing-usage drift between snapshots).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_TOKEN_MONITOR_HOST` | `127.0.0.1` | bind address — keep on loopback unless you know what you're doing |
| `CLAUDE_TOKEN_MONITOR_PORT` | `47821` | HTTP / SSE port |

Caches:

- Token-usage skill cache: `~/.claude/skills/token-usage/usage-cache.json`
  (per-day totals; the daemon reads it at startup to fill in days that
  rotated out of the live JSONL window).
- Topic-summary cache: `~/.cache/claude-token-monitor/topic-summaries.json`
  (Jira titles + LLM-generated descriptions per topic; survives daemon
  restarts so summaries reappear instantly).
