"""Heuristic topic assignment.

Topics are Jira-style ticket IDs (e.g. PROJ-144), 'unclassified:<project>'
(no branch info) or 'unclassified:<project>#<branch>' (branch-scoped
unclassified bucket — keeps ad-hoc work in different branches from
collapsing into one mega-row).

Two entry points:
  - assign_topic_for_record(git_branch, project)
        Per-record resolver used by the parser. Priority:
        gitBranch ticket > project folder ticket > unclassified.
        Pure function, no state.
  - assign_topic(early_user_prompts, project)
        Legacy session-level resolver. Kept for backward-compat tests
        only — no longer used for primary attribution.
"""
from __future__ import annotations

import re
from collections import Counter

# Match Jira-style ticket IDs. Both ends use negative lookarounds rather
# than `\b` because `_` is a word char in regex — so `\b` fails between
# `_` and a letter on the left ('setup_PROJ-144') AND between a digit and
# `_` on the right ('PROJ-185_wits...'). We want to allow `_` as a
# separator on both sides while still rejecting alphanumeric runs that
# would change the ticket value (e.g. 'XPROJ-144' or 'PROJ-1850abc').
TICKET_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2,5}-\d+)(?![A-Za-z0-9])")


def extract_tickets(text: str) -> list[str]:
    if not text:
        return []
    return TICKET_RE.findall(text)


def infer_session_ticket(early_user_prompts: list[str]) -> str | None:
    """Most-common ticket mentioned across a session's early user prompts,
    or None if none mention one. Ties broken by first occurrence.

    Used to re-attribute `unclassified:` sessions whose branch/folder
    didn't carry a ticket but whose opening prompts did.
    """
    counts: Counter[str] = Counter()
    for p in early_user_prompts:
        counts.update(extract_tickets(p))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def assign_topic_for_record(
    git_branch: str | None,
    project: str,
) -> str:
    """Resolve the topic for a single usage record.

    Priority: gitBranch ticket > project folder ticket > unclassified.

    The previous version also had a "most-recent user-prompt ticket
    mention" fallback — dropped because it leaked across context
    switches (a single mention of PROJ-X mid-session would tag every
    record after that as PROJ-X even after the conversation moved on).
    gitBranch and folder are deterministic; ad-hoc work without either
    falls into a branch-scoped unclassified bucket below.
    """
    if git_branch:
        tickets = extract_tickets(git_branch)
        if tickets:
            return tickets[0]
    folder_tickets = extract_tickets(project)
    if folder_tickets:
        return folder_tickets[0]
    # No ticket anywhere — bucket by branch within the project so a
    # long-lived root checkout doesn't collapse all ad-hoc work into one
    # mega-row. `unclassified:<project>` (no branch) means we don't know
    # the branch (record had no gitBranch field).
    if git_branch:
        return f"unclassified:{project}#{git_branch}"
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
        rest = topic_id.split(":", 1)[1]
        # "<project>#<branch>" — split branch out so the user sees it.
        if "#" in rest:
            project, branch = rest.split("#", 1)
            return f"{_short_project(project)} / {branch} (no ticket)"
        return f"{_short_project(rest)} (no ticket)"
    return topic_id


def _short_project(project: str) -> str:
    """Trim the path-encoded project name to its last segment.

    `~/.claude/projects/` directories look like
    '-Users-username-development-myrepo-worktree-PROJ-123-foo' — we just want
    the leaf. Drop the leading dash and grab the last path-like component
    (heuristic: split on '-' and take the tail after the last segment that
    looks like a 'home' path).
    """
    s = project.lstrip("-")
    # Common case: "-Users-<user>-development-<thing>" — keep <thing>.
    if s.startswith("Users-"):
        parts = s.split("-")
        if len(parts) >= 4 and parts[2] == "development":
            return "-".join(parts[3:])
    return s
