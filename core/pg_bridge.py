#!/usr/bin/env python3
"""
pg_bridge.py — LOAM: Postgres connection and schema.
b17: PGBR1  ΔΣ=42

Schema is correct from first CREATE TABLE. No ALTER TABLE ever.
"""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
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
    trust       TEXT DEFAULT 'WORKER',
    folder_root TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    submitted_by TEXT,
    agent        TEXT DEFAULT 'kart',
    status       TEXT DEFAULT 'pending',
    result       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opus_atoms (
    id             TEXT PRIMARY KEY,
    content        TEXT NOT NULL,
    domain         TEXT DEFAULT 'meta',
    depth          INTEGER DEFAULT 1,
    source_session TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id         TEXT PRIMARY KEY,
    domain     TEXT DEFAULT 'meta',
    principle  TEXT NOT NULL,
    source     TEXT DEFAULT 'self',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS journal (
    id         TEXT PRIMARY KEY,
    entry      TEXT NOT NULL,
    session_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jeles_sessions (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    jsonl_path  TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    cwd         TEXT,
    turn_count  INTEGER DEFAULT 0,
    file_size   INTEGER DEFAULT 0,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jeles_atoms (
    id         TEXT PRIMARY KEY,
    jsonl_id   TEXT NOT NULL,
    agent      TEXT NOT NULL,
    content    TEXT NOT NULL,
    domain     TEXT DEFAULT 'meta',
    depth      INTEGER DEFAULT 1,
    certainty  FLOAT DEFAULT 0.98,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS binder_files (
    id         TEXT PRIMARY KEY,
    agent      TEXT NOT NULL,
    jsonl_id   TEXT NOT NULL,
    dest_path  TEXT NOT NULL,
    filed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS binder_edges (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    source_atom TEXT NOT NULL,
    target_atom TEXT NOT NULL,
    edge_type   TEXT NOT NULL,
    status      TEXT DEFAULT 'proposed',
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ratifications (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    jsonl_id    TEXT NOT NULL,
    approved    BOOLEAN NOT NULL,
    cache_path  TEXT,
    ratified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Columns added after initial deployment — safe to run repeatedly.
_MIGRATIONS = [
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS project TEXT NOT NULL DEFAULT 'global'",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS valid_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS invalid_at TIMESTAMPTZ",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS category TEXT",
    "ALTER TABLE frank_ledger ADD COLUMN IF NOT EXISTS project TEXT NOT NULL DEFAULT 'global'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS trust TEXT DEFAULT 'WORKER'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS folder_root TEXT",
]

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_knowledge_project ON knowledge (project);
CREATE INDEX IF NOT EXISTS idx_knowledge_valid_at ON knowledge (valid_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_invalid_at ON knowledge (invalid_at)
    WHERE invalid_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_agent_status ON tasks (agent, status);
CREATE INDEX IF NOT EXISTS idx_opus_atoms_domain ON opus_atoms (domain);
CREATE INDEX IF NOT EXISTS idx_feedback_domain ON feedback (domain);
CREATE INDEX IF NOT EXISTS idx_jeles_sessions_agent ON jeles_sessions (agent);
CREATE INDEX IF NOT EXISTS idx_jeles_atoms_jsonl ON jeles_atoms (jsonl_id);
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
        for stmt in _MIGRATIONS:
            cur.execute(stmt)
        cur.execute(_INDEXES)
    conn.commit()


class PgBridge:
    def __init__(self):
        self.conn = _connect()
        init_schema(self.conn)
        self._last_ingest_error = None

    # ── Connection resilience ─────────────────────────────────────────────────

    def _ensure_conn(self):
        """Reconnect if the connection was dropped (handles DDoS-induced disconnects)."""
        try:
            self.conn.cursor().execute("SELECT 1")
        except Exception:
            try:
                self.conn = _connect()
            except Exception:
                pass

    @staticmethod
    def gen_id(length: int = 5) -> str:
        """Generate a base-17 style short ID."""
        raw = uuid.uuid4().hex[:length * 2]
        return raw[:length].upper()

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        self._ensure_conn()
        tables = ["knowledge", "tasks", "opus_atoms", "feedback", "journal",
                  "jeles_sessions", "jeles_atoms", "agents", "frank_ledger"]
        result = {}
        try:
            with self.conn.cursor() as cur:
                for t in tables:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {t}")
                        result[t] = cur.fetchone()[0]
                    except Exception:
                        result[t] = -1
        except Exception:
            pass
        return result

    # ── Knowledge ────────────────────────────────────────────────────────────

    def knowledge_put(self, record: dict) -> str:
        self._ensure_conn()
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

    def ingest_atom(self, title: str, summary: str, source_type: str = "mcp",
                    source_id: str = "", category: str = "general",
                    domain: Optional[str] = None) -> Optional[str]:
        """sap_mcp.py compatibility wrapper for willow_knowledge_ingest."""
        try:
            self._last_ingest_error = None
            atom_id = self.gen_id(8)
            self.knowledge_put({
                "id":          atom_id,
                "project":     domain or "global",
                "title":       title,
                "summary":     summary,
                "source_type": source_type,
                "content":     {"source_id": source_id},
                "category":    category,
            })
            return atom_id
        except Exception as e:
            self._last_ingest_error = str(e)
            return None

    def knowledge_close(self, old_id: str, new_valid_at: datetime) -> None:
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE knowledge SET invalid_at = %s
                WHERE id = %s AND invalid_at IS NULL
            """, (new_valid_at, old_id))
        self.conn.commit()

    def knowledge_search(self, query: str, project: Optional[str] = None,
                         include_invalid: bool = False, limit: int = 20) -> list:
        self._ensure_conn()
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

    def knowledge_at(self, query: str, at_time: datetime,
                     project: Optional[str] = None, limit: int = 20) -> list:
        self._ensure_conn()
        at_time_upper = at_time + timedelta(seconds=5)
        filters = [
            "(title ILIKE %s OR summary ILIKE %s)",
            "valid_at <= %s",
            "(invalid_at IS NULL OR invalid_at > %s)",
        ]
        params = [f"%{query}%", f"%{query}%", at_time_upper, at_time]
        if project:
            filters.append("project = %s")
            params.append(project)
        where = " AND ".join(filters)
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM knowledge WHERE {where} LIMIT %s",
                params + [limit],
            )
            return [dict(r) for r in cur.fetchall()]

    # ── CMB ──────────────────────────────────────────────────────────────────

    def cmb_put(self, atom_id: str, content: dict) -> None:
        self._ensure_conn()
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cmb_atoms (id, content) VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (atom_id, psycopg2.extras.Json(content)))
        self.conn.commit()

    def ingest_ganesha_atom(self, entry: str, domain: str = "meta",
                            depth: int = 1) -> Optional[str]:
        """Store a journal/ganesha atom. Falls back to cmb_atoms for now."""
        try:
            atom_id = self.gen_id(8)
            self.cmb_put(atom_id, {"entry": entry, "domain": domain, "depth": depth})
            return atom_id
        except Exception:
            return None

    # ── Tasks ────────────────────────────────────────────────────────────────

    def submit_task(self, task: str, submitted_by: str = "ganesha",
                    agent: str = "kart") -> Optional[str]:
        self._ensure_conn()
        try:
            task_id = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tasks (id, task, submitted_by, agent)
                    VALUES (%s, %s, %s, %s)
                """, (task_id, task, submitted_by, agent))
            self.conn.commit()
            return task_id
        except Exception:
            return None

    def task_status(self, task_id: str) -> Optional[dict]:
        self._ensure_conn()
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def pending_tasks(self, agent: str = "kart", limit: int = 10) -> list:
        self._ensure_conn()
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM tasks WHERE agent = %s AND status = 'pending'
                ORDER BY created_at ASC LIMIT %s
            """, (agent, limit))
            return [dict(r) for r in cur.fetchall()]

    # ── Opus ─────────────────────────────────────────────────────────────────

    def search_opus(self, query: str, limit: int = 20) -> list:
        self._ensure_conn()
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM opus_atoms
                WHERE content ILIKE %s
                ORDER BY created_at DESC LIMIT %s
            """, (f"%{query}%", limit))
            return [dict(r) for r in cur.fetchall()]

    def ingest_opus_atom(self, content: str, domain: str = "meta",
                         depth: int = 1, source_session: Optional[str] = None) -> Optional[str]:
        self._ensure_conn()
        try:
            atom_id = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO opus_atoms (id, content, domain, depth, source_session)
                    VALUES (%s, %s, %s, %s, %s)
                """, (atom_id, content, domain, depth, source_session))
            self.conn.commit()
            return atom_id
        except Exception:
            return None

    def opus_feedback(self, domain: Optional[str] = None) -> list:
        self._ensure_conn()
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if domain:
                cur.execute("""
                    SELECT * FROM feedback WHERE domain = %s
                    ORDER BY created_at DESC LIMIT 50
                """, (domain,))
            else:
                cur.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 50")
            return [dict(r) for r in cur.fetchall()]

    def opus_feedback_write(self, domain: str, principle: str,
                            source: str = "self") -> bool:
        self._ensure_conn()
        try:
            fid = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO feedback (id, domain, principle, source)
                    VALUES (%s, %s, %s, %s)
                """, (fid, domain, principle, source))
            self.conn.commit()
            return True
        except Exception:
            return False

    def opus_journal_write(self, entry: str,
                           session_id: Optional[str] = None) -> Optional[str]:
        self._ensure_conn()
        try:
            jid = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO journal (id, entry, session_id)
                    VALUES (%s, %s, %s)
                """, (jid, entry, session_id))
            self.conn.commit()
            return jid
        except Exception:
            return None

    # ── Agents ───────────────────────────────────────────────────────────────

    def agent_create(self, name: str, trust: str = "WORKER",
                     role: str = "", folder_root: Optional[str] = None) -> dict:
        self._ensure_conn()
        try:
            agent_id = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO agents (id, name, role, trust, folder_root)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        role = EXCLUDED.role,
                        trust = EXCLUDED.trust,
                        folder_root = EXCLUDED.folder_root
                    RETURNING id
                """, (agent_id, name, role, trust, folder_root))
                row = cur.fetchone()
            self.conn.commit()
            return {"id": row[0] if row else agent_id, "name": name, "status": "created"}
        except Exception as e:
            return {"error": str(e)}

    # ── JELES ────────────────────────────────────────────────────────────────

    def jeles_register_jsonl(self, agent: str, jsonl_path: str, session_id: str,
                             cwd: Optional[str] = None, turn_count: int = 0,
                             file_size: int = 0) -> dict:
        self._ensure_conn()
        try:
            jid = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jeles_sessions
                        (id, agent, jsonl_path, session_id, cwd, turn_count, file_size)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (jid, agent, jsonl_path, session_id, cwd, turn_count, file_size))
            self.conn.commit()
            return {"id": jid, "status": "registered"}
        except Exception as e:
            return {"error": str(e)}

    def jeles_extract_atom(self, agent: str, jsonl_id: str, content: str,
                           domain: str = "meta", depth: int = 1,
                           certainty: float = 0.98,
                           title: Optional[str] = None) -> dict:
        self._ensure_conn()
        try:
            aid = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jeles_atoms
                        (id, jsonl_id, agent, content, domain, depth, certainty, title)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (aid, jsonl_id, agent, content, domain, depth, certainty, title))
            self.conn.commit()
            return {"id": aid, "status": "extracted"}
        except Exception as e:
            return {"error": str(e)}

    # ── Binder ───────────────────────────────────────────────────────────────

    def binder_file(self, agent: str, jsonl_id: str, dest_path: str) -> dict:
        self._ensure_conn()
        try:
            fid = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO binder_files (id, agent, jsonl_id, dest_path)
                    VALUES (%s, %s, %s, %s)
                """, (fid, agent, jsonl_id, dest_path))
            self.conn.commit()
            return {"id": fid, "status": "filed"}
        except Exception as e:
            return {"error": str(e)}

    def binder_propose_edge(self, agent: str, source_atom: str,
                            target_atom: str, edge_type: str) -> dict:
        self._ensure_conn()
        try:
            eid = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO binder_edges
                        (id, agent, source_atom, target_atom, edge_type)
                    VALUES (%s, %s, %s, %s, %s)
                """, (eid, agent, source_atom, target_atom, edge_type))
            self.conn.commit()
            return {"id": eid, "status": "proposed"}
        except Exception as e:
            return {"error": str(e)}

    # ── Ratify ───────────────────────────────────────────────────────────────

    def ratify(self, agent: str, jsonl_id: str, approve: bool = True,
               cache_path: Optional[str] = None) -> dict:
        self._ensure_conn()
        try:
            rid = self.gen_id(8)
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ratifications (id, agent, jsonl_id, approved, cache_path)
                    VALUES (%s, %s, %s, %s, %s)
                """, (rid, agent, jsonl_id, approve, cache_path))
            self.conn.commit()
            return {"id": rid, "approved": approve, "status": "ratified"}
        except Exception as e:
            return {"error": str(e)}

    # ── Ledger ───────────────────────────────────────────────────────────────

    def ledger_append(self, project: str, event_type: str, content: dict) -> str:
        # Known limitation: not concurrency-safe — two writers can fork the hash chain.
        # Single-writer model assumed. Tracked for Plan 3: SELECT FOR UPDATE if needed.
        self._ensure_conn()
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
        self._ensure_conn()
        filters = []
        params = []
        if project:
            filters.append("project = %s")
            params.append(project)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM frank_ledger {where} ORDER BY created_at DESC LIMIT %s",
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def ledger_verify(self):
        self._ensure_conn()
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
