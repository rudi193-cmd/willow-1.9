#!/usr/bin/env python3
"""
graceful.py — W19GD: Graceful degradation when Postgres is unavailable.
b17: GRD19  ΔΣ=42

DegradedBridge is a drop-in for PgBridge that routes to SOIL (SQLite).
Use get_bridge() instead of PgBridge() directly wherever degradation matters.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class DegradedBridge:
    """Drop-in for PgBridge when Postgres is unavailable. Routes to SOIL."""

    degraded = True

    def __init__(self, store=None):
        if store is None:
            from core.willow_store import WillowStore
            store = WillowStore()
        self._store = store

    def knowledge_put(self, record: dict) -> str:
        record_id = record.get("id") or record.get("_id")
        if not record_id:
            raise ValueError("record must have an id field")
        record["_id"] = record_id
        self._store.put("knowledge/fallback", record)
        return record_id

    def knowledge_search(self, query: str, project: Optional[str] = None,
                         include_invalid: bool = False, limit: int = 20) -> list:
        results = self._store.search("knowledge/fallback", query)
        if project:
            results = [r for r in results if r.get("project") == project]
        return results[:limit]

    def knowledge_close(self, old_id: str, new_valid_at: datetime) -> None:
        pass  # no bi-temporal in degraded mode

    def cmb_put(self, atom_id: str, content: dict) -> None:
        pass  # CMB requires Postgres

    def ledger_append(self, project: str, event_type: str, content: dict) -> str:
        import warnings
        warnings.warn(
            "ledger_append called in degraded mode — audit event silently dropped",
            RuntimeWarning, stacklevel=2,
        )
        return ""  # ledger requires Postgres — caller should check bridge.degraded

    def ledger_verify(self) -> dict:
        return {"valid": False, "degraded": True, "count": 0}

    def ledger_read(self, project: Optional[str] = None, limit: int = 50) -> list:
        return []


class _LiveBridge:
    """Thin wrapper marking a real PgBridge as not-degraded."""
    degraded = False

    def __init__(self, pg_bridge):
        self._pg = pg_bridge

    def __getattr__(self, name):
        return getattr(self._pg, name)


_pg_bridge_mod = None  # cached to avoid re-executing module on every get_bridge() call


def _load_pg_bridge_mod():
    global _pg_bridge_mod
    if _pg_bridge_mod is not None:
        return _pg_bridge_mod
    import importlib.util
    willow_root = Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location(
        "pg_bridge_19", willow_root / "core" / "pg_bridge.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _pg_bridge_mod = mod
    return mod


def get_bridge(pg_dsn: Optional[str] = None):
    """
    Return a live PgBridge (degraded=False) or DegradedBridge (degraded=True).
    Call this instead of PgBridge() directly wherever degradation matters.
    The pg_bridge module is cached after first successful load.
    """
    try:
        mod = _load_pg_bridge_mod()
    except Exception:
        return DegradedBridge()

    try:
        if pg_dsn:
            import psycopg2
            conn = psycopg2.connect(pg_dsn)
            bridge = mod.PgBridge.__new__(mod.PgBridge)
            bridge.conn = conn
            mod.init_schema(conn)
            return _LiveBridge(bridge)
        else:
            return _LiveBridge(mod.PgBridge())
    except Exception:
        return DegradedBridge()
