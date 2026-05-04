"""Heuristic topic assignment for sessions.

v1 strategy: look for Jira-style ticket IDs (e.g. COR-144) in the first few
user prompts and the project folder name. Most common ticket wins. Sessions
with no ticket fall under 'unclassified:<project>'.

Pure functions only — no state. Rollup calls assign_topic(prompts, project)
on each ingest and stores the result on SessionInfo.topic_id.

Future-extension hook: swap the body of assign_topic() to use embeddings or
LLM labeling without touching rollup or routes.
"""
from __future__ import annotations

import re
from collections import Counter

TICKET_RE = re.compile(r"\b([A-Z]{2,5}-\d+)\b")


def extract_tickets(text: str) -> list[str]:
    if not text:
        return []
    return TICKET_RE.findall(text)


def assign_topic(early_user_prompts: list[str], project: str) -> str:
    """Return a topic key for a session.

    Topic keys are either a ticket id (e.g. 'COR-144') or 'unclassified:<project>'.
    """
    counts: Counter[str] = Counter()
    # Project folder names like 'headway-worktree-COR-144-foo' often carry the
    # ticket; weight them the same as a single prompt mention. The 'most
    # common ticket wins' tiebreak then prefers the one the user actually
    # talked about most in early turns.
    counts.update(extract_tickets(project))
    for p in early_user_prompts[:5]:
        counts.update(extract_tickets(p))

    if not counts:
        return f"unclassified:{project}"
    # Counter.most_common returns ties in insertion order; project tickets
    # are inserted first, so a ticket present only in the folder name still
    # wins over no ticket at all but loses to one mentioned in prompts.
    return counts.most_common(1)[0][0]


def topic_display_label(topic_id: str) -> str:
    if topic_id.startswith("unclassified:"):
        project = topic_id.split(":", 1)[1]
        return f"{project} (no ticket)"
    return topic_id
