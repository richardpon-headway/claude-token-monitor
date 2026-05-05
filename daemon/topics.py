"""Heuristic topic assignment.

Topics are Jira-style ticket IDs (e.g. COR-144) or 'unclassified:<project>'
when no ticket can be found.

Two entry points:
  - assign_topic_for_record(git_branch, current_prompt_ticket, project)
        Per-record resolver used by the parser. Priority order:
        gitBranch → most recent user-prompt mention in this session →
        project folder → unclassified. This is the resolver of record.
  - assign_topic(early_user_prompts, project)
        Legacy session-level resolver. Still here for tests/backward-compat
        but no longer used for primary attribution.

Pure functions only — no state. Caller maintains "current_prompt_ticket"
across records of the same session and passes it in.
"""
from __future__ import annotations

import re
from collections import Counter

# Match Jira-style ticket IDs. Negative lookbehind for any letter so the
# ticket isn't fused with a preceding word (e.g. branch names like
# 'zendesk_trigger_setup_COR-144' — `\b` alone fails because `_` is a word
# char, so there's no boundary between `_` and `C`).
TICKET_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2,5}-\d+)\b")


def extract_tickets(text: str) -> list[str]:
    if not text:
        return []
    return TICKET_RE.findall(text)


def assign_topic_for_record(
    git_branch: str | None,
    current_prompt_ticket: str | None,
    project: str,
) -> str:
    """Resolve the topic for a single usage record.

    Priority: gitBranch (highest, most reliable signal) > most-recent
    user-prompt ticket mention in this session > project folder > unclassified.
    """
    if git_branch:
        tickets = extract_tickets(git_branch)
        if tickets:
            return tickets[0]
    if current_prompt_ticket:
        return current_prompt_ticket
    folder_tickets = extract_tickets(project)
    if folder_tickets:
        return folder_tickets[0]
    return f"unclassified:{project}"


def assign_topic(early_user_prompts: list[str], project: str) -> str:
    """Legacy session-level topic assignment (most-common ticket wins).

    Kept for backward-compat tests; the per-record resolver above is the
    primary path now.
    """
    counts: Counter[str] = Counter()
    counts.update(extract_tickets(project))
    for p in early_user_prompts[:5]:
        counts.update(extract_tickets(p))
    if not counts:
        return f"unclassified:{project}"
    return counts.most_common(1)[0][0]


def topic_display_label(topic_id: str) -> str:
    if topic_id.startswith("unclassified:"):
        project = topic_id.split(":", 1)[1]
        return f"{project} (no ticket)"
    return topic_id
