"""Helpers for building synthetic JSONL session files in tmpdir."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest


def _record(
    *,
    role: str = "assistant",
    msg_id: str | None = None,
    timestamp: str | None = None,
    output: int = 0,
    input_: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
    text: str | None = None,
) -> dict:
    msg: dict = {"role": role}
    if msg_id is not None:
        msg["id"] = msg_id
    if text is not None:
        msg["content"] = text
    if role == "assistant":
        msg["usage"] = {
            "input_tokens": input_,
            "output_tokens": output,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        }
    rec: dict = {"message": msg}
    if timestamp is not None:
        rec["timestamp"] = timestamp
    return rec


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def make_session(tmp_path: pathlib.Path):
    """Returns (projects_dir, write_session(project, session_id, records))."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    def _write(project: str, session_id: str, records: list[dict]) -> pathlib.Path:
        proj = projects_dir / project
        proj.mkdir(exist_ok=True)
        path = proj / f"{session_id}.jsonl"
        with path.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return path

    return projects_dir, _write, _record, _now_iso
