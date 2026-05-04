from __future__ import annotations

from daemon.parser import parse_file
from daemon.rollup import Rollup


def _ingest(rollup: Rollup, projects_dir, path):
    r = parse_file(
        path,
        projects_dir=projects_dir,
        seen_message_ids=rollup.seen_message_ids,
        start_offset=rollup.file_offset(str(path)),
    )
    rollup.ingest(r, file_path=str(path))


def test_ingest_accumulates_day_and_session(make_session):
    projects_dir, write, record, now = make_session
    ts = now()
    path = write("p", "s1", [
        record(msg_id="m1", timestamp=ts, output=100, input_=10),
        record(msg_id="m2", timestamp=ts, output=200, input_=20),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    assert r.by_session["s1"].output == 300
    assert r.by_session["s1"].messages == 2
    # both records on the same UTC day
    assert sum(b.output for b in r.by_day_utc.values()) == 300


def test_ingest_idempotent_on_replay(make_session):
    """Re-parsing the same file should NOT double-count, because dedup state
    in seen_message_ids is shared across calls."""
    projects_dir, write, record, now = make_session
    ts = now()
    path = write("p", "s1", [
        record(msg_id="m1", timestamp=ts, output=100),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    _ingest(r, projects_dir, path)  # replay
    assert r.by_session["s1"].output == 100
    assert r.by_session["s1"].messages == 1


def test_topic_assigned_from_prompt(make_session):
    projects_dir, write, record, now = make_session
    path = write("plain-project", "s1", [
        record(role="user", text="please look into COR-144"),
        record(msg_id="m1", timestamp=now(), output=100),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    assert r.by_session["s1"].topic_id == "COR-144"


def test_topic_unclassified_when_no_ticket(make_session):
    projects_dir, write, record, now = make_session
    path = write("plain-project", "s1", [
        record(role="user", text="just a question"),
        record(msg_id="m1", timestamp=now(), output=100),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    assert r.by_session["s1"].topic_id == "unclassified:plain-project"


def test_load_cache_days_does_not_overwrite_logs(make_session):
    projects_dir, write, record, now = make_session
    ts = now()
    path = write("p", "s1", [
        record(msg_id="m1", timestamp=ts, output=100),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    # log gave us today's bucket
    log_day = next(iter(r.by_day_utc.keys()))
    log_bucket_output = r.by_day_utc[log_day].output

    r.load_cache_days(
        by_utc_date={log_day: {"output": 999999, "input": 0, "messages": 99}},
        by_local_date={},
    )
    # cache must NOT have overwritten the log-derived day
    assert r.by_day_utc[log_day].output == log_bucket_output


def test_load_cache_days_fills_missing_only(make_session):
    r = Rollup()
    r.load_cache_days(
        by_utc_date={
            "2026-04-01": {"output": 1000, "input": 500, "messages": 5},
        },
        by_local_date={},
    )
    assert r.by_day_utc["2026-04-01"].output == 1000


def test_snapshot_projects_aggregates_sessions(make_session):
    projects_dir, write, record, now = make_session
    ts = now()
    p1 = write("proj-x", "s1", [record(msg_id="a", timestamp=ts, output=100)])
    p2 = write("proj-x", "s2", [record(msg_id="b", timestamp=ts, output=200)])
    p3 = write("proj-y", "s3", [record(msg_id="c", timestamp=ts, output=50)])
    r = Rollup()
    for p in (p1, p2, p3):
        _ingest(r, projects_dir, p)
    by_proj = {p.project: p for p in r.snapshot_projects()}
    assert by_proj["proj-x"].sessions == 2
    assert by_proj["proj-x"].output == 300
    assert by_proj["proj-y"].sessions == 1
    assert by_proj["proj-y"].output == 50


def test_file_offset_persists_across_calls(make_session):
    projects_dir, write, record, now = make_session
    ts = now()
    path = write("p", "s1", [
        record(msg_id="m1", timestamp=ts, output=100),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    first_offset = r.file_offset(str(path))
    assert first_offset > 0

    # append a new record and re-ingest from the saved offset
    import json
    with path.open("a") as f:
        f.write(json.dumps({
            "message": {"id": "m2", "usage": {"output_tokens": 250, "input_tokens": 0}},
            "timestamp": now(),
        }) + "\n")
    _ingest(r, projects_dir, path)
    assert r.by_session["s1"].output == 350
    assert r.file_offset(str(path)) > first_offset
