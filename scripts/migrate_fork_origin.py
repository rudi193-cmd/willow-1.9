#!/usr/bin/env python3
"""
scripts/migrate_fork_origin.py
Assign all existing knowledge atoms to FORK-ORIGIN and mark it merged.
Run once after the forks schema is applied.

Usage:
    python3 scripts/migrate_fork_origin.py           # live run
    python3 scripts/migrate_fork_origin.py --dry-run # preview only
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.pg_bridge import PgBridge

FORK_ID = "FORK-ORIGIN"
DRY_RUN = "--dry-run" in sys.argv

print(f"[migrate] FORK-ORIGIN migration {'(DRY RUN) ' if DRY_RUN else ''}starting...")

with PgBridge() as b:
    cur = b.conn.cursor()

    cur.execute("SELECT id FROM forks WHERE id = %s", (FORK_ID,))
    if cur.fetchone():
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE fork_id = %s", (FORK_ID,))
        count = cur.fetchone()[0]
        print(f"[migrate] FORK-ORIGIN already exists with {count} atoms. Nothing to do.")
        sys.exit(0)

    cur.execute("SELECT COUNT(*) FROM knowledge WHERE fork_id IS NULL")
    total = cur.fetchone()[0]
    print(f"[migrate] Found {total} atoms with fork_id IS NULL → will assign to {FORK_ID}")

    if DRY_RUN:
        print("[migrate] DRY RUN — no changes written.")
        sys.exit(0)

    now = datetime.now(timezone.utc).isoformat()

    cur.execute("""
        INSERT INTO forks (id, title, created_by, topic, status, participants, changes, merged_at, outcome_note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        FORK_ID,
        "Origin — all work before Willow Forks",
        "hanuman",
        "foundation",
        "merged",
        json.dumps(["hanuman"]),
        json.dumps([{"component": "kb", "type": "bulk_migration",
                     "count": total, "logged_at": now}]),
        now,
        f"Bootstrap migration: {total} existing atoms assigned at 1.9 launch",
    ))

    cur.execute("UPDATE knowledge SET fork_id = %s WHERE fork_id IS NULL", (FORK_ID,))
    updated = cur.rowcount
    b.conn.commit()

print(f"[migrate] Done. FORK-ORIGIN created. {updated} atoms tagged and marked permanent.")
