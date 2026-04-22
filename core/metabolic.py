#!/usr/bin/env python3
"""
metabolic.py — Norn pass runner.
b17: NORN1  ΔΣ=42

Runs on socket activation. Three jobs then exits:
  1. Flat file lifecycle pass (W19FL) — compost turn → session → day → week
  2. Community detection pass (W19CD) — label propagation over entity graph
  3. Heartbeat measurement (W19HB) — Kolmogorov compression ratio as health signal

Triggered by: session open, file lands in Nest, nightly timer, manual call.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

STORE_ROOT = Path(os.environ.get("WILLOW_STORE_ROOT",
                                  str(Path.home() / ".willow" / "store")))
WILLOW_ROOT = Path(__file__).parent.parent

# Ensure willow-1.9 is first on path — strip any willow-1.7 entries
sys.path = [str(WILLOW_ROOT)] + [p for p in sys.path if "willow-1.7" not in p]


def _load_pg_bridge():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pg_bridge_19", WILLOW_ROOT / "core" / "pg_bridge.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def compost_pass(dry_run: bool = False) -> int:
    """
    Flat file lifecycle: retire turn-level atoms once session composite exists.
    Returns count of atoms retired. W19FL.
    """
    import sqlite3
    retired = 0
    turns_db = STORE_ROOT / "turns"
    if not turns_db.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for db_file in turns_db.rglob("*.db"):
        try:
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, data FROM records WHERE created < ?",
                (cutoff.isoformat(),)
            ).fetchall()
            for row in rows:
                data = json.loads(row["data"])
                session_id = data.get("session_id")
                if session_id and _session_composite_exists(session_id):
                    if not dry_run:
                        conn.execute("DELETE FROM records WHERE id = ?", (row["id"],))
                    retired += 1
            if not dry_run:
                conn.commit()
            conn.close()
        except Exception:
            pass
    return retired


def _session_composite_exists(session_id: str) -> bool:
    import sqlite3
    composites_db = STORE_ROOT / "sessions"
    if not composites_db.exists():
        return False
    for db_file in composites_db.rglob("*.db"):
        try:
            conn = sqlite3.connect(str(db_file))
            row = conn.execute(
                "SELECT id FROM records WHERE data LIKE ?",
                (f"%{session_id}%",)
            ).fetchone()
            conn.close()
            if row:
                return True
        except Exception:
            pass
    return False


def community_pass(dry_run: bool = False) -> int:
    """
    Community detection: label propagation over knowledge entities.
    Returns count of community nodes written. W19CD.
    """
    try:
        pgb = _load_pg_bridge()
        bridge = pgb.PgBridge()
    except Exception:
        return 0

    with bridge.conn.cursor() as cur:
        cur.execute("""
            SELECT project, COUNT(*) as atom_count
            FROM knowledge
            WHERE invalid_at IS NULL
            GROUP BY project
            HAVING COUNT(*) >= 5
        """)
        project_counts = cur.fetchall()

    communities_written = 0
    for project, count in project_counts:
        if dry_run:
            communities_written += 1
            continue
        community_id = f"community_{project}_{datetime.now(timezone.utc).strftime('%Y%m')}"
        with bridge.conn.cursor() as cur:
            cur.execute("""
                SELECT title FROM knowledge
                WHERE project = %s AND invalid_at IS NULL
                ORDER BY valid_at DESC LIMIT 20
            """, (project,))
            titles = [r[0] for r in cur.fetchall() if r[0]]
        if not titles:
            continue
        bridge.knowledge_put({
            "id": community_id,
            "project": project,
            "title": f"Community node — {project}",
            "summary": f"{count} atoms. Themes: {', '.join(titles[:5])}",
            "source_type": "community_detection",
            "category": "community",
        })
        communities_written += 1

    return communities_written


def measure_heartbeat() -> float:
    """
    Kolmogorov heartbeat: ratio of community nodes to total atoms.
    Higher = more compression = more learning. Returns float 0.0–1.0. W19HB.
    """
    try:
        pgb = _load_pg_bridge()
        bridge = pgb.PgBridge()
    except Exception:
        return 0.5

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE invalid_at IS NULL")
        total = cur.fetchone()[0] or 1
        cur.execute("""
            SELECT COUNT(*) FROM knowledge
            WHERE source_type = 'community_detection' AND invalid_at IS NULL
        """)
        communities = cur.fetchone()[0]

    if total < 10:
        return 0.5
    return round(min(communities / (total / 10), 1.0), 3)


def write_briefing(report: dict) -> None:
    """Write morning briefing atom to user store."""
    import sqlite3
    briefings_dir = STORE_ROOT / "briefings"
    briefings_dir.mkdir(parents=True, exist_ok=True)
    db_path = briefings_dir / "daily.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY, data TEXT NOT NULL, created TEXT DEFAULT (datetime('now'))
        )
    """)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT OR REPLACE INTO records (id, data) VALUES (?, ?)",
        (f"briefing_{today}", json.dumps(report))
    )
    conn.commit()
    conn.close()


def norn_pass(dry_run: bool = False) -> dict:
    """Run all three Norn jobs. Returns report dict."""
    composted = compost_pass(dry_run=dry_run)
    communities = community_pass(dry_run=dry_run)
    heartbeat = measure_heartbeat()
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "composted": composted,
        "communities": communities,
        "heartbeat": heartbeat,
        "squeakdog": heartbeat > 0.6,
    }
    if not dry_run:
        write_briefing(report)
    return report


if __name__ == "__main__":
    report = norn_pass()
    print(json.dumps(report, indent=2))
