"""Tests for daemon/labeler.py — pure resolver, no cache or thread.

We mock subprocess.run via monkeypatch so no real CLI calls fire.
"""
from __future__ import annotations

import json
import subprocess
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
