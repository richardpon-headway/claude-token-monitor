from __future__ import annotations

from daemon.topics import (
    assign_topic,
    assign_topic_for_record,
    extract_tickets,
    topic_display_label,
)


def test_extract_tickets_finds_jira_ids():
    assert extract_tickets("fix COR-144 then DT-1890") == ["COR-144", "DT-1890"]


def test_extract_tickets_requires_2_to_5_uppercase():
    # too short
    assert extract_tickets("X-1") == []
    # too long
    assert extract_tickets("ABCDEF-1") == []
    # lowercase
    assert extract_tickets("cor-144") == []


def test_extract_tickets_handles_underscore_after_digits():
    """Branch names like 'rpon/COR-185_wits_...' must still match COR-185.
    Old `\\b` after the digit run failed because `_` is a word char."""
    assert extract_tickets("rpon/COR-185_wits_tables") == ["COR-185"]
    assert extract_tickets("feat/DT-1890_reduce_overhead") == ["DT-1890"]


def test_extract_tickets_rejects_glued_alphanumeric():
    """Don't extract from runs that would change the ticket meaning."""
    # COR-1850 is a valid 4-digit number after the dash, so this matches:
    assert extract_tickets("COR-1850") == ["COR-1850"]
    # But COR-185abc isn't a real ticket — letters change semantics.
    assert extract_tickets("COR-185abc") == []


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


def test_topic_display_label_branch_scoped():
    """Branch-scoped unclassified buckets show the branch in the label."""
    assert (
        topic_display_label("unclassified:-Users-rpon-development-headway#main")
        == "headway / main (no ticket)"
    )


# --- assign_topic_for_record (per-record resolver) ---------------------

def test_per_record_branch_wins_over_folder():
    topic = assign_topic_for_record(
        git_branch="zendesk_trigger_setup_COR-144",
        project="headway-worktree-COR-200-foo",
    )
    assert topic == "COR-144"


def test_per_record_falls_back_to_folder():
    topic = assign_topic_for_record(
        git_branch=None,
        project="headway-worktree-COR-144-foo",
    )
    assert topic == "COR-144"


def test_per_record_unclassified_branch_scoped_when_branch_known():
    """No ticket anywhere but we know the branch -> bucket by branch."""
    topic = assign_topic_for_record(git_branch="main", project="headway")
    assert topic == "unclassified:headway#main"


def test_per_record_unclassified_no_branch_when_branch_missing():
    topic = assign_topic_for_record(git_branch=None, project="headway")
    assert topic == "unclassified:headway"


def test_per_record_no_prompt_history_fallback():
    """We dropped the prompt-history fallback: a branch without a ticket
    no longer leaks attribution from prior prompts. It buckets by branch."""
    topic = assign_topic_for_record(
        git_branch="my-feature-branch",
        project="headway",
    )
    assert topic == "unclassified:headway#my-feature-branch"
