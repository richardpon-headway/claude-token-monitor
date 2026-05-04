from __future__ import annotations

from daemon.parser import parse_file


def test_dedup_on_message_id(make_session):
    projects_dir, write, record, now = make_session
    ts = now()
    path = write("proj-a", "sess-1", [
        record(role="user", text="hello"),
        record(msg_id="m1", timestamp=ts, output=100, input_=50),
        # duplicate: Claude Code logs each assistant turn twice
        record(msg_id="m1", timestamp=ts, output=100, input_=50),
        record(msg_id="m2", timestamp=ts, output=200, input_=80),
    ])
    seen: set[str] = set()
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=seen)
    assert len(r.records) == 2
    assert sum(x.output_tokens for x in r.records) == 300
    assert seen == {"m1", "m2"}


def test_input_tokens_includes_cache(make_session):
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="x", timestamp=now(), output=10,
               input_=5, cache_creation=3, cache_read=2),
    ])
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert r.records[0].input_tokens == 10  # 5 + 3 + 2
    assert r.records[0].output_tokens == 10


def test_skips_records_with_no_usage(make_session):
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(role="user", text="hi"),
        record(msg_id="m1", timestamp=now(), output=0, input_=0),  # all-zero
        record(msg_id="m2", timestamp=now(), output=42),
    ])
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert len(r.records) == 1
    assert r.records[0].message_id == "m2"


def test_early_user_prompts_capped_at_5(make_session):
    projects_dir, write, record, now = make_session
    prompts = [f"prompt {i}" for i in range(10)]
    records = [record(role="user", text=p) for p in prompts]
    path = write("p", "s", records)
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert r.early_user_prompts == prompts[:5]


def test_early_user_prompts_extracts_from_content_blocks(make_session):
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        {"message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "content": "noise"},
                {"type": "text", "text": "  fix COR-144 please  "},
            ],
        }},
    ])
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert r.early_user_prompts == ["fix COR-144 please"]


def test_tail_offset_partial_line_safe(make_session, tmp_path):
    """If the file ends mid-line (mid-flush), bytes_read must NOT advance past
    the last newline — otherwise we'd skip the partial record on next read."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="m1", timestamp=now(), output=100),
    ])
    # Append an incomplete line (simulating an in-progress write)
    with path.open("ab") as f:
        f.write(b'{"timestamp": "' + now().encode() + b'", "message":')
    seen: set[str] = set()
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=seen)
    assert len(r.records) == 1
    # bytes_read should be at the end of the FIRST line, not into the partial.
    full = path.read_bytes()
    first_nl = full.index(b"\n") + 1
    assert r.bytes_read == first_nl

    # Now finish writing the second record and re-parse from the saved offset
    with path.open("ab") as f:
        f.write(b' {"id": "m2", "usage": {"output_tokens": 50, "input_tokens": 0}}}\n')
    r2 = parse_file(path, projects_dir=projects_dir,
                    seen_message_ids=seen, start_offset=r.bytes_read)
    assert len(r2.records) == 1
    assert r2.records[0].message_id == "m2"
    assert r2.records[0].output_tokens == 50


def test_assigns_topic_per_record_from_branch(make_session):
    """Per-record topic_id should follow the gitBranch on each record, not
    a single per-session value."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="m1", timestamp=now(), output=10,
               git_branch="feat/COR-144-foo"),
        record(msg_id="m2", timestamp=now(), output=20,
               git_branch="feat/COR-119-bar"),
    ])
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert [rec.topic_id for rec in r.records] == ["COR-144", "COR-119"]


def test_assigns_topic_from_user_prompt_when_branch_lacks_ticket(make_session):
    """When the branch has no ticket, assistant tokens after a user prompt
    mentioning a ticket should be attributed to that ticket."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="m1", timestamp=now(), output=10, git_branch="main"),
        record(role="user", text="now let's work on COR-144"),
        record(msg_id="m2", timestamp=now(), output=20, git_branch="main"),
        record(role="user", text="actually switch to COR-119"),
        record(msg_id="m3", timestamp=now(), output=30, git_branch="main"),
    ])
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert [rec.topic_id for rec in r.records] == [
        "unclassified:p", "COR-144", "COR-119",
    ]


def test_current_prompt_ticket_carries_across_incremental_parses(make_session):
    """Rollup persists current_prompt_ticket between incremental reads of the
    same file. Verify the parser threads it through correctly."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(role="user", text="working on COR-144"),
        record(msg_id="m1", timestamp=now(), output=10, git_branch="main"),
    ])
    r1 = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert r1.current_prompt_ticket == "COR-144"
    assert r1.records[0].topic_id == "COR-144"

    # Append a new assistant turn (no new user prompt) and re-parse from offset
    import json
    with path.open("a") as f:
        f.write(json.dumps({
            "message": {"id": "m2", "role": "assistant",
                        "usage": {"input_tokens": 0, "output_tokens": 50}},
            "timestamp": now(),
            "gitBranch": "main",
        }) + "\n")
    r2 = parse_file(
        path, projects_dir=projects_dir, seen_message_ids={"m1"},
        start_offset=r1.bytes_read,
        current_prompt_ticket=r1.current_prompt_ticket,
    )
    assert r2.records[0].topic_id == "COR-144"  # carried forward


def test_captures_git_branch_per_record(make_session):
    """Each UsageRecord should carry the gitBranch field present in the
    JSONL row, since branches change mid-session and drive per-record
    topic attribution."""
    projects_dir, write, record, now = make_session
    path = write("p", "s", [
        record(msg_id="m1", timestamp=now(), output=10,
               git_branch="zendesk_trigger_setup_COR-144"),
        record(msg_id="m2", timestamp=now(), output=20,
               git_branch="main"),
        record(msg_id="m3", timestamp=now(), output=30),  # no gitBranch
    ])
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    branches = [rec.git_branch for rec in r.records]
    assert branches == ["zendesk_trigger_setup_COR-144", "main", None]


def test_project_resolution(make_session):
    projects_dir, write, record, now = make_session
    path = write("my-project-folder", "session-abc", [
        record(msg_id="m", timestamp=now(), output=1),
    ])
    r = parse_file(path, projects_dir=projects_dir, seen_message_ids=set())
    assert r.project == "my-project-folder"
    assert r.session_id == "session-abc"
