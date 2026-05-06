"""Tests for daemon/labeler.py — pure resolver, no cache or thread.

We mock subprocess.run via monkeypatch so no real CLI calls fire.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import pytest

from daemon import labeler


@dataclass
class FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _patch_run(monkeypatch: pytest.MonkeyPatch, behavior: dict | Any):
    """Install a subprocess.run double. behavior may be a FakeProc, an
    Exception class to raise, or a dict mapping argv[0] -> FakeProc/Exception."""
    def fake_run(argv, **kwargs):
        chosen = behavior
        if isinstance(behavior, dict):
            chosen = behavior.get(argv[0])
            if chosen is None:
                raise FileNotFoundError(argv[0])
        if isinstance(chosen, type) and issubclass(chosen, BaseException):
            raise chosen(argv[0])
        return chosen
    monkeypatch.setattr(subprocess, "run", fake_run)


def test_is_ticket_topic():
    assert labeler.is_ticket_topic("COR-144")
    assert labeler.is_ticket_topic("DT-1890")
    assert not labeler.is_ticket_topic("unclassified:headway")
    assert not labeler.is_ticket_topic("ABCDEF-1")  # 6 letters > 5
    assert not labeler.is_ticket_topic("cor-144")   # lowercase


def test_fetch_jira_summary_returns_summary_field(monkeypatch):
    payload = {"key": "COR-144",
               "fields": {"summary": "IA call webhook source of truth"}}
    _patch_run(monkeypatch, FakeProc(stdout=json.dumps(payload)))
    assert labeler.fetch_jira_summary("COR-144") == "IA call webhook source of truth"


def test_fetch_jira_summary_none_when_acli_missing(monkeypatch):
    _patch_run(monkeypatch, FileNotFoundError)
    assert labeler.fetch_jira_summary("COR-144") is None


def test_fetch_jira_summary_none_on_nonzero_exit(monkeypatch):
    _patch_run(monkeypatch, FakeProc(returncode=1, stderr="not authenticated"))
    assert labeler.fetch_jira_summary("COR-144") is None


def test_fetch_jira_summary_none_on_bad_json(monkeypatch):
    _patch_run(monkeypatch, FakeProc(stdout="not json at all"))
    assert labeler.fetch_jira_summary("COR-144") is None


def test_fetch_jira_summary_none_on_timeout(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv[0], 8.0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert labeler.fetch_jira_summary("COR-144") is None


def test_fetch_claude_summary_strips_output(monkeypatch):
    _patch_run(monkeypatch, FakeProc(stdout="  cleaning up the parser  \n\n"))
    out = labeler.fetch_claude_summary("unclassified:foo", ["hello", "fix the parser"])
    assert out == "cleaning up the parser"


def test_fetch_claude_summary_none_when_no_prompts(monkeypatch):
    """No prompts to feed → no LLM call; return None without spending tokens."""
    called: list = []
    def fake_run(argv, **kwargs):
        called.append(argv)
        return FakeProc(stdout="should never be used")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert labeler.fetch_claude_summary("topic", []) is None
    assert called == []  # never called


def test_fetch_claude_summary_none_on_missing_cli(monkeypatch):
    _patch_run(monkeypatch, FileNotFoundError)
    assert labeler.fetch_claude_summary("topic", ["something"]) is None


def test_summarize_topic_ticket_uses_jira(monkeypatch):
    payload = {"fields": {"summary": "Webhook rewrite"}}
    runs: list[list[str]] = []
    def fake_run(argv, **kwargs):
        runs.append(argv)
        if argv[0] == "acli":
            return FakeProc(stdout=json.dumps(payload))
        return FakeProc(stdout="claude was called incorrectly")
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = labeler.summarize_topic("COR-144", ["any prompt"])
    assert out == "Webhook rewrite"
    # Only acli should have been called — claude is the fallback.
    assert all(r[0] == "acli" for r in runs)


def test_summarize_topic_falls_back_to_claude_when_jira_misses(monkeypatch):
    runs: list[list[str]] = []
    def fake_run(argv, **kwargs):
        runs.append(argv)
        if argv[0] == "acli":
            return FakeProc(returncode=1, stderr="no such issue")  # Jira miss
        if argv[0] == "claude":
            return FakeProc(stdout="something about a clinical scale")
        raise FileNotFoundError(argv[0])
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = labeler.summarize_topic("GAD-7", ["talking about anxiety scales"])
    assert out == "something about a clinical scale"
    assert [r[0] for r in runs] == ["acli", "claude"]


def test_summarize_topic_non_ticket_skips_acli(monkeypatch):
    """Non-ticket topic_id should jump straight to claude — don't waste a
    subprocess call on a Jira ticket that obviously can't exist."""
    runs: list[list[str]] = []
    def fake_run(argv, **kwargs):
        runs.append(argv)
        if argv[0] == "claude":
            return FakeProc(stdout="exploration in the headway repo")
        raise AssertionError(f"unexpected argv[0]={argv[0]}")
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = labeler.summarize_topic("unclassified:headway", ["look around"])
    assert out == "exploration in the headway repo"
    assert [r[0] for r in runs] == ["claude"]


# --- cache ----------------------------------------------------------------

def test_cache_round_trip(tmp_path):
    cache = {
        "COR-144": labeler.CachedSummary(summary="webhook rewrite", fetched_at=1.0),
        "GAD-7": labeler.CachedSummary(summary="anxiety scale", fetched_at=2.0),
    }
    p = tmp_path / "cache.json"
    labeler.save_cache(cache, p)
    loaded = labeler.load_cache(p)
    assert loaded == cache


def test_cache_load_missing_file_returns_empty(tmp_path):
    assert labeler.load_cache(tmp_path / "nope.json") == {}


def test_cache_load_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text("{ this is not json")
    assert labeler.load_cache(p) == {}


def test_cache_load_skips_malformed_entries(tmp_path):
    """One bad entry shouldn't poison the rest — drop it and keep going."""
    import json
    p = tmp_path / "cache.json"
    p.write_text(json.dumps({
        "COR-144": {"summary": "good", "fetched_at": 5.0},
        "GAD-7": "not a dict",
        "DT-1890": {"summary": 999, "fetched_at": 5.0},  # summary not str
        "EL-635": {"summary": "ok", "fetched_at": "not a number"},
    }))
    loaded = labeler.load_cache(p)
    assert list(loaded.keys()) == ["COR-144"]
    assert loaded["COR-144"].summary == "good"


def test_is_fresh_within_ttl():
    cached = labeler.CachedSummary(summary="x", fetched_at=1000.0)
    # 6 days later — still fresh
    assert labeler.is_fresh(cached, now=1000.0 + 6 * 86400) is True


def test_is_fresh_past_ttl():
    cached = labeler.CachedSummary(summary="x", fetched_at=1000.0)
    # 8 days later — stale
    assert labeler.is_fresh(cached, now=1000.0 + 8 * 86400) is False


def test_save_cache_writes_atomically(tmp_path):
    """save_cache should write to a tempfile then rename, not leave a
    partial file on the destination path."""
    cache = {"COR-144": labeler.CachedSummary(summary="x", fetched_at=1.0)}
    p = tmp_path / "cache.json"
    labeler.save_cache(cache, p)
    # No leftover .tmp file
    assert not (tmp_path / "cache.json.tmp").exists()
    # Final file is well-formed
    assert "COR-144" in labeler.load_cache(p)


def test_save_cache_creates_parent_dir(tmp_path):
    p = tmp_path / "nested" / "deep" / "cache.json"
    labeler.save_cache({}, p)
    assert p.exists()


# --- Labeler (background thread + tick logic) ----------------------------

class _FakeTopic:
    def __init__(self, topic_id):
        self.topic_id = topic_id


class _FakeSession:
    def __init__(
        self, segments, early_user_prompts,
        *, session_id="fake", topic_id=None, last_at=None, output=0,
    ):
        self.segments = segments
        self.early_user_prompts = early_user_prompts
        self.session_id = session_id
        # Default the dominant topic to the first segment key so existing
        # tests that don't set this work transparently.
        self.topic_id = topic_id or (next(iter(segments), None) if segments else None)
        self.last_at = last_at
        self.output = output


class _FakeRollup:
    def __init__(self, topics, sessions):
        self._topics = topics
        self._sessions = sessions
    def snapshot_topics(self):
        return [_FakeTopic(t) for t in self._topics]
    def snapshot_sessions(self):
        return list(self._sessions)


def test_labeler_get_summary_returns_cached_value(tmp_path, monkeypatch):
    rollup = _FakeRollup([], [])
    monkeypatch.setattr(labeler, "summarize_topic", lambda *a, **kw: None)
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    assert lab.get_summary("missing") is None
    # Inject a cached entry directly
    lab._cache["COR-144"] = labeler.CachedSummary("hi", time.time())
    assert lab.get_summary("COR-144") == "hi"


def test_labeler_tick_processes_pending_skips_fresh(tmp_path, monkeypatch):
    rollup = _FakeRollup(
        topics=["COR-144", "COR-119"],
        sessions=[_FakeSession({"COR-144": object(), "COR-119": object()},
                                ["fix the webhook"])],
    )
    calls: list[str] = []
    monkeypatch.setattr(labeler, "summarize_topic",
                        lambda tid, prompts: (calls.append(tid), f"sum:{tid}")[1])
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    # Pre-seed COR-144 as fresh — tick should skip it
    lab._cache["COR-144"] = labeler.CachedSummary("old", time.time())

    n = lab.tick()
    assert n == 1
    assert calls == ["COR-119"]
    assert lab.get_summary("COR-144") == "old"
    assert lab.get_summary("COR-119") == "sum:COR-119"


def test_labeler_tick_caps_at_max_per_tick(tmp_path, monkeypatch):
    rollup = _FakeRollup(
        topics=[f"COR-{i}" for i in range(50)],
        sessions=[_FakeSession({f"COR-{i}": object() for i in range(50)}, ["x"])],
    )
    monkeypatch.setattr(labeler, "summarize_topic", lambda tid, prompts: f"s:{tid}")
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json", max_per_tick=5)
    n = lab.tick()
    assert n == 5
    assert sum(1 for tid in [f"COR-{i}" for i in range(50)]
               if lab.get_summary(tid) is not None) == 5


def test_labeler_tick_persists_cache(tmp_path, monkeypatch):
    rollup = _FakeRollup(
        topics=["COR-144"],
        sessions=[_FakeSession({"COR-144": object()}, ["fix the webhook"])],
    )
    monkeypatch.setattr(labeler, "summarize_topic", lambda tid, prompts: "webhook")
    cache_path = tmp_path / "c.json"
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    lab.tick()
    # Reload cache from disk to verify it was written
    reloaded = labeler.load_cache(cache_path)
    assert reloaded["COR-144"].summary == "webhook"


def test_labeler_tick_skips_when_summarize_returns_none(tmp_path, monkeypatch):
    rollup = _FakeRollup(
        topics=["COR-144"],
        sessions=[_FakeSession({"COR-144": object()}, ["x"])],
    )
    monkeypatch.setattr(labeler, "summarize_topic", lambda tid, prompts: None)
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    n = lab.tick()
    assert n == 0
    assert lab.get_summary("COR-144") is None  # nothing cached


def test_labeler_collect_prompts_only_sessions_in_topic(tmp_path, monkeypatch):
    sessions = [
        _FakeSession({"COR-144": object()}, ["A1", "A2"]),
        _FakeSession({"COR-119": object()}, ["B1"]),         # different topic
        _FakeSession({"COR-144": object()}, ["C1"]),
    ]
    rollup = _FakeRollup(["COR-144", "COR-119"], sessions)
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    out = lab._collect_prompts("COR-144", sessions)
    assert "A1" in out and "A2" in out and "C1" in out
    assert "B1" not in out


def test_labeler_tick_resyncs_from_disk_before_processing(tmp_path, monkeypatch):
    """If another process writes a summary to the cache file, the next tick
    should pick it up via disk-reload rather than re-summarize the topic."""
    rollup = _FakeRollup(
        topics=["COR-144"],
        sessions=[_FakeSession({"COR-144": object()}, ["x"])],
    )
    cache_path = tmp_path / "c.json"
    summarize_calls: list[str] = []
    monkeypatch.setattr(
        labeler, "summarize_topic",
        lambda tid, prompts: (summarize_calls.append(tid), "from_summarize")[1],
    )
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    # Externally write a cached summary (simulating another daemon process).
    labeler.save_cache(
        {"COR-144": labeler.CachedSummary(summary="from_disk", fetched_at=time.time())},
        cache_path,
    )
    n = lab.tick()
    # No new summarize_topic call — entry already on disk and fresh.
    assert n == 0
    assert summarize_calls == []
    assert lab.get_summary("COR-144") == "from_disk"


def test_labeler_tick_resync_prefers_newer_fetched_at(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=[], sessions=[])
    cache_path = tmp_path / "c.json"
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    # Older value in memory
    lab._cache["COR-144"] = labeler.CachedSummary(summary="old_inmem", fetched_at=100.0)
    # Newer value externally written to disk
    labeler.save_cache(
        {"COR-144": labeler.CachedSummary(summary="new_disk", fetched_at=200.0)},
        cache_path,
    )
    lab.tick()
    assert lab.get_summary("COR-144") == "new_disk"


def test_labeler_tick_resync_keeps_newer_inmem_when_disk_is_stale(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=[], sessions=[])
    cache_path = tmp_path / "c.json"
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    # Newer value in memory (e.g. just labeled)
    lab._cache["COR-144"] = labeler.CachedSummary(summary="new_inmem", fetched_at=200.0)
    # Older value on disk
    labeler.save_cache(
        {"COR-144": labeler.CachedSummary(summary="old_disk", fetched_at=100.0)},
        cache_path,
    )
    lab.tick()
    assert lab.get_summary("COR-144") == "new_inmem"


# --- classify_session -----------------------------------------------------

def _classify_run(stdout: str):
    """Helper: returns a fake_run that always returns the given stdout."""
    def fake_run(argv, **kwargs):
        return FakeProc(stdout=stdout)
    return fake_run


def test_classify_session_parses_json_and_returns_ticket(monkeypatch):
    fake_resp = '{"ticket": "COR-144", "summary": "webhook rewrite", "confidence": 0.9}'
    monkeypatch.setattr(subprocess, "run", _classify_run(fake_resp))
    result = labeler.classify_session(
        session_id="s1",
        prompts_sample=["fix the webhook handler"],
        candidate_tickets=[("COR-144", "IA call webhook")],
    )
    assert result is not None
    assert result.ticket == "COR-144"
    assert result.summary == "webhook rewrite"
    assert result.confidence == 0.9


def test_classify_session_drops_ticket_below_confidence_threshold(monkeypatch):
    fake_resp = '{"ticket": "COR-144", "summary": "maybe webhook", "confidence": 0.5}'
    monkeypatch.setattr(subprocess, "run", _classify_run(fake_resp))
    result = labeler.classify_session(
        session_id="s1",
        prompts_sample=["something vague"],
        candidate_tickets=[("COR-144", None)],
    )
    assert result is not None
    # confidence < default 0.8 -> ticket is dropped, summary kept
    assert result.ticket is None
    assert result.summary == "maybe webhook"
    assert result.confidence == 0.5


def test_classify_session_handles_null_ticket(monkeypatch):
    fake_resp = '{"ticket": null, "summary": "exploring atlas auth", "confidence": 0.95}'
    monkeypatch.setattr(subprocess, "run", _classify_run(fake_resp))
    result = labeler.classify_session(
        session_id="s1",
        prompts_sample=["how does atlas auth work"],
        candidate_tickets=[("COR-144", None)],
    )
    assert result is not None
    assert result.ticket is None
    assert result.summary == "exploring atlas auth"


def test_classify_session_extracts_json_from_messy_output(monkeypatch):
    """LLM might wrap JSON in markdown fences or add prose. Pick out the
    first {...} block."""
    messy = (
        "Sure, here's the classification:\n"
        '```json\n{"ticket": "COR-144", "summary": "the webhook", "confidence": 0.85}\n```'
    )
    monkeypatch.setattr(subprocess, "run", _classify_run(messy))
    result = labeler.classify_session(
        session_id="s1",
        prompts_sample=["webhook stuff"],
        candidate_tickets=[("COR-144", None)],
    )
    assert result is not None
    assert result.ticket == "COR-144"


def test_classify_session_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _classify_run("not json at all"))
    assert labeler.classify_session(
        session_id="s1",
        prompts_sample=["x"],
        candidate_tickets=[],
    ) is None


def test_classify_session_returns_none_on_empty_prompts(monkeypatch):
    """No prompts -> no LLM call (saves tokens)."""
    called: list = []
    def fake_run(argv, **kwargs):
        called.append(argv)
        return FakeProc(stdout="should never be used")
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = labeler.classify_session(
        session_id="s1",
        prompts_sample=[],
        candidate_tickets=[("COR-144", None)],
    )
    assert result is None
    assert called == []


def test_classify_session_returns_none_on_subprocess_failure(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("claude")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert labeler.classify_session(
        session_id="s1",
        prompts_sample=["x"],
        candidate_tickets=[],
    ) is None


def test_classify_session_records_output_at_classification(monkeypatch):
    """output_at_classification is the session's total output at call
    time — used by the rollup's B refresh policy (re-classify when
    output >= 2x last classified value)."""
    fake_resp = '{"ticket": null, "summary": "x", "confidence": 0.9}'
    monkeypatch.setattr(subprocess, "run", _classify_run(fake_resp))
    result = labeler.classify_session(
        session_id="s1",
        prompts_sample=["x"],
        candidate_tickets=[],
        output_at_classification=12345,
    )
    assert result is not None
    assert result.output_at_classification == 12345


def test_tick_classifications_includes_tickets_from_prompts(tmp_path, monkeypatch):
    """Tickets mentioned in user prompts must enter the candidate list,
    even when the rollup never surfaced them as a topic. Otherwise sessions
    in unclassified worktrees that explicitly reference a ticket can't
    be re-attributed."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)

    sessions = [
        # An unclassified session in the window that references COR-65
        # in its prompts. The rollup has never seen COR-65 as a topic.
        _FakeSession(
            segments={"unclassified:headway": object()},
            early_user_prompts=["fix the COR-65 currency scroll bug"],
            session_id="needs-classifying",
            topic_id="unclassified:headway",
            last_at=now,
            output=1000,
        ),
        # Another session whose prompts mention DT-1890 — should also
        # land in the candidate list.
        _FakeSession(
            segments={"DT-1890": object()},
            early_user_prompts=["DT-1890 deploy overhead"],
            session_id="dt-session",
            topic_id="DT-1890",
            last_at=now,
            output=500,
        ),
    ]
    rollup = _FakeRollup(topics=["DT-1890"], sessions=sessions)

    seen_candidates: list[list[tuple[str, str | None]]] = []

    def fake_classify(session_id, prompts_sample, candidate_tickets, **kwargs):
        seen_candidates.append(list(candidate_tickets))
        return labeler.SessionClassification(
            ticket="COR-65", summary="currency bug", confidence=0.9,
            output_at_classification=kwargs.get("output_at_classification", 0),
        )

    monkeypatch.setattr(labeler, "classify_session", fake_classify)
    monkeypatch.setattr(labeler, "summarize_topic", lambda *a, **kw: None)

    lab = labeler.Labeler(
        rollup,
        cache_path=tmp_path / "c.json",
        classification_cache_path=tmp_path / "cc.json",
    )
    lab.tick()

    assert len(seen_candidates) == 1
    candidate_ids = {tid for tid, _ in seen_candidates[0]}
    # DT-1890 came in via topic snapshot; COR-65 came in via prompt text.
    assert "DT-1890" in candidate_ids
    assert "COR-65" in candidate_ids


def test_labeler_start_stop_lifecycle(tmp_path, monkeypatch):
    rollup = _FakeRollup([], [])
    monkeypatch.setattr(labeler, "summarize_topic", lambda *a, **kw: None)
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json", interval_sec=0.05)
    lab.start()
    time.sleep(0.15)  # let it run a couple of ticks
    lab.stop()
    assert lab._thread is None
