from __future__ import annotations

from daemon.topics import assign_topic, extract_tickets, topic_display_label


def test_extract_tickets_finds_jira_ids():
    assert extract_tickets("fix COR-144 then DT-1890") == ["COR-144", "DT-1890"]


def test_extract_tickets_requires_2_to_5_uppercase():
    # too short
    assert extract_tickets("X-1") == []
    # too long
    assert extract_tickets("ABCDEF-1") == []
    # lowercase
    assert extract_tickets("cor-144") == []


def test_assign_topic_prefers_prompt_mention_over_folder():
    """A ticket mentioned in a prompt should beat a different ticket only in
    the folder name — most-common-wins."""
    topic = assign_topic(
        early_user_prompts=["work on COR-144", "still COR-144"],
        project="headway-worktree-COR-122-something",
    )
    assert topic == "COR-144"  # 2 mentions vs folder's 1


def test_assign_topic_falls_back_to_folder_ticket():
    topic = assign_topic(
        early_user_prompts=["just a generic question"],
        project="headway-worktree-COR-144-foo",
    )
    assert topic == "COR-144"


def test_assign_topic_unclassified_when_no_ticket():
    topic = assign_topic(
        early_user_prompts=["hello", "how are you"],
        project="headway",
    )
    assert topic == "unclassified:headway"


def test_assign_topic_only_uses_first_5_prompts():
    """Tickets in prompts beyond the first 5 should not count."""
    prompts = [
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "actually it's COR-144",  # 6th — should be ignored
    ]
    topic = assign_topic(prompts, project="plain-project")
    assert topic == "unclassified:plain-project"


def test_topic_display_label():
    assert topic_display_label("COR-144") == "COR-144"
    assert topic_display_label("unclassified:my-proj") == "my-proj (no ticket)"
