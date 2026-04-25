#!/usr/bin/env python3
"""
bridge_factory.py — Return the right bridge for this environment. b17: BFCT1 ΔΣ=42

    WILLOW_BACKEND=sqlite   → SqliteBridge (~/.willow/willow.db)
    WILLOW_BACKEND=postgres → PgBridge (willow_19)
    unset                   → PgBridge, auto-fall-back to SqliteBridge if Postgres unreachable

Usage:
    from core.bridge_factory import get_bridge
    bridge = get_bridge()
"""
import os
import sys

_BACKEND = os.environ.get("WILLOW_BACKEND", "auto").lower()


def get_bridge():
    """Return a PgBridge or SqliteBridge depending on WILLOW_BACKEND and availability."""
    if _BACKEND == "sqlite":
        from core.sqlite_bridge import SqliteBridge
        return SqliteBridge()

    if _BACKEND == "postgres":
        from core.pg_bridge import PgBridge
        return PgBridge()

    # auto — try Postgres, fall back to SQLite
    try:
        from core.pg_bridge import try_connect, PgBridge
        conn = try_connect()
        if conn:
            conn.close()
            return PgBridge()
    except Exception:
        pass

    print("[bridge_factory] Postgres unavailable — using SQLite", file=sys.stderr)
    from core.sqlite_bridge import SqliteBridge
    return SqliteBridge()


def backend_name() -> str:
    bridge = get_bridge()
    name = type(bridge).__name__
    try:
        bridge.close()
    except Exception:
        pass
    return name
