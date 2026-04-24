# willow/forks.py — Fork CRUD operations. b17: FORKS1  ΔΣ=42
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone

from core.pg_bridge import PgBridge


def _b17() -> str:
    return str(uuid.uuid4()).upper().replace("-", "")[:8]


def fork_create(
    bridge: PgBridge,
    title: str,
    created_by: str,
    topic: str = "",
    fork_id: str | None = None,
) -> dict:
    fork_id = fork_id or f"FORK-{_b17()}"
    cur = bridge.conn.cursor()
    cur.execute("""
        INSERT INTO forks (id, title, created_by, topic, status, participants, changes)
        VALUES (%s, %s, %s, %s, 'open', %s, '[]')
    """, (fork_id, title, created_by, topic, json.dumps([created_by])))
    bridge.conn.commit()
    return {"fork_id": fork_id, "status": "open"}


def _as_list(val) -> list:
    """Psycopg2 may return JSONB as a Python object already; normalize to list."""
    if isinstance(val, list):
        return val
    return json.loads(val)


def fork_join(bridge: PgBridge, fork_id: str, component: str) -> dict:
    cur = bridge.conn.cursor()
    cur.execute("SELECT participants FROM forks WHERE id = %s", (fork_id,))
    row = cur.fetchone()
    if not row:
        return {"error": f"fork {fork_id} not found"}
    participants = _as_list(row[0])
    if component not in participants:
        participants.append(component)
    cur.execute("UPDATE forks SET participants = %s WHERE id = %s",
                (json.dumps(participants), fork_id))
    bridge.conn.commit()
    return {"fork_id": fork_id, "participants": participants}


def fork_log(
    bridge: PgBridge,
    fork_id: str,
    component: str,
    type_: str,
    ref: str,
    description: str = "",
) -> dict:
    cur = bridge.conn.cursor()
    cur.execute("SELECT changes FROM forks WHERE id = %s", (fork_id,))
    row = cur.fetchone()
    if not row:
        return {"error": f"fork {fork_id} not found"}
    changes = _as_list(row[0])
    changes.append({
        "component": component, "type": type_, "ref": ref,
        "description": description,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    })
    cur.execute("UPDATE forks SET changes = %s WHERE id = %s",
                (json.dumps(changes), fork_id))
    bridge.conn.commit()
    return {"logged": True, "change_count": len(changes)}


def fork_merge(bridge: PgBridge, fork_id: str, outcome_note: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cur = bridge.conn.cursor()
    cur.execute("""
        UPDATE forks SET status = 'merged', merged_at = %s, outcome_note = %s
        WHERE id = %s AND status = 'open'
    """, (now, outcome_note, fork_id))
    bridge.conn.commit()
    if cur.rowcount == 0:
        return {"merged": False, "reason": "fork not found or not open"}
    cur.execute("UPDATE knowledge SET fork_id = NULL WHERE fork_id = %s", (fork_id,))
    promoted = cur.rowcount
    bridge.conn.commit()
    return {"merged": True, "promoted_count": promoted}


def fork_delete(bridge: PgBridge, fork_id: str, reason: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cur = bridge.conn.cursor()
    cur.execute("""
        UPDATE forks SET status = 'deleted', deleted_at = %s, outcome_note = %s
        WHERE id = %s AND status = 'open'
    """, (now, reason, fork_id))
    bridge.conn.commit()
    if cur.rowcount == 0:
        return {"deleted": False, "reason": "fork not found or not open"}
    # Mark atoms as invalid (soft-archive) — knowledge has no domain column
    cur.execute("""
        UPDATE knowledge SET invalid_at = now()
        WHERE fork_id = %s AND invalid_at IS NULL
    """, (fork_id,))
    archived = cur.rowcount
    bridge.conn.commit()
    return {"deleted": True, "archived_count": archived}


def fork_status(bridge: PgBridge, fork_id: str) -> dict | None:
    cur = bridge.conn.cursor()
    cur.execute("""
        SELECT id, title, created_by, topic, status, participants, changes,
               created_at, merged_at, deleted_at, outcome_note
        FROM forks WHERE id = %s
    """, (fork_id,))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "fork_id": row[0], "title": row[1], "created_by": row[2],
        "topic": row[3], "status": row[4],
        "participants": _as_list(row[5]), "changes": _as_list(row[6]),
        "created_at": str(row[7]), "merged_at": str(row[8]) if row[8] else None,
        "deleted_at": str(row[9]) if row[9] else None, "outcome_note": row[10],
    }


def fork_list(bridge: PgBridge, status: str = "open") -> list[dict]:
    cur = bridge.conn.cursor()
    cur.execute("""
        SELECT id, title, created_at, created_by, topic,
               jsonb_array_length(participants), jsonb_array_length(changes)
        FROM forks WHERE status = %s
        ORDER BY created_at DESC LIMIT 100
    """, (status,))
    return [
        {"fork_id": r[0], "title": r[1], "created_at": str(r[2]),
         "created_by": r[3], "topic": r[4],
         "participant_count": r[5], "change_count": r[6]}
        for r in cur.fetchall()
    ]
