from __future__ import annotations

from daemon.topics import (
    assign_topic,
    assign_topic_for_record,
    extract_tickets,
    infer_session_ticket,
    topic_display_label,
)


def test_extract_tickets_finds_jira_ids():
    assert extract_tickets("fix PROJ-144 then TASK-1890") == ["PROJ-144", "TASK-1890"]


def test_extract_tickets_requires_2_to_5_uppercase():
    # too short
    assert extract_tickets("X-1") == []
    # too long
    assert extract_tickets("ABCDEF-1") == []
    # lowercase
    assert extract_tickets("proj-123") == []


def test_extract_tickets_handles_underscore_after_digits():
    """Branch names like 'username/PROJ-185_wits_...' must still match PROJ-185.
    Old `\\b` after the digit run failed because `_` is a word char."""
    assert extract_tickets("username/PROJ-185_wits_tables") == ["PROJ-185"]
    assert extract_tickets("feat/TASK-1890_reduce_overhead") == ["TASK-1890"]


def test_extract_tickets_rejects_glued_alphanumeric():
    """Don't extract from runs that would change the ticket meaning."""
    # PROJ-1850 is a valid 4-digit number after the dash, so this matches:
    assert extract_tickets("PROJ-1850") == ["PROJ-1850"]
    # But PROJ-185abc isn't a real ticket — letters change semantics.
    assert extract_tickets("PROJ-185abc") == []


def test_assign_topic_prefers_prompt_mention_over_folder():
    """A ticket mentioned in a prompt should beat a different ticket only in
    the folder name — most-common-wins."""
    topic = assign_topic(
        early_user_prompts=["work on PROJ-144", "still PROJ-144"],
        project="myrepo-worktree-PROJ-122-something",
    )
    assert topic == "PROJ-144"  # 2 mentions vs folder's 1


def test_assign_topic_falls_back_to_folder_ticket():
    topic = assign_topic(
        early_user_prompts=["just a generic question"],
        project="myrepo-worktree-PROJ-144-foo",
    )
    assert topic == "PROJ-144"


def test_assign_topic_unclassified_when_no_ticket():
    topic = assign_topic(
        early_user_prompts=["hello", "how are you"],
        project="myrepo",
    )
    assert topic == "unclassified:myrepo"


def test_assign_topic_only_uses_first_5_prompts():
    """Tickets in prompts beyond the first 5 should not count."""
    prompts = [
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "actually it's PROJ-144",  # 6th — should be ignored
    ]
    topic = assign_topic(prompts, project="plain-project")
    assert topic == "unclassified:plain-project"


def test_topic_display_label():
    assert topic_display_label("PROJ-144") == "PROJ-144"
    assert topic_display_label("unclassified:my-proj") == "my-proj (no ticket)"


def test_topic_display_label_branch_scoped():
    """Branch-scoped unclassified buckets show the branch in the label."""
    assert (
        topic_display_label("unclassified:-Users-username-development-myrepo#main")
        == "myrepo / main (no ticket)"
    )


def test_topic_display_label_custom_strips_prefix():
    """A free-text `custom:` topic (e.g. a session title) shows verbatim."""
    assert topic_display_label("custom:Fix the progress bar") == "Fix the progress bar"
    # A colon in the label itself is preserved (only the first split is taken).
    assert topic_display_label("custom:add CTM: free-text topic") == "add CTM: free-text topic"


# --- assign_topic_for_record (per-record resolver) ---------------------

def test_per_record_branch_wins_over_folder():
    topic = assign_topic_for_record(
        git_branch="feature_setup_PROJ-144",
        project="myrepo-worktree-PROJ-200-foo",
    )
    assert topic == "PROJ-144"


def test_per_record_falls_back_to_folder():
    topic = assign_topic_for_record(
        git_branch=None,
        project="myrepo-worktree-PROJ-144-foo",
    )
    assert topic == "PROJ-144"


def test_per_record_unclassified_branch_scoped_when_branch_known():
    """No ticket anywhere but we know the branch -> bucket by branch."""
    topic = assign_topic_for_record(git_branch="main", project="myrepo")
    assert topic == "unclassified:myrepo#main"


def test_per_record_unclassified_no_branch_when_branch_missing():
    topic = assign_topic_for_record(git_branch=None, project="myrepo")
    assert topic == "unclassified:myrepo"


def test_per_record_no_prompt_history_fallback():
    """We dropped the prompt-history fallback: a branch without a ticket
    no longer leaks attribution from prior prompts. It buckets by branch."""
    topic = assign_topic_for_record(
        git_branch="my-feature-branch",
        project="myrepo",
    )
    assert topic == "unclassified:myrepo#my-feature-branch"


def test_infer_session_ticket_returns_most_common():
    assert infer_session_ticket(
        ["fix PROJ-144 webhook", "more on PROJ-144", "also touches TASK-1890"]
    ) == "PROJ-144"


def test_infer_session_ticket_returns_none_when_no_ticket_mentioned():
    assert infer_session_ticket(["look around the codebase", "what does X do"]) is None


def test_infer_session_ticket_returns_none_for_empty_prompts():
    assert infer_session_ticket([]) is None


def test_infer_session_ticket_ties_break_by_first_occurrence():
    """Counter.most_common is stable in insertion order on ties — so the
    first ticket to appear wins when counts are equal."""
    assert infer_session_ticket(["PROJ-65 then TASK-1890"]) == "PROJ-65"
    assert infer_session_ticket(["TASK-1890 then PROJ-65"]) == "TASK-1890"
