"""JSONL transcript parser for Claude Code session logs.

Adapted from ~/.claude/skills/token-usage/usage.py. Dedup-on-message-id rule
is identical: Claude Code records each assistant API response twice in the
transcript, so we count each billed message.id once. Extended here to also
extract per-session metadata (early user prompts, started_at, last_at) for
topic heuristics in daemon/topics.py.

Stateless. The rollup owns dedup state and per-file byte offsets.
"""
from __future__ import annotations

import datetime
import json
import pathlib
from dataclasses import dataclass, field

EARLY_PROMPT_CAP = 5
PROMPT_CHAR_CAP = 1000


@dataclass
class UsageRecord:
    session_id: str
    project: str
    timestamp_utc: datetime.datetime
    output_tokens: int
    input_tokens: int  # input + cache_creation + cache_read (matches usage.py)
    message_id: str | None
    git_branch: str | None = None  # checked-out branch when this turn ran
    topic_id: str = ""  # resolved by topics.assign_topic_for_record


@dataclass
class ParseResult:
    session_id: str
    project: str
    records: list[UsageRecord] = field(default_factory=list)
    early_user_prompts: list[str] = field(default_factory=list)
    started_at: datetime.datetime | None = None
    last_at: datetime.datetime | None = None
    bytes_read: int = 0  # absolute offset; rollup persists this


def _project_for(path: pathlib.Path, projects_dir: pathlib.Path) -> str:
    try:
        rel = path.relative_to(projects_dir)
    except ValueError:
        return "<unknown>"
    return rel.parts[0] if rel.parts else "<unknown>"


def _extract_user_text(rec: dict) -> str | None:
    msg = rec.get("message") or {}
    if msg.get("role") != "user":
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str) and t.strip():
                    return t.strip()
    return None


def _parse_ts(ts: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_file(
    path: pathlib.Path,
    *,
    projects_dir: pathlib.Path,
    seen_message_ids: set[str],
    start_offset: int = 0,
) -> ParseResult:
    """Parse a session JSONL file from start_offset to its last complete line.

    seen_message_ids is mutated in place; the rollup owns it and persists it
    across calls so duplicate message.ids written in separate flushes still
    dedup correctly.
    """
    from daemon.topics import assign_topic_for_record

    session_id = path.stem
    project = _project_for(path, projects_dir)
    result = ParseResult(session_id=session_id, project=project, bytes_read=start_offset)

    try:
        with path.open("rb") as f:
            f.seek(start_offset)
            raw = f.read()
    except OSError:
        return result

    last_nl = raw.rfind(b"\n")
    if last_nl == -1:
        return result  # no complete line yet; don't advance offset
    processed = raw[: last_nl + 1]
    result.bytes_read = start_offset + last_nl + 1

    for line in processed.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        dt_utc = _parse_ts(rec.get("timestamp", ""))
        if dt_utc is not None:
            if result.started_at is None or dt_utc < result.started_at:
                result.started_at = dt_utc
            if result.last_at is None or dt_utc > result.last_at:
                result.last_at = dt_utc

        text = _extract_user_text(rec)
        if text and len(result.early_user_prompts) < EARLY_PROMPT_CAP:
            result.early_user_prompts.append(text[:PROMPT_CHAR_CAP])

        msg = rec.get("message") or {}
        usage = msg.get("usage") or {}
        if not usage or dt_utc is None:
            continue

        mid = msg.get("id")
        if mid is not None:
            if mid in seen_message_ids:
                continue
            seen_message_ids.add(mid)

        i = usage.get("input_tokens") or 0
        o = usage.get("output_tokens") or 0
        cc = usage.get("cache_creation_input_tokens") or 0
        cr = usage.get("cache_read_input_tokens") or 0
        if not (i or o or cc or cr):
            continue

        git_branch = rec.get("gitBranch") or None
        topic_id = assign_topic_for_record(git_branch, project)
        result.records.append(UsageRecord(
            session_id=session_id,
            project=project,
            timestamp_utc=dt_utc,
            output_tokens=o,
            input_tokens=i + cc + cr,
            message_id=mid,
            git_branch=git_branch,
            topic_id=topic_id,
        ))

    return result
