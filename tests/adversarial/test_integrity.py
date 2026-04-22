# tests/adversarial/test_integrity.py
"""Ledger tamper detection and bi-temporal integrity.

Ledger tests use clean_bridge (truncated frank_ledger) because ledger_verify()
walks the entire chain in created_at order — stale rows from other tests
would produce false chain breaks.
"""
import psycopg2.extras
import pytest
from datetime import datetime, timezone, timedelta


def test_tampered_hash_detected(clean_bridge):
    """Directly tampering a stored hash is caught by ledger_verify."""
    clean_bridge.ledger_append("adv_ledger", "decision", {"note": "first"})
    clean_bridge.ledger_append("adv_ledger", "decision", {"note": "second"})
    with clean_bridge.conn.cursor() as cur:
        cur.execute("""
            UPDATE frank_ledger SET hash = 'deadbeefdeadbeefdeadbeefdeadbeef'
            WHERE id = (
                SELECT id FROM frank_ledger ORDER BY created_at ASC LIMIT 1
            )
        """)
    clean_bridge.conn.commit()
    result = clean_bridge.ledger_verify()
    assert result["valid"] is False
    assert result["broken_at"] is not None


def test_broken_prev_hash_link_detected(clean_bridge):
    """Corrupting prev_hash on any entry breaks the chain verification."""
    clean_bridge.ledger_append("adv_ledger2", "decision", {"note": "alpha"})
    clean_bridge.ledger_append("adv_ledger2", "decision", {"note": "beta"})
    with clean_bridge.conn.cursor() as cur:
        cur.execute("""
            UPDATE frank_ledger SET prev_hash = 'not_the_real_previous_hash'
            WHERE id = (
                SELECT id FROM frank_ledger ORDER BY created_at DESC LIMIT 1
            )
        """)
    clean_bridge.conn.commit()
    result = clean_bridge.ledger_verify()
    assert result["valid"] is False


def test_closed_atom_not_reopened_by_put(bridge):
    """knowledge_close sets invalid_at; a subsequent knowledge_put with the same id
    must NOT reset invalid_at — the atom must stay closed."""
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t_close = datetime(2026, 3, 1, tzinfo=timezone.utc)
    bridge.knowledge_put({
        "id": "adv_int_closed",
        "project": "adv_integrity",
        "title": "will be closed",
        "valid_at": t0,
    })
    bridge.knowledge_close("adv_int_closed", t_close)
    # Re-put the same id without specifying invalid_at
    bridge.knowledge_put({
        "id": "adv_int_closed",
        "project": "adv_integrity",
        "title": "attempt to reopen atom",
    })
    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT invalid_at FROM knowledge WHERE id = 'adv_int_closed'")
        row = cur.fetchone()
    assert row["invalid_at"] is not None, (
        "invalid_at was cleared — knowledge_put reopened a closed atom. "
        "Check ON CONFLICT clause in pg_bridge.knowledge_put."
    )


def test_draugr_category_overwritten_by_conflict_update(bridge):
    """ON CONFLICT updates category — draugr label does not survive a re-put with category=None.
    This is documented behavior: callers must not assume draugr persists after re-put."""
    from core.intelligence import draugr_mark
    bridge.knowledge_put({
        "id": "adv_draugr_conflict",
        "project": "adv_integrity",
        "title": "zombie atom candidate",
        "summary": "old stale content",
    })
    draugr_mark(bridge, ["adv_draugr_conflict"])
    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT category FROM knowledge WHERE id = 'adv_draugr_conflict'")
        assert cur.fetchone()["category"] == "draugr"
    # Re-put without setting category — ON CONFLICT sets category = EXCLUDED.category = None
    bridge.knowledge_put({
        "id": "adv_draugr_conflict",
        "project": "adv_integrity",
        "title": "zombie atom updated",
        "summary": "refreshed content",
    })
    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT category FROM knowledge WHERE id = 'adv_draugr_conflict'")
        row = cur.fetchone()
    assert row["category"] is None, (
        "Expected category=None after re-put. ON CONFLICT should overwrite. "
        "If this fails, the ON CONFLICT clause was changed — update draugr_mark callers accordingly."
    )


def test_knowledge_at_before_close(bridge):
    """Atom queried before its close time must be found."""
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(hours=3)
    t_close = now - timedelta(hours=1)
    bridge.knowledge_put({
        "id": "adv_at_before",
        "project": "adv_integrity",
        "title": "temporal integrity probe before close",
        "valid_at": t0,
    })
    bridge.knowledge_close("adv_at_before", t_close)
    query_at = t_close - timedelta(minutes=30)
    results = bridge.knowledge_at("temporal integrity probe before close", at_time=query_at)
    assert any(r["id"] == "adv_at_before" for r in results), (
        "Atom should be visible before its close time"
    )


def test_knowledge_at_after_close(bridge):
    """Atom queried after its close time must NOT be found."""
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(hours=3)
    t_close = now - timedelta(hours=1)
    bridge.knowledge_put({
        "id": "adv_at_after",
        "project": "adv_integrity",
        "title": "temporal integrity probe after close",
        "valid_at": t0,
    })
    bridge.knowledge_close("adv_at_after", t_close)
    results = bridge.knowledge_at("temporal integrity probe after close", at_time=now)
    assert not any(r["id"] == "adv_at_after" for r in results), (
        "Closed atom appeared after its close time — bi-temporal query has a bug"
    )
