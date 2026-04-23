"""Tests for willow/nuke.py — forensic delete."""
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_nuke(store_root: Path, willow_dir: Path):
    """Reload nuke module with controlled paths."""
    import os
    os.environ["WILLOW_STORE_ROOT"] = str(store_root)
    if "willow.nuke" in sys.modules:
        del sys.modules["willow.nuke"]
    import willow.nuke as nuke
    # Override module-level constants to point at tmp dirs
    nuke.STORE_ROOT = store_root
    nuke.WILLOW_DIR = willow_dir
    nuke.LOGS_DIR = willow_dir / "logs"
    nuke._TMP_PATTERNS = [
        str(willow_dir / "session_anchor.json"),
        str(willow_dir / "anchor_state.json"),
    ]
    return nuke


# ---------------------------------------------------------------------------
# NukeResult dataclass
# ---------------------------------------------------------------------------

def test_nuke_result_success_when_no_errors():
    from willow.nuke import NukeResult
    r = NukeResult(timestamp="2026-01-01T00:00:00+00:00")
    assert r.success is True


def test_nuke_result_failure_when_errors():
    from willow.nuke import NukeResult
    r = NukeResult(timestamp="2026-01-01T00:00:00+00:00", errors=["pg connect: refused"])
    assert r.success is False


def test_nuke_result_defaults():
    from willow.nuke import NukeResult
    r = NukeResult(timestamp="t")
    assert r.store_files_deleted == 0
    assert r.store_bytes_freed == 0
    assert r.pg_tables_truncated == []
    assert r.tmp_files_removed == 0
    assert r.receipt_path is None


# ---------------------------------------------------------------------------
# Dry run — nothing deleted, receipt written
# ---------------------------------------------------------------------------

def test_dry_run_deletes_nothing(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()

    # Plant some DB files — should NOT be deleted
    (store_root / "test.db").write_text("data")
    (store_root / "sub").mkdir()
    (store_root / "sub" / "other.db").write_text("data2")

    # Plant tmp files — should NOT be deleted
    willow_dir.mkdir()
    anchor = willow_dir / "session_anchor.json"
    anchor.write_text("{}")

    nuke = _reload_nuke(store_root, willow_dir)

    with patch.object(nuke, "_truncate_pg_tables", return_value=([], [])):
        result = nuke.execute(dry_run=True)

    # Files still exist
    assert (store_root / "test.db").exists()
    assert (store_root / "sub" / "other.db").exists()
    assert anchor.exists()

    # Counts report what WOULD be deleted — consistent with store_files_deleted
    assert result.store_files_deleted == 2
    assert result.tmp_files_removed == 1  # anchor exists, counted but not deleted
    assert result.success is True


def test_dry_run_writes_DRY_receipt(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()
    willow_dir.mkdir()

    nuke = _reload_nuke(store_root, willow_dir)

    with patch.object(nuke, "_truncate_pg_tables", return_value=([], [])):
        result = nuke.execute(dry_run=True)

    assert result.receipt_path is not None
    receipt_file = Path(result.receipt_path)
    assert receipt_file.exists()
    assert "DRY" in receipt_file.name

    data = json.loads(receipt_file.read_text())
    assert data["dry_run"] is True


# ---------------------------------------------------------------------------
# Live run — files deleted, receipt written
# ---------------------------------------------------------------------------

def test_live_run_deletes_store_files(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()
    willow_dir.mkdir()

    (store_root / "alpha.db").write_text("x" * 100)
    (store_root / "beta.db").write_text("y" * 200)

    nuke = _reload_nuke(store_root, willow_dir)

    with patch.object(nuke, "_truncate_pg_tables", return_value=(["compact_contexts"], [])):
        result = nuke.execute(dry_run=False)

    assert not (store_root / "alpha.db").exists()
    assert not (store_root / "beta.db").exists()
    assert result.store_files_deleted == 2
    assert result.store_bytes_freed == 300
    assert result.success is True


def test_live_run_deletes_tmp_files(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()
    willow_dir.mkdir()

    anchor = willow_dir / "session_anchor.json"
    anchor_state = willow_dir / "anchor_state.json"
    anchor.write_text("{}")
    anchor_state.write_text('{"prompt_count": 1}')

    nuke = _reload_nuke(store_root, willow_dir)

    with patch.object(nuke, "_truncate_pg_tables", return_value=([], [])):
        result = nuke.execute(dry_run=False)

    assert not anchor.exists()
    assert not anchor_state.exists()
    assert result.tmp_files_removed == 2


def test_live_run_writes_NUKE_receipt(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()
    willow_dir.mkdir()

    nuke = _reload_nuke(store_root, willow_dir)

    with patch.object(nuke, "_truncate_pg_tables", return_value=([], [])):
        result = nuke.execute(dry_run=False)

    assert result.receipt_path is not None
    receipt_file = Path(result.receipt_path)
    assert receipt_file.exists()
    assert "NUKE" in receipt_file.name

    data = json.loads(receipt_file.read_text())
    assert data["dry_run"] is False


def test_live_run_missing_store_root_is_not_error(tmp_path):
    store_root = tmp_path / "store_does_not_exist"
    willow_dir = tmp_path / "willow"
    willow_dir.mkdir()

    nuke = _reload_nuke(store_root, willow_dir)

    with patch.object(nuke, "_truncate_pg_tables", return_value=([], [])):
        result = nuke.execute(dry_run=False)

    assert result.store_files_deleted == 0
    assert result.success is True


# ---------------------------------------------------------------------------
# Postgres truncation — isolated with mocked connection
# ---------------------------------------------------------------------------

def test_truncate_pg_tables_returns_truncated_list(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()
    willow_dir.mkdir()

    nuke = _reload_nuke(store_root, willow_dir)

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    mock_pg = MagicMock()
    mock_pg.conn = mock_conn

    with patch("core.pg_bridge.PgBridge", return_value=mock_pg):
        truncated, errors = nuke._truncate_pg_tables()

    assert len(errors) == 0
    assert len(truncated) == len(nuke._PG_NUKE_TABLES)


def test_truncate_pg_tables_handles_pg_connect_failure(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()
    willow_dir.mkdir()

    nuke = _reload_nuke(store_root, willow_dir)

    with patch("core.pg_bridge.PgBridge", side_effect=Exception("connection refused")):
        truncated, errors = nuke._truncate_pg_tables()

    assert truncated == []
    assert any("pg connect" in e for e in errors)


# ---------------------------------------------------------------------------
# Receipt contents
# ---------------------------------------------------------------------------

def test_receipt_contains_expected_fields(tmp_path):
    store_root = tmp_path / "store"
    willow_dir = tmp_path / "willow"
    store_root.mkdir()
    willow_dir.mkdir()

    nuke = _reload_nuke(store_root, willow_dir)

    with patch.object(nuke, "_truncate_pg_tables", return_value=(["compact_contexts"], [])):
        result = nuke.execute(dry_run=True)

    data = json.loads(Path(result.receipt_path).read_text())
    for key in ("nuke_at", "dry_run", "store_files_deleted", "store_bytes_freed",
                "pg_tables_truncated", "tmp_files_removed", "errors"):
        assert key in data, f"Missing key: {key}"
