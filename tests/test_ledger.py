"""Tests for W19LG — FRANK's Ledger: verify + read."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pg_bridge import PgBridge


@pytest.fixture
def pg():
    bridge = PgBridge()
    with bridge.conn.cursor() as cur:
        # Truncate the entire ledger — willow_19 is a dedicated test DB.
        # The ledger uses a global hash chain; partial deletes corrupt it.
        cur.execute("TRUNCATE frank_ledger")
    bridge.conn.commit()
    return bridge


def test_ledger_append_returns_id(pg):
    record_id = pg.ledger_append("test_ledger", "decision", {"note": "test entry"})
    assert isinstance(record_id, str)
    assert len(record_id) > 0


def test_ledger_append_creates_hash(pg):
    pg.ledger_append("test_ledger", "decision", {"note": "hashed entry"})
    with pg.conn.cursor() as cur:
        cur.execute(
            "SELECT hash FROM frank_ledger WHERE project='test_ledger' ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None
    assert len(row[0]) == 64  # SHA-256 hex


def test_ledger_read_returns_entries(pg):
    pg.ledger_append("test_ledger", "decision", {"note": "alpha"})
    pg.ledger_append("test_ledger", "decision", {"note": "beta"})
    entries = pg.ledger_read(project="test_ledger")
    assert len(entries) >= 2


def test_ledger_read_filters_by_project(pg):
    pg.ledger_append("test_ledger", "decision", {"note": "in project"})
    pg.ledger_append("other_project_xyz", "decision", {"note": "other"})
    entries = pg.ledger_read(project="test_ledger")
    assert all(e["project"] == "test_ledger" for e in entries)


def test_ledger_verify_valid_chain(pg):
    pg.ledger_append("test_ledger", "decision", {"note": "first"})
    pg.ledger_append("test_ledger", "decision", {"note": "second"})
    result = pg.ledger_verify()
    assert result["valid"] is True
    assert result["count"] >= 2


def test_ledger_verify_returns_count(pg):
    pg.ledger_append("test_ledger", "decision", {"note": "counted"})
    result = pg.ledger_verify()
    assert isinstance(result["count"], int)
    assert result["count"] >= 1


def test_ledger_read_limit_respected(pg):
    for i in range(5):
        pg.ledger_append("test_ledger", "decision", {"note": f"entry {i}"})
    entries = pg.ledger_read(project="test_ledger", limit=3)
    assert len(entries) <= 3
