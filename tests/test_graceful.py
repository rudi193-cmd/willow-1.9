"""Tests for W19GD — graceful degradation when Postgres is down."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_degraded_bridge_is_available():
    from core.graceful import DegradedBridge
    assert DegradedBridge is not None


def test_degraded_bridge_knowledge_put_writes_to_store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    from core.graceful import DegradedBridge
    store = ws.WillowStore()
    bridge = DegradedBridge(store)
    bridge.knowledge_put({"id": "gd_test_1", "title": "fallback atom", "project": "test"})
    results = store.search("knowledge/fallback", "fallback")
    assert len(results) == 1
    assert results[0]["id"] == "gd_test_1"


def test_degraded_bridge_knowledge_search_reads_from_store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    from core.graceful import DegradedBridge
    store = ws.WillowStore()
    bridge = DegradedBridge(store)
    bridge.knowledge_put({"id": "gd_test_2", "title": "Norse wisdom", "project": "test"})
    results = bridge.knowledge_search("Norse")
    assert len(results) == 1


def test_degraded_bridge_knowledge_close_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    from core.graceful import DegradedBridge
    from datetime import datetime, timezone
    store = ws.WillowStore()
    bridge = DegradedBridge(store)
    bridge.knowledge_close("nonexistent", datetime.now(timezone.utc))  # must not raise


def test_degraded_bridge_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    from core.graceful import DegradedBridge
    store = ws.WillowStore()
    bridge = DegradedBridge(store)
    assert bridge.degraded is True


def test_get_bridge_returns_degraded_when_pg_down():
    from core.graceful import get_bridge
    bridge = get_bridge(pg_dsn="dbname=nonexistent_db_xyz user=nobody")
    assert bridge.degraded is True


def test_get_bridge_returns_pg_when_available():
    from core.graceful import get_bridge
    import os
    db = os.environ.get("WILLOW_PG_DB", "willow_19_test")
    user = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", ""))
    host = os.environ.get("WILLOW_PG_HOST", "")
    port = os.environ.get("WILLOW_PG_PORT", "")
    dsn = f"dbname={db} user={user}"
    if host:
        dsn += f" host={host}"
    if port:
        dsn += f" port={port}"
    bridge = get_bridge(pg_dsn=dsn)
    assert bridge.degraded is False
