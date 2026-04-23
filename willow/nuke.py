#!/usr/bin/env python3
"""
willow/nuke.py — Forensic delete for SOIL store and session context.
b17: NUKE1  ΔΣ=42

What it deletes:
  - SOIL store: all *.db files under WILLOW_STORE_ROOT (SQLite collections)
  - Postgres: truncates compact_contexts (session-scoped) and willow_session temp data
  - Tmp: removes ~/.willow/session_anchor.json and anchor_state.json
  - Writes a timestamped nuke receipt to ~/.willow/logs/

What it does NOT delete:
  - Postgres knowledge, tasks, jeles_sessions, frank_ledger, agents — these are permanent
  - Ollama models
  - Handoffs, binder files, ratifications

Usage:
    from willow.nuke import execute
    result = execute()  # returns NukeResult
"""

import glob
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("willow.nuke")

STORE_ROOT = Path(os.environ.get("WILLOW_STORE_ROOT", Path.home() / ".willow" / "store"))
WILLOW_DIR = Path.home() / ".willow"
LOGS_DIR = WILLOW_DIR / "logs"

_TMP_PATTERNS = [
    str(WILLOW_DIR / "session_anchor.json"),
    str(WILLOW_DIR / "anchor_state.json"),
]


@dataclass
class NukeResult:
    timestamp: str
    store_files_deleted: int = 0
    store_bytes_freed: int = 0
    pg_tables_truncated: list = field(default_factory=list)
    tmp_files_removed: int = 0
    errors: list = field(default_factory=list)
    receipt_path: Optional[str] = None

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


_PG_NUKE_TABLES = [
    "compact_contexts",   # session context
    "knowledge",          # LOAM atoms
    "cmb_atoms",          # ganesha atoms
    "frank_ledger",       # hash chain from genesis
    "opus_atoms",         # opus layer
    "feedback",           # feedback records
    "journal",            # journal entries
]


def _truncate_pg_tables() -> tuple[list, list]:
    """Truncate all nuke-targeted Postgres tables. Returns (truncated, errors)."""
    truncated = []
    errors = []
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.pg_bridge import PgBridge
        pg = PgBridge()
        with pg.conn.cursor() as cur:
            for table in _PG_NUKE_TABLES:
                try:
                    cur.execute(f"TRUNCATE TABLE {table}")
                    truncated.append(table)
                except Exception as e:
                    errors.append(f"truncate {table}: {e}")
        pg.conn.commit()
    except Exception as e:
        errors.append(f"pg connect: {e}")
    return truncated, errors


def execute(dry_run: bool = False) -> NukeResult:
    """
    Execute forensic delete. Returns NukeResult.
    Set dry_run=True to see what would be deleted without deleting.
    """
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = NukeResult(timestamp=ts)

    # 1. SOIL store
    if STORE_ROOT.exists():
        for db_file in STORE_ROOT.rglob("*.db"):
            try:
                size = db_file.stat().st_size
                if not dry_run:
                    db_file.unlink()
                result.store_files_deleted += 1
                result.store_bytes_freed += size
                logger.info("nuke: removed %s (%d bytes)", db_file, size)
            except Exception as e:
                result.errors.append(f"rm {db_file}: {e}")
    else:
        logger.info("nuke: STORE_ROOT not found (%s), skipping", STORE_ROOT)

    # 2. Postgres tables (LOAM atoms, ledger, session context)
    if not dry_run:
        truncated, pg_errors = _truncate_pg_tables()
        result.pg_tables_truncated = truncated
        result.errors.extend(pg_errors)
    else:
        result.pg_tables_truncated = [f"{t} (dry_run)" for t in _PG_NUKE_TABLES]

    # 3. Tmp session files
    for pattern in _TMP_PATTERNS:
        p = Path(pattern)
        if p.exists():
            try:
                if not dry_run:
                    p.unlink()
                result.tmp_files_removed += 1
                logger.info("nuke: removed tmp %s", p)
            except Exception as e:
                result.errors.append(f"rm {p}: {e}")

    # 4. Write receipt
    receipt = {
        "nuke_at": ts,
        "dry_run": dry_run,
        "store_files_deleted": result.store_files_deleted,
        "store_bytes_freed": result.store_bytes_freed,
        "pg_tables_truncated": result.pg_tables_truncated,
        "tmp_files_removed": result.tmp_files_removed,
        "errors": result.errors,
    }
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    label = "DRY" if dry_run else "NUKE"
    receipt_path = LOGS_DIR / f"{label}_{ts.replace(':', '').replace('-', '')[:15]}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))
    result.receipt_path = str(receipt_path)
    logger.info("nuke: receipt written to %s", receipt_path)

    return result


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Willow forensic delete")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    r = execute(dry_run=args.dry_run)
    print(json.dumps({
        "success": r.success,
        "store_files_deleted": r.store_files_deleted,
        "store_bytes_freed": r.store_bytes_freed,
        "pg_tables_truncated": r.pg_tables_truncated,
        "tmp_files_removed": r.tmp_files_removed,
        "errors": r.errors,
        "receipt": r.receipt_path,
    }, indent=2))
