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
