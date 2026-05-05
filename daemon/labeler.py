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
import re
import subprocess

# Same shape as topics.TICKET_RE but anchored to the whole string — we use
# this on a topic_id, not free text.
TICKET_KEY_RE = re.compile(r"^[A-Z]{2,5}-\d+$")

ACLI_TIMEOUT_SEC = 8.0
CLAUDE_TIMEOUT_SEC = 30.0
PROMPTS_SAMPLE_CAP = 20


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
