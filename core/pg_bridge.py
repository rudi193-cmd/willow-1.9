#!/usr/bin/env python3
"""
pg_bridge.py — LOAM: Postgres connection and schema.
b17: PGBR1  ΔΣ=42

Schema is correct from first CREATE TABLE. No ALTER TABLE ever.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False


_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL DEFAULT 'global',
    valid_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalid_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    title       TEXT,
    summary     TEXT,
    content     JSONB,
    source_type TEXT,
    category    TEXT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_project ON knowledge (project);
CREATE INDEX IF NOT EXISTS idx_knowledge_valid_at ON knowledge (valid_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_invalid_at ON knowledge (invalid_at)
    WHERE invalid_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS cmb_atoms (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    content     JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS frank_ledger (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL DEFAULT 'global',
    event_type  TEXT NOT NULL,
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    prev_hash   TEXT,
    hash        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    role        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _connect() -> "psycopg2.connection":
    return psycopg2.connect(
        dbname=os.environ.get("WILLOW_PG_DB", "willow_19"),
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
        host=os.environ.get("WILLOW_PG_HOST"),
        port=os.environ.get("WILLOW_PG_PORT"),
    )


def try_connect() -> Optional["psycopg2.connection"]:
    try:
        return _connect()
    except Exception:
        return None


def init_schema(conn: "psycopg2.connection") -> None:
    with conn.cursor() as cur:
        cur.execute(_SCHEMA)
    conn.commit()


class PgBridge:
    def __init__(self):
        self.conn = _connect()
        init_schema(self.conn)

    def knowledge_put(self, record: dict) -> str:
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge
                    (id, project, valid_at, invalid_at, title, summary, content, source_type, category)
                VALUES
                    (%(id)s, %(project)s, %(valid_at)s, %(invalid_at)s,
                     %(title)s, %(summary)s, %(content)s, %(source_type)s, %(category)s)
                ON CONFLICT (id) DO UPDATE SET
                    project     = EXCLUDED.project,
                    valid_at    = EXCLUDED.valid_at,
                    title       = EXCLUDED.title,
                    summary     = EXCLUDED.summary,
                    content     = EXCLUDED.content,
                    source_type = EXCLUDED.source_type,
                    category    = EXCLUDED.category
            """, {
                "id":          record["id"],
                "project":     record.get("project", "global"),
                "valid_at":    record.get("valid_at", datetime.now(timezone.utc)),
                "invalid_at":  record.get("invalid_at"),
                "title":       record.get("title"),
                "summary":     record.get("summary"),
                "content":     psycopg2.extras.Json(record.get("content")),
                "source_type": record.get("source_type"),
                "category":    record.get("category"),
            })
        self.conn.commit()
        return record["id"]

    def knowledge_close(self, old_id: str, new_valid_at: datetime) -> None:
        """Bi-temporal contradiction resolution: close old edge when new one opens."""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE knowledge SET invalid_at = %s
                WHERE id = %s AND invalid_at IS NULL
            """, (new_valid_at, old_id))
        self.conn.commit()

    def knowledge_search(self, query: str, project: Optional[str] = None,
                         include_invalid: bool = False, limit: int = 20) -> list:
        filters = ["(title ILIKE %s OR summary ILIKE %s)"]
        params = [f"%{query}%", f"%{query}%"]
        if project:
            filters.append("project = %s")
            params.append(project)
        if not include_invalid:
            filters.append("invalid_at IS NULL")
        where = " AND ".join(filters)
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM knowledge WHERE {where} LIMIT %s", params + [limit])
            return [dict(r) for r in cur.fetchall()]

    def cmb_put(self, atom_id: str, content: dict) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cmb_atoms (id, content) VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (atom_id, psycopg2.extras.Json(content)))
        self.conn.commit()

    def ledger_append(self, project: str, event_type: str, content: dict) -> str:
        # Known limitation: not concurrency-safe — two writers can fork the hash chain.
        # Single-writer model assumed. Tracked for Plan 3: SELECT FOR UPDATE if needed.
        import uuid
        record_id = str(uuid.uuid4())
        with self.conn.cursor() as cur:
            cur.execute("SELECT hash FROM frank_ledger ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            prev_hash = row[0] if row else None
            payload = json.dumps({"event_type": event_type, "content": content}, sort_keys=True)
            new_hash = hashlib.sha256(f"{prev_hash or ''}{payload}".encode()).hexdigest()
            cur.execute("""
                INSERT INTO frank_ledger (id, project, event_type, content, prev_hash, hash)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (record_id, project, event_type, psycopg2.extras.Json(content),
                  prev_hash, new_hash))
        self.conn.commit()
        return record_id

    def ledger_read(self, project=None, limit=50):
        """Read ledger entries, newest first, optionally filtered by project."""
        import psycopg2.extras as _ex
        filters = []
        params = []
        if project:
            filters.append("project = %s")
            params.append(project)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)
        with self.conn.cursor(cursor_factory=_ex.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM frank_ledger {where} ORDER BY created_at DESC LIMIT %s",
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def ledger_verify(self):
        """Verify hash chain integrity. Returns {valid, broken_at, count}."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, event_type, content, prev_hash, hash "
                "FROM frank_ledger ORDER BY created_at ASC"
            )
            rows = cur.fetchall()
        if not rows:
            return {"valid": True, "broken_at": None, "count": 0}
        prev = None
        for record_id, event_type, content, prev_hash, stored_hash in rows:
            payload = json.dumps(
                {"event_type": event_type, "content": content}, sort_keys=True
            )
            expected = hashlib.sha256(f"{prev or ''}{payload}".encode()).hexdigest()
            if expected != stored_hash:
                return {"valid": False, "broken_at": record_id, "count": len(rows)}
            if prev_hash != prev:
                return {"valid": False, "broken_at": record_id, "count": len(rows)}
            prev = stored_hash
        return {"valid": True, "broken_at": None, "count": len(rows)}
