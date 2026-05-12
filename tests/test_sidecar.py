"""Tests for the CDH session-meta sidecar reader in daemon.routes."""
from __future__ import annotations

import json
import os
import pathlib
import time
from unittest.mock import patch

import pytest

from daemon import routes


@pytest.fixture
def sidecar_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    d = tmp_path / "session-meta"
    d.mkdir()
    monkeypatch.setattr(routes, "SIDECAR_DIR", d)
    routes._sidecar_cache.clear()
    yield d
    routes._sidecar_cache.clear()


def test_returns_none_when_file_missing(sidecar_dir: pathlib.Path):
    assert routes.read_session_sidecar("nope") is None


def test_returns_parsed_dict_when_valid(sidecar_dir: pathlib.Path):
    payload = {
        "session_id": "abc",
        "started_via": "cdh",
        "ticket": "COR-144",
        "worktree": "headway_cor-144",
    }
    (sidecar_dir / "abc.json").write_text(json.dumps(payload))
    assert routes.read_session_sidecar("abc") == payload


def test_returns_none_when_json_malformed(sidecar_dir: pathlib.Path):
    (sidecar_dir / "abc.json").write_text("{not valid json")
    assert routes.read_session_sidecar("abc") is None


def test_returns_none_when_root_is_not_an_object(sidecar_dir: pathlib.Path):
    # JSON is parseable but not the expected shape — treat as no sidecar.
    (sidecar_dir / "abc.json").write_text('["just", "a", "list"]')
    assert routes.read_session_sidecar("abc") is None


def test_mtime_cache_skips_reparse_when_unchanged(sidecar_dir: pathlib.Path):
    payload = {"ticket": "COR-144"}
    (sidecar_dir / "abc.json").write_text(json.dumps(payload))
    assert routes.read_session_sidecar("abc") == payload
    # Second call with unchanged mtime must hit the cache, not json.loads.
    with patch("daemon.routes.json.loads") as spy:
        assert routes.read_session_sidecar("abc") == payload
        spy.assert_not_called()


def test_mtime_cache_invalidates_when_file_rewritten(sidecar_dir: pathlib.Path):
    path = sidecar_dir / "abc.json"
    path.write_text(json.dumps({"ticket": "COR-144"}))
    assert routes.read_session_sidecar("abc") == {"ticket": "COR-144"}
    # Bump mtime explicitly so the test isn't flaky on coarse filesystem
    # timestamp resolution.
    later = time.time() + 10
    path.write_text(json.dumps({"ticket": "DT-1890"}))
    os.utime(path, (later, later))
    assert routes.read_session_sidecar("abc") == {"ticket": "DT-1890"}


def test_cache_invalidates_when_file_deleted(sidecar_dir: pathlib.Path):
    path = sidecar_dir / "abc.json"
    path.write_text(json.dumps({"ticket": "COR-144"}))
    assert routes.read_session_sidecar("abc") == {"ticket": "COR-144"}
    path.unlink()
    assert routes.read_session_sidecar("abc") is None
    assert "abc" not in routes._sidecar_cache
