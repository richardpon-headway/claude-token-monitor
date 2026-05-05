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
    # Dominant topic recomputed from segments — only one segment, so it wins.
    assert r.by_session["s1"].topic_id == "COR-144"
    assert "COR-144" in r.by_session["s1"].segments


def test_topic_unclassified_when_no_ticket(make_session):
    projects_dir, write, record, now = make_session
    path = write("plain-project", "s1", [
        record(role="user", text="just a question"),
        record(msg_id="m1", timestamp=now(), output=100),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    assert r.by_session["s1"].topic_id == "unclassified:plain-project"


def test_session_with_branch_switch_creates_two_segments(make_session):
    """Mid-session branch switch should split tokens across two topic
    segments, not lump them into one."""
    projects_dir, write, record, now = make_session
    path = write("plain-project", "s1", [
        record(msg_id="m1", timestamp=now(), output=300, git_branch="feat/COR-144-foo"),
        record(msg_id="m2", timestamp=now(), output=200, git_branch="feat/COR-119-bar"),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    s = r.by_session["s1"]
    assert s.output == 500
    assert set(s.segments.keys()) == {"COR-144", "COR-119"}
    assert s.segments["COR-144"].output == 300
    assert s.segments["COR-119"].output == 200
    # Dominant topic is the one with the most output.
    assert s.topic_id == "COR-144"


def test_topic_aggregates_from_segments_across_sessions(make_session):
    """A topic's totals = sum of all segments matching that topic across
    every session that touched it."""
    projects_dir, write, record, now = make_session
    p1 = write("alpha", "s1", [
        record(msg_id="a1", timestamp=now(), output=100, git_branch="feat/COR-144"),
        record(msg_id="a2", timestamp=now(), output=50, git_branch="main"),
    ])
    p2 = write("alpha", "s2", [
        record(msg_id="b1", timestamp=now(), output=200, git_branch="feat/COR-144"),
    ])
    r = Rollup()
    _ingest(r, projects_dir, p1)
    _ingest(r, projects_dir, p2)
    by_topic = {t.topic_id: t for t in r.snapshot_topics()}
    assert by_topic["COR-144"].output == 300  # 100 + 200
    assert by_topic["COR-144"].sessions == 2  # both sessions touched it
    assert by_topic["unclassified:alpha"].output == 50
    assert by_topic["unclassified:alpha"].sessions == 1


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


def test_per_minute_dual_keyed_local_and_utc(make_session):
    """Each ingested record should land in BOTH by_minute_local and
    by_minute_utc with equal totals, so /api/usage/timeseries can serve
    either timezone without reaggregating raw records."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="m1", timestamp=now(), output=300),
        record(msg_id="m2", timestamp=now(), output=200),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    assert sum(r.by_minute_local.values()) == 500
    assert sum(r.by_minute_utc.values()) == 500


def test_snapshot_timeseries_tz_arg(make_session):
    """tz='local' returns local-iso keys, tz='utc' returns UTC-iso keys.
    Both summed totals match."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="m1", timestamp=now(), output=100),
        record(msg_id="m2", timestamp=now(), output=200),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    local = r.snapshot_timeseries(60, tz="local")
    utc = r.snapshot_timeseries(60, tz="utc")
    assert sum(v for _, v in local) == sum(v for _, v in utc) == 300
    # UTC iso has '+00:00' suffix; local has the machine's offset.
    assert utc and utc[0][0].endswith("+00:00")


def test_utc_windows_exclude_today(make_session):
    """usage.py's UTC windows are 'Last N complete UTC days' — today excluded.
    Local windows include today (still-ticking). Regression for parity bug
    found 2026-05-04 against /token-usage output."""
    import datetime
    projects_dir, write, record, now = make_session
    today_utc = datetime.datetime.now(datetime.timezone.utc).date()
    today_utc_iso = today_utc.isoformat()
    yesterday_utc_iso = (today_utc - datetime.timedelta(days=1)).isoformat()
    today_local = datetime.datetime.now().astimezone().date().isoformat()

    r = Rollup()
    # Seed today's UTC bucket only (a value impossible to ignore if included).
    r.load_cache_days(
        by_utc_date={
            today_utc_iso: {"output": 1_000_000, "input": 0, "messages": 1},
            yesterday_utc_iso: {"output": 7, "input": 0, "messages": 1},
        },
        by_local_date={
            today_local: {"output": 5, "input": 0, "messages": 1},
        },
    )
    w = r.snapshot_windows()
    # UTC windows must exclude today_utc's 1M.
    assert w["last_7d_utc"]["output"] == 7
    assert w["last_30d_utc"]["output"] == 7
    # Local "today" window must include today_local.
    assert w["today_local"]["output"] == 5


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
