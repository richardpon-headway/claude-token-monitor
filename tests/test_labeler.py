"""Tests for daemon/labeler.py — pure resolver, cache, and background tick.

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
    assert labeler.is_ticket_topic("PROJ-144")
    assert labeler.is_ticket_topic("TASK-1890")
    assert not labeler.is_ticket_topic("unclassified:myrepo")
    assert not labeler.is_ticket_topic("ABCDEF-1")  # 6 letters > 5
    assert not labeler.is_ticket_topic("proj-123")   # lowercase


def test_fetch_jira_summary_returns_summary_field(monkeypatch):
    payload = {"key": "PROJ-144",
               "fields": {"summary": "example ticket summary"}}
    _patch_run(monkeypatch, FakeProc(stdout=json.dumps(payload)))
    assert labeler.fetch_jira_summary("PROJ-144") == "example ticket summary"


def test_fetch_jira_summary_none_when_acli_missing(monkeypatch):
    _patch_run(monkeypatch, FileNotFoundError)
    assert labeler.fetch_jira_summary("PROJ-144") is None


def test_fetch_jira_summary_none_on_nonzero_exit(monkeypatch):
    _patch_run(monkeypatch, FakeProc(returncode=1, stderr="not authenticated"))
    assert labeler.fetch_jira_summary("PROJ-144") is None


def test_fetch_jira_summary_none_on_bad_json(monkeypatch):
    _patch_run(monkeypatch, FakeProc(stdout="not json at all"))
    assert labeler.fetch_jira_summary("PROJ-144") is None


def test_fetch_jira_summary_none_on_timeout(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv[0], 8.0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert labeler.fetch_jira_summary("PROJ-144") is None


def test_summarize_topic_ticket_uses_jira(monkeypatch):
    payload = {"fields": {"summary": "Webhook rewrite"}}
    runs: list[list[str]] = []
    def fake_run(argv, **kwargs):
        runs.append(argv)
        return FakeProc(stdout=json.dumps(payload))
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = labeler.summarize_topic("PROJ-144")
    assert out == "Webhook rewrite"
    assert all(r[0] == "acli" for r in runs)


def test_summarize_topic_non_ticket_returns_none_without_shelling_out(monkeypatch):
    """Non-ticket topic_id means there's no Jira issue to look up; skip the
    subprocess call entirely."""
    runs: list[list[str]] = []
    def fake_run(argv, **kwargs):
        runs.append(argv)
        raise AssertionError(f"unexpected subprocess call: {argv}")
    monkeypatch.setattr(subprocess, "run", fake_run)
    out = labeler.summarize_topic("unclassified:myrepo")
    assert out is None
    assert runs == []


def test_summarize_topic_returns_none_when_jira_misses(monkeypatch):
    _patch_run(monkeypatch, FakeProc(returncode=1, stderr="no such issue"))
    assert labeler.summarize_topic("GAD-7") is None


# --- cache ----------------------------------------------------------------

def test_cache_round_trip(tmp_path):
    cache = {
        "PROJ-144": labeler.CachedSummary(summary="webhook rewrite", fetched_at=1.0),
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
    p = tmp_path / "cache.json"
    p.write_text(json.dumps({
        "PROJ-144": {"summary": "good", "fetched_at": 5.0},
        "GAD-7": "not a dict",
        "TASK-1890": {"summary": 999, "fetched_at": 5.0},  # summary not str
        "EL-635": {"summary": "ok", "fetched_at": "not a number"},
    }))
    loaded = labeler.load_cache(p)
    assert list(loaded.keys()) == ["PROJ-144"]
    assert loaded["PROJ-144"].summary == "good"


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
    cache = {"PROJ-144": labeler.CachedSummary(summary="x", fetched_at=1.0)}
    p = tmp_path / "cache.json"
    labeler.save_cache(cache, p)
    # No leftover .tmp file
    assert not (tmp_path / "cache.json.tmp").exists()
    # Final file is well-formed
    assert "PROJ-144" in labeler.load_cache(p)


def test_save_cache_creates_parent_dir(tmp_path):
    p = tmp_path / "nested" / "deep" / "cache.json"
    labeler.save_cache({}, p)
    assert p.exists()


# --- Labeler (background thread + tick logic) ----------------------------

class _FakeTopic:
    def __init__(self, topic_id):
        self.topic_id = topic_id


class _FakeRollup:
    def __init__(self, topics):
        self._topics = topics
    def snapshot_topics(self):
        return [_FakeTopic(t) for t in self._topics]


def test_labeler_get_summary_returns_cached_value(tmp_path, monkeypatch):
    rollup = _FakeRollup([])
    monkeypatch.setattr(labeler, "summarize_topic", lambda *a, **kw: None)
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    assert lab.get_summary("missing") is None
    lab._cache["PROJ-144"] = labeler.CachedSummary("hi", time.time())
    assert lab.get_summary("PROJ-144") == "hi"


def test_labeler_tick_processes_pending_skips_fresh(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=["PROJ-144", "PROJ-119"])
    calls: list[str] = []
    monkeypatch.setattr(labeler, "summarize_topic",
                        lambda tid: (calls.append(tid), f"sum:{tid}")[1])
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    # Pre-seed PROJ-144 as fresh — tick should skip it
    lab._cache["PROJ-144"] = labeler.CachedSummary("old", time.time())

    n = lab.tick()
    assert n == 1
    assert calls == ["PROJ-119"]
    assert lab.get_summary("PROJ-144") == "old"
    assert lab.get_summary("PROJ-119") == "sum:PROJ-119"


def test_labeler_tick_skips_non_ticket_topics(tmp_path, monkeypatch):
    """Non-ticket topics (`unclassified:...`) have no Jira to query — the
    tick should skip them entirely instead of burning a no-op call."""
    rollup = _FakeRollup(topics=["unclassified:myrepo", "PROJ-144"])
    calls: list[str] = []
    monkeypatch.setattr(labeler, "summarize_topic",
                        lambda tid: (calls.append(tid), f"sum:{tid}")[1])
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    n = lab.tick()
    assert n == 1
    assert calls == ["PROJ-144"]
    assert lab.get_summary("unclassified:myrepo") is None


def test_labeler_tick_caps_at_max_per_tick(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=[f"PROJ-{i}" for i in range(50)])
    monkeypatch.setattr(labeler, "summarize_topic", lambda tid: f"s:{tid}")
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json", max_per_tick=5)
    n = lab.tick()
    assert n == 5
    assert sum(1 for tid in [f"PROJ-{i}" for i in range(50)]
               if lab.get_summary(tid) is not None) == 5


def test_labeler_tick_persists_cache(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=["PROJ-144"])
    monkeypatch.setattr(labeler, "summarize_topic", lambda tid: "webhook")
    cache_path = tmp_path / "c.json"
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    lab.tick()
    reloaded = labeler.load_cache(cache_path)
    assert reloaded["PROJ-144"].summary == "webhook"


def test_labeler_tick_skips_when_summarize_returns_none(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=["PROJ-144"])
    monkeypatch.setattr(labeler, "summarize_topic", lambda tid: None)
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json")
    n = lab.tick()
    assert n == 0
    assert lab.get_summary("PROJ-144") is None


def test_labeler_tick_resyncs_from_disk_before_processing(tmp_path, monkeypatch):
    """If another process writes a summary to the cache file, the next tick
    should pick it up via disk-reload rather than re-summarize the topic."""
    rollup = _FakeRollup(topics=["PROJ-144"])
    cache_path = tmp_path / "c.json"
    summarize_calls: list[str] = []
    monkeypatch.setattr(
        labeler, "summarize_topic",
        lambda tid: (summarize_calls.append(tid), "from_summarize")[1],
    )
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    labeler.save_cache(
        {"PROJ-144": labeler.CachedSummary(summary="from_disk", fetched_at=time.time())},
        cache_path,
    )
    n = lab.tick()
    assert n == 0
    assert summarize_calls == []
    assert lab.get_summary("PROJ-144") == "from_disk"


def test_labeler_tick_resync_prefers_newer_fetched_at(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=[])
    cache_path = tmp_path / "c.json"
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    lab._cache["PROJ-144"] = labeler.CachedSummary(summary="old_inmem", fetched_at=100.0)
    labeler.save_cache(
        {"PROJ-144": labeler.CachedSummary(summary="new_disk", fetched_at=200.0)},
        cache_path,
    )
    lab.tick()
    assert lab.get_summary("PROJ-144") == "new_disk"


def test_labeler_tick_resync_keeps_newer_inmem_when_disk_is_stale(tmp_path, monkeypatch):
    rollup = _FakeRollup(topics=[])
    cache_path = tmp_path / "c.json"
    lab = labeler.Labeler(rollup, cache_path=cache_path)
    lab._cache["PROJ-144"] = labeler.CachedSummary(summary="new_inmem", fetched_at=200.0)
    labeler.save_cache(
        {"PROJ-144": labeler.CachedSummary(summary="old_disk", fetched_at=100.0)},
        cache_path,
    )
    lab.tick()
    assert lab.get_summary("PROJ-144") == "new_inmem"


def test_labeler_start_stop_lifecycle(tmp_path, monkeypatch):
    rollup = _FakeRollup([])
    monkeypatch.setattr(labeler, "summarize_topic", lambda *a, **kw: None)
    lab = labeler.Labeler(rollup, cache_path=tmp_path / "c.json", interval_sec=0.05)
    lab.start()
    time.sleep(0.15)  # let it run a couple of ticks
    lab.stop()
    assert lab._thread is None
