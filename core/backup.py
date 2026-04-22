#!/usr/bin/env python3
"""
backup.py — W19BK: Backup and restore.
b17: BAK19  ΔΣ=42

Snorri Sturluson wrote down the myths. willow backup does the same.

  willow backup           — creates ~/.willow/backups/<timestamp>/
  willow restore <path>   — restores from a backup directory
"""
import json
import os
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _safe_tar_members(tar: tarfile.TarFile, target_dir: Path):
    """Yield only members that extract inside target_dir — no path traversal."""
    target = str(target_dir.resolve())
    for member in tar.getmembers():
        member_path = str((target_dir / member.name).resolve())
        if member_path.startswith(target + os.sep) or member_path == target:
            yield member


def create_backup(
    willow_home: Optional[Path] = None,
    backup_root: Optional[Path] = None,
    pg_db: str = "willow_19",
    skip_pg: bool = False,
) -> Path:
    """
    Create a timestamped backup of ~/.willow/ and optionally pg_dump willow_19.
    Returns path to the .tar.gz file.
    """
    home = willow_home or (Path.home() / ".willow")
    root = backup_root or (Path.home() / ".willow" / "backups")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S-%f")
    backup_dir = root / ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    tar_path = backup_dir / "willow-store.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        if home.exists():
            tar.add(home, arcname=".willow",
                    filter=lambda ti: None if "backups" in ti.name else ti)

    pg_included = False
    if not skip_pg:
        sql_path = backup_dir / f"{pg_db}.sql"
        try:
            result = subprocess.run(["pg_dump", pg_db], capture_output=True, text=True)
            if result.returncode == 0:
                sql_path.write_text(result.stdout)
                pg_included = True
        except FileNotFoundError:
            pass

    version = "unknown"
    version_file = home / "version"
    if version_file.exists():
        version = version_file.read_text().strip()

    (backup_dir / "manifest.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
        "pg_included": pg_included,
        "pg_db": pg_db if pg_included else None,
        "tar": tar_path.name,
    }, indent=2))

    return tar_path


def restore_backup(backup_path: Path, willow_home: Optional[Path] = None,
                   pg_db: str = "willow_19") -> None:
    """Restore from a backup directory. Unpacks tar into ~/.willow/."""
    home_parent = (willow_home or (Path.home() / ".willow")).parent
    backup_dir = backup_path if backup_path.is_dir() else backup_path.parent

    tar_files = list(backup_dir.glob("*.tar.gz"))
    if not tar_files:
        raise FileNotFoundError(f"No .tar.gz found in {backup_dir}")

    with tarfile.open(tar_files[0], "r:gz") as tar:
        tar.extractall(home_parent,
                       members=list(_safe_tar_members(tar, Path(home_parent))))

    sql_file = backup_dir / f"{pg_db}.sql"
    if sql_file.exists():
        try:
            subprocess.run(["psql", pg_db], input=sql_file.read_text(),
                           text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"  Postgres restore failed: {e}")
            print(f"  Manual restore: psql {pg_db} < {sql_file}")
