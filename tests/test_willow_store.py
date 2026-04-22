"""Tests for willow_store.py — user store partition."""
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_default_store_root_is_user_path(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / ".willow" / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    store = ws.WillowStore()
    assert str(store.root).startswith(str(tmp_path))


def test_store_root_never_inside_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / ".willow" / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    store = ws.WillowStore()
    repo_root = Path(__file__).parent.parent
    assert not str(store.root).startswith(str(repo_root))


def test_store_put_and_get(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    store = ws.WillowStore()
    record = {"_id": "test001", "title": "test", "content": "hello"}
    store.put("test/atoms", record)
    result = store.get("test/atoms", "test001")
    assert result["title"] == "test"


def test_store_list_returns_records(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    store = ws.WillowStore()
    store.put("test/atoms", {"_id": "a1", "title": "alpha"})
    store.put("test/atoms", {"_id": "a2", "title": "beta"})
    results = store.list("test/atoms")
    assert len(results) == 2


def test_store_search_tokenizes_query(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    store = ws.WillowStore()
    store.put("test/atoms", {"_id": "b1", "title": "Yggdrasil root", "content": "Norse tree"})
    store.put("test/atoms", {"_id": "b2", "title": "Mimir well", "content": "wisdom water"})
    results = store.search("test/atoms", "Yggdrasil Norse")
    assert len(results) == 1
    assert results[0]["_id"] == "b1"
