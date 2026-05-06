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


def test_topic_assigned_from_branch(make_session):
    """gitBranch is now the primary signal for the ticket. Prompt-history
    fallback was dropped (it leaked attribution across context switches)."""
    projects_dir, write, record, now = make_session
    path = write("plain-project", "s1", [
        record(role="user", text="please look into the carrier autocomplete"),
        record(msg_id="m1", timestamp=now(), output=100,
               git_branch="feat/COR-144-foo"),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
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
    # Branch-scoped unclassified bucket — main branch, no ticket.
    assert by_topic["unclassified:alpha#main"].output == 50
    assert by_topic["unclassified:alpha#main"].sessions == 1


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


def test_snapshot_windows_includes_spark_arrays(make_session):
    """Each window in snapshot_windows() should ship a 'spark' array of the
    expected length: 24 hourly buckets for today, 7 daily for 7d, 30 for
    30d. Sums in spark should match the window's output total."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="m1", timestamp=now(), output=100),
        record(msg_id="m2", timestamp=now(), output=200),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)
    w = r.snapshot_windows()
    assert len(w["today_local"]["spark"]) == 24
    assert len(w["last_7d_local"]["spark"]) == 7
    assert len(w["last_30d_local"]["spark"]) == 30
    assert len(w["last_7d_utc"]["spark"]) == 7
    assert len(w["last_30d_utc"]["spark"]) == 30
    # Today's hourly spark should sum to today's output total.
    assert sum(w["today_local"]["spark"]) == w["today_local"]["output"]
    # Local 7d/30d sums should match the headline output.
    assert sum(w["last_7d_local"]["spark"]) == w["last_7d_local"]["output"]
    assert sum(w["last_30d_local"]["spark"]) == w["last_30d_local"]["output"]


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


def test_utc_windows_include_today(make_session):
    """Both LOCAL and UTC last 7d/30d windows include today (in-progress
    day). Earlier we excluded today_utc to mirror token-usage's
    'complete UTC days' semantics, but that confused users — the
    rightmost bar should be 'today' regardless of timezone. Local
    parity with the skill is preserved; UTC parity is intentionally
    dropped."""
    import datetime
    projects_dir, write, record, now = make_session
    today_utc = datetime.datetime.now(datetime.timezone.utc).date()
    today_utc_iso = today_utc.isoformat()
    yesterday_utc_iso = (today_utc - datetime.timedelta(days=1)).isoformat()
    today_local = datetime.datetime.now().astimezone().date().isoformat()

    r = Rollup()
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
    # UTC windows must INCLUDE today_utc's 1M — sum is 1M + 7.
    assert w["last_7d_utc"]["output"] == 1_000_007
    assert w["last_30d_utc"]["output"] == 1_000_007
    # Local "today" window unchanged — includes today_local.
    assert w["today_local"]["output"] == 5


def test_windowed_groups_filters_by_timestamp(make_session):
    """Records older than the window's cutoff should not show up in the
    grouped totals — that's the whole point of the windowed query."""
    import datetime as _dt
    projects_dir, write, record, _now = make_session
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    fresh = now_utc.isoformat().replace("+00:00", "Z")
    stale = (now_utc - _dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    path = write("p", "s", [
        record(msg_id="m_old", timestamp=stale, output=999,
               git_branch="feat/COR-144"),
        record(msg_id="m_new", timestamp=fresh, output=42,
               git_branch="feat/COR-144"),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)

    # 1h window — only the fresh record (42 tokens) should count
    rows = r.windowed_groups("topic", range_minutes=60)
    assert len(rows) == 1
    assert rows[0]["topic_id"] == "COR-144"
    assert rows[0]["output"] == 42
    assert rows[0]["messages"] == 1

    # 4h window — both records should count (1041 tokens)
    rows4 = r.windowed_groups("topic", range_minutes=240)
    assert rows4[0]["output"] == 1041
    assert rows4[0]["messages"] == 2


def test_windowed_groups_session_segments_are_per_window(make_session):
    """Session rows from windowed_groups should expose a 'segments' map
    that reflects only what happened inside the window — older segments
    must not leak in."""
    import datetime as _dt
    projects_dir, write, record, _now = make_session
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    fresh = now_utc.isoformat().replace("+00:00", "Z")
    stale = (now_utc - _dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    path = write("p", "s", [
        record(msg_id="m1", timestamp=stale, output=300, git_branch="feat/COR-144"),
        record(msg_id="m2", timestamp=fresh, output=42, git_branch="feat/COR-119"),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)

    rows = r.windowed_groups("session", range_minutes=60)
    assert len(rows) == 1
    s = rows[0]
    assert s["session_id"] == "s"
    assert s["output"] == 42
    # segments dict only carries the in-window topic, not COR-144
    assert set(s["segments"].keys()) == {"COR-119"}
    assert s["topic_id"] == "COR-119"


def test_windowed_groups_session_overrides_reattribute_unclassified(make_session):
    """When session_overrides supplies a ticket for a session, the
    session's UNCLASSIFIED records get re-attributed; records that were
    already on a ticket-named branch are unchanged."""
    import datetime as _dt
    projects_dir, write, record, _now = make_session
    fresh = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    path = write("p", "s", [
        # half on a ticket-named branch (already tagged COR-144)
        record(msg_id="m1", timestamp=fresh, output=100,
               git_branch="feat/COR-144"),
        # half on main (unclassified by default)
        record(msg_id="m2", timestamp=fresh, output=50, git_branch="main"),
    ])
    r = Rollup()
    _ingest(r, projects_dir, path)

    # No override -> COR-144 (100) and an unclassified row (50)
    rows = r.windowed_groups("topic", range_minutes=60)
    by_topic = {x["topic_id"]: x for x in rows}
    assert by_topic["COR-144"]["output"] == 100
    unclassified_keys = [k for k in by_topic if k.startswith("unclassified:")]
    assert len(unclassified_keys) == 1
    assert by_topic[unclassified_keys[0]]["output"] == 50

    # With override -> the unclassified portion goes to COR-119,
    # the gitBranch-tagged portion stays as COR-144.
    rows2 = r.windowed_groups(
        "topic", range_minutes=60,
        session_overrides={"s": "COR-119"},
    )
    by_topic2 = {x["topic_id"]: x for x in rows2}
    assert by_topic2["COR-144"]["output"] == 100
    assert by_topic2["COR-119"]["output"] == 50
    assert not any(k.startswith("unclassified:") for k in by_topic2)


def test_windowed_groups_project_distinct_session_count(make_session):
    """Multiple sessions hitting the same project should count once each
    in the project row's `sessions` field."""
    import datetime as _dt
    projects_dir, write, record, _now = make_session
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    fresh = now_utc.isoformat().replace("+00:00", "Z")
    p1 = write("alpha", "s1", [record(msg_id="a1", timestamp=fresh, output=10)])
    p2 = write("alpha", "s2", [record(msg_id="b1", timestamp=fresh, output=20)])
    r = Rollup()
    _ingest(r, projects_dir, p1)
    _ingest(r, projects_dir, p2)
    rows = r.windowed_groups("project", range_minutes=60)
    assert len(rows) == 1
    assert rows[0]["project"] == "alpha"
    assert rows[0]["sessions"] == 2
    assert rows[0]["output"] == 30


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
