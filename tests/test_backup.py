"""Tests for W19BK — Backup/Restore."""
import json
import sys
import tarfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_backup_creates_tar(tmp_path):
    (tmp_path / ".willow" / "store").mkdir(parents=True)
    (tmp_path / ".willow" / "version").write_text("1.9.0\n")
    from core.backup import create_backup
    backup_path = create_backup(
        willow_home=tmp_path / ".willow",
        backup_root=tmp_path / "backups",
        skip_pg=True,
    )
    assert backup_path.exists()
    assert str(backup_path).endswith(".tar.gz")


def test_backup_tar_contains_version(tmp_path):
    (tmp_path / ".willow" / "store").mkdir(parents=True)
    (tmp_path / ".willow" / "version").write_text("1.9.0\n")
    from core.backup import create_backup
    backup_path = create_backup(
        willow_home=tmp_path / ".willow",
        backup_root=tmp_path / "backups",
        skip_pg=True,
    )
    with tarfile.open(backup_path, "r:gz") as tar:
        names = tar.getnames()
    assert any("version" in n for n in names)


def test_backup_manifest_written(tmp_path):
    (tmp_path / ".willow" / "store").mkdir(parents=True)
    (tmp_path / ".willow" / "version").write_text("1.9.0\n")
    from core.backup import create_backup
    backup_path = create_backup(
        willow_home=tmp_path / ".willow",
        backup_root=tmp_path / "backups",
        skip_pg=True,
    )
    data = json.loads((backup_path.parent / "manifest.json").read_text())
    assert data["version"] == "1.9.0"
    assert data["pg_included"] is False


def test_backup_is_idempotent(tmp_path):
    (tmp_path / ".willow" / "store").mkdir(parents=True)
    (tmp_path / ".willow" / "version").write_text("1.9.0\n")
    from core.backup import create_backup
    b1 = create_backup(tmp_path / ".willow", tmp_path / "backups", skip_pg=True)
    b2 = create_backup(tmp_path / ".willow", tmp_path / "backups", skip_pg=True)
    assert b1 != b2
    assert b1.exists()
    assert b2.exists()
