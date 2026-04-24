"""Tests for pg_bridge.py — schema correctness."""
import os
import pytest
import psycopg2


def _conn():
    return psycopg2.connect(
        dbname=os.environ.get("WILLOW_PG_DB", "willow_19"),
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
    )


def test_knowledge_table_has_project_column():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='knowledge' AND column_name='project'
    """)
    assert cur.fetchone() is not None, "knowledge table missing 'project' column"
    conn.close()


def test_knowledge_table_has_bitemporal_columns():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='knowledge' AND column_name IN ('valid_at','invalid_at')
    """)
    cols = {row[0] for row in cur.fetchall()}
    assert 'valid_at' in cols
    assert 'invalid_at' in cols
    conn.close()


def test_cmb_atoms_table_exists():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_name='cmb_atoms'
    """)
    assert cur.fetchone() is not None
    conn.close()


def test_frank_ledger_table_exists():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_name='frank_ledger'
    """)
    assert cur.fetchone() is not None
    conn.close()


def test_knowledge_project_defaults_to_global():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_default FROM information_schema.columns
        WHERE table_schema='public' AND table_name='knowledge' AND column_name='project'
    """)
    row = cur.fetchone()
    assert row is not None
    assert 'global' in str(row[0])
    conn.close()


def test_knowledge_weight_columns():
    """knowledge table must have weight columns."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='knowledge'
        AND column_name IN ('visit_count', 'weight', 'last_visited')
    """)
    cols = {r[0] for r in cur.fetchall()}
    conn.close()
    missing = {'visit_count', 'weight', 'last_visited'} - cols
    assert not missing, f"Missing weight columns: {missing}"


def test_routing_decisions_table():
    """routing_decisions table must exist and accept inserts."""
    import uuid, json
    conn = _conn()
    cur = conn.cursor()
    rid = str(uuid.uuid4())[:8]
    cur.execute(
        "INSERT INTO routing_decisions (id, prompt_hash, decision) VALUES (%s, %s, %s)",
        (rid, 'testhash', json.dumps({"route": "test"}))
    )
    conn.commit()
    cur.execute("SELECT id FROM routing_decisions WHERE id = %s", (rid,))
    assert cur.fetchone() is not None
    cur.execute("DELETE FROM routing_decisions WHERE id = %s", (rid,))
    conn.commit()
    conn.close()
