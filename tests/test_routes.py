"""End-to-end tests for the /api/usage/groups route's sidecar override.

Exercises the full path the unit tests cover in pieces: a session-meta
sidecar -> the `groups` handler building a `custom:` override -> rollup
re-attribution -> the display label. No such end-to-end test existed before.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon import routes
from daemon.parser import parse_file
from daemon.rollup import Rollup
from daemon.routes import Broadcaster, make_router


@pytest.fixture
def sidecar_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    d = tmp_path / "session-meta"
    d.mkdir()
    monkeypatch.setattr(routes, "SIDECAR_DIR", d)
    routes._sidecar_cache.clear()
    yield d
    routes._sidecar_cache.clear()


def _client(rollup: Rollup) -> TestClient:
    app = FastAPI()
    app.include_router(make_router(rollup, Broadcaster(), labeler=None))
    return TestClient(app)


def _topic_rows(client: TestClient) -> dict[str, dict]:
    resp = client.get("/api/usage/groups", params={"by": "topic", "range": "1d"})
    assert resp.status_code == 200
    return {r["topic_id"]: r for r in resp.json()["rows"]}


def test_groups_uses_free_text_topic_sidecar_as_label(
    make_session, sidecar_dir: pathlib.Path
):
    """A sidecar with a free-text `topic` re-labels an otherwise-unclassified
    session's tokens by that title, shown verbatim (no `custom:` prefix)."""
    import datetime as _dt

    projects_dir, write, record, _now = make_session
    fresh = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    path = write("p", "s", [
        record(msg_id="m1", timestamp=fresh, output=120, git_branch="main"),
    ])
    rollup = Rollup()
    parsed = parse_file(
        path,
        projects_dir=projects_dir,
        seen_message_ids=rollup.seen_message_ids,
        start_offset=rollup.file_offset(str(path)),
    )
    rollup.ingest(parsed, file_path=str(path))

    (sidecar_dir / "s.json").write_text(
        json.dumps({"session_id": "s", "started_via": "cvi", "topic": "Fix the progress bar"})
    )

    rows = _topic_rows(_client(rollup))
    assert "custom:Fix the progress bar" in rows
    row = rows["custom:Fix the progress bar"]
    assert row["output"] == 120
    assert row["label"] == "Fix the progress bar"
    assert not any(k.startswith("unclassified:") for k in rows)


def test_groups_sidecar_ticket_wins_over_topic(
    make_session, sidecar_dir: pathlib.Path
):
    """When a sidecar carries both a ticket and a free-text topic, the ticket
    takes precedence (it's the more specific signal)."""
    import datetime as _dt

    projects_dir, write, record, _now = make_session
    fresh = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    path = write("p", "s", [
        record(msg_id="m1", timestamp=fresh, output=90, git_branch="main"),
    ])
    rollup = Rollup()
    parsed = parse_file(
        path,
        projects_dir=projects_dir,
        seen_message_ids=rollup.seen_message_ids,
        start_offset=rollup.file_offset(str(path)),
    )
    rollup.ingest(parsed, file_path=str(path))

    (sidecar_dir / "s.json").write_text(
        json.dumps({"session_id": "s", "ticket": "PROJ-7", "topic": "some title"})
    )

    rows = _topic_rows(_client(rollup))
    assert rows["PROJ-7"]["output"] == 90
    assert "custom:some title" not in rows
