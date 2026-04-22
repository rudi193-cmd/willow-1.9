# tests/adversarial/conftest.py
"""Shared adversarial test fixtures.
Inherits WILLOW_PG_DB=willow_19_test and init_pg_schema from tests/conftest.py.
"""
import io
import os
import sys
import tarfile
from pathlib import Path
import pytest

REPO_ROOT = str(Path(__file__).parent.parent.parent)
sys.path = [REPO_ROOT] + [p for p in sys.path if "willow-1.7" not in p]


@pytest.fixture
def bridge():
    from core.pg_bridge import PgBridge
    b = PgBridge()
    yield b
    with b.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE id LIKE 'adv_%'")
        cur.execute("DELETE FROM knowledge WHERE project LIKE 'adv_%'")
        cur.execute("DELETE FROM frank_ledger WHERE project LIKE 'adv_%'")
    b.conn.commit()
    b.conn.close()


@pytest.fixture
def clean_bridge(bridge):
    """Bridge with truncated frank_ledger — for integrity tests that verify the full chain."""
    with bridge.conn.cursor() as cur:
        cur.execute("TRUNCATE frank_ledger")
    bridge.conn.commit()
    return bridge


@pytest.fixture
def tmp_safe_root(tmp_path):
    """Temporary directory standing in for WILLOW_SAFE_ROOT."""
    return tmp_path / "SAFE" / "Applications"


@pytest.fixture
def make_tar(tmp_path):
    """Build a .tar.gz with specified (member_name, content_bytes) pairs."""
    def _make(members: list) -> Path:
        tar_path = tmp_path / "test.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            for name, content in members:
                info = tarfile.TarInfo(name=name)
                data = io.BytesIO(content)
                info.size = len(content)
                tf.addfile(info, data)
        return tar_path
    return _make
