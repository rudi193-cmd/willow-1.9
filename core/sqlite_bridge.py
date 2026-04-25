#!/usr/bin/env python3
"""
sqlite_bridge.py — SQLite backend for Willow. b17: SQBR1 ΔΣ=42

Drop-in replacement for PgBridge when Postgres is unavailable.
Designed for mobile (Termux), CI, and offline-first installs.

DB file: ~/.willow/willow.db  (override with WILLOW_SQLITE_PATH)

Differences from PgBridge:
  - FTS5 virtual table for knowledge search (no pgvector)
  - All timestamps stored as ISO TEXT
  - JSONB stored as TEXT (json.dumps/loads)
  - Thread-safe via check_same_thread=False + per-operation commits
"""
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


_DB_PATH = Path(os.environ.get(
    "WILLOW_SQLITE_PATH",
    str(Path.home() / ".willow" / "willow.db")
))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL DEFAULT 'global',
    valid_at    TEXT NOT NULL DEFAULT (datetime('now')),
    invalid_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    title       TEXT,
    summary     TEXT,
    content     TEXT,
    source_type TEXT,
    category    TEXT,
    visit_count INTEGER NOT NULL DEFAULT 0,
    weight      REAL NOT NULL DEFAULT 1.0,
    last_visited TEXT,
    fork_id     TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    id UNINDEXED,
    title,
    summary,
    content='knowledge',
    content_rowid='rowid'
);

CREATE TABLE IF NOT EXISTS cmb_atoms (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    content    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS frank_ledger (
    id         TEXT PRIMARY KEY,
    project    TEXT NOT NULL DEFAULT 'global',
    event_type TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    prev_hash  TEXT,
    hash       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    role        TEXT,
    trust       TEXT DEFAULT 'WORKER',
    folder_root TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    submitted_by TEXT,
    agent        TEXT DEFAULT 'kart',
    status       TEXT DEFAULT 'pending',
    result       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS opus_atoms (
    id             TEXT PRIMARY KEY,
    content        TEXT NOT NULL,
    domain         TEXT DEFAULT 'meta',
    depth          INTEGER DEFAULT 1,
    source_session TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id         TEXT PRIMARY KEY,
    domain     TEXT DEFAULT 'meta',
    principle  TEXT NOT NULL,
    source     TEXT DEFAULT 'self',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal (
    id         TEXT PRIMARY KEY,
    entry      TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jeles_sessions (
    id            TEXT PRIMARY KEY,
    agent         TEXT NOT NULL,
    jsonl_path    TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    cwd           TEXT,
    turn_count    INTEGER DEFAULT 0,
    file_size     INTEGER DEFAULT 0,
    registered_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jeles_atoms (
    id         TEXT PRIMARY KEY,
    jsonl_id   TEXT NOT NULL,
    agent      TEXT NOT NULL,
    content    TEXT NOT NULL,
    domain     TEXT DEFAULT 'meta',
    depth      INTEGER DEFAULT 1,
    certainty  REAL DEFAULT 0.98,
    title      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS binder_files (
    id         TEXT PRIMARY KEY,
    agent      TEXT NOT NULL,
    jsonl_id   TEXT NOT NULL,
    dest_path  TEXT NOT NULL,
    filed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS binder_edges (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    source_atom TEXT NOT NULL,
    target_atom TEXT NOT NULL,
    edge_type   TEXT NOT NULL,
    status      TEXT DEFAULT 'proposed',
    proposed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ratifications (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    jsonl_id    TEXT NOT NULL,
    approved    INTEGER NOT NULL,
    cache_path  TEXT,
    ratified_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS compact_contexts (
    id         TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'handoff',
    agent      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forks (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    created_by   TEXT NOT NULL,
    topic        TEXT,
    status       TEXT NOT NULL DEFAULT 'open',
    participants TEXT NOT NULL DEFAULT '[]',
    changes      TEXT NOT NULL DEFAULT '[]',
    merged_at    TEXT,
    deleted_at   TEXT,
    outcome_note TEXT
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_knowledge_project    ON knowledge (project);
CREATE INDEX IF NOT EXISTS idx_knowledge_valid_at   ON knowledge (valid_at);
CREATE INDEX IF NOT EXISTS idx_tasks_agent_status   ON tasks (agent, status);
CREATE INDEX IF NOT EXISTS idx_jeles_sessions_agent ON jeles_sessions (agent);
CREATE INDEX IF NOT EXISTS idx_jeles_atoms_jsonl    ON jeles_atoms (jsonl_id);
CREATE INDEX IF NOT EXISTS idx_forks_status         ON forks (status);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, id, title, summary)
    VALUES (new.rowid, new.id, new.title, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, id, title, summary)
    VALUES ('delete', old.rowid, old.id, old.title, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, id, title, summary)
    VALUES ('delete', old.rowid, old.id, old.title, old.summary);
    INSERT INTO knowledge_fts(rowid, id, title, summary)
    VALUES (new.rowid, new.id, new.title, new.summary);
END;
"""

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jdump(obj) -> str:
    if obj is None:
        return "null"
    return json.dumps(obj, default=str)


def _jload(s: Optional[str]):
    if s is None or s == "null":
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def _row_to_dict(cur: sqlite3.Cursor, row: tuple) -> dict:
    cols = [d[0] for d in cur.description]
    d = dict(zip(cols, row))
    # Deserialise JSON columns
    for col in ("content", "result", "participants", "changes", "decision"):
        if col in d and isinstance(d[col], str):
            d[col] = _jload(d[col])
    return d


def _open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.executescript(_INDEXES)
    conn.executescript(_FTS_TRIGGERS)
    conn.commit()
    return conn


def try_connect(path: Optional[Path] = None) -> Optional["SqliteBridge"]:
    """Return a SqliteBridge, or None if the DB file can't be opened."""
    try:
        return SqliteBridge(path)
    except Exception:
        return None


class SqliteBridge:
    """SQLite implementation of the PgBridge API."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DB_PATH
        self.conn = _open_db(self._path)
        self._last_ingest_error = None

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def gen_id(length: int = 5) -> str:
        raw = uuid.uuid4().hex[:length * 2]
        return raw[:length].upper()

    def _exec(self, sql: str, params=()) -> sqlite3.Cursor:
        with _lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def _query(self, sql: str, params=()) -> list:
        with _lock:
            cur = self.conn.execute(sql, params)
            rows = cur.fetchall()
        return [_row_to_dict(cur, r) for r in rows]

    def _query_one(self, sql: str, params=()) -> Optional[dict]:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        tables = ["knowledge", "tasks", "opus_atoms", "feedback", "journal",
                  "jeles_sessions", "jeles_atoms", "agents", "frank_ledger"]
        result = {}
        for t in tables:
            try:
                with _lock:
                    cur = self.conn.execute(f"SELECT COUNT(*) FROM {t}")
                    result[t] = cur.fetchone()[0]
            except Exception:
                result[t] = -1
        return result

    # ── Knowledge ──────────────────────────────────────────────────────────────

    def increment_visit(self, atom_id: str) -> None:
        self._exec("""
            UPDATE knowledge
            SET visit_count  = visit_count + 1,
                last_visited = ?,
                weight       = 1.0 + ((visit_count + 1) * 0.1)
            WHERE id = ?
        """, (_now(), atom_id))

    def knowledge_put(self, record: dict) -> str:
        atom_id = record.get("id") or self.gen_id(8)
        record = {**record, "id": atom_id}
        self._exec("""
            INSERT INTO knowledge
                (id, project, valid_at, invalid_at, title, summary, content, source_type, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project     = excluded.project,
                valid_at    = excluded.valid_at,
                title       = excluded.title,
                summary     = excluded.summary,
                content     = excluded.content,
                source_type = excluded.source_type,
                category    = excluded.category
        """, (
            atom_id,
            record.get("project", "global"),
            record.get("valid_at", _now()),
            record.get("invalid_at"),
            record.get("title"),
            record.get("summary"),
            _jdump(record.get("content")),
            record.get("source_type"),
            record.get("category"),
        ))
        return atom_id

    def ingest_atom(self, title: str, summary: str, source_type: str = "mcp",
                    source_id: str = "", category: str = "general",
                    domain: Optional[str] = None) -> Optional[str]:
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
        self._exec(
            "UPDATE knowledge SET invalid_at = ? WHERE id = ? AND invalid_at IS NULL",
            (new_valid_at.isoformat(), old_id),
        )

    def knowledge_search(self, query: str, project: Optional[str] = None,
                         include_invalid: bool = False, limit: int = 20) -> list:
        # Try FTS5 first, fall back to LIKE
        try:
            fts_sql = """
                SELECT k.* FROM knowledge k
                JOIN knowledge_fts f ON k.rowid = f.rowid
                WHERE knowledge_fts MATCH ?
            """
            params: list = [query]
            if project:
                fts_sql += " AND k.project = ?"
                params.append(project)
            if not include_invalid:
                fts_sql += " AND k.invalid_at IS NULL"
            fts_sql += " ORDER BY rank LIMIT ?"
            params.append(limit)
            results = self._query(fts_sql, params)
            if results:
                return results
        except Exception:
            pass

        # LIKE fallback
        like_sql = """
            SELECT * FROM knowledge
            WHERE (title LIKE ? OR summary LIKE ?)
        """
        like_q = f"%{query}%"
        params = [like_q, like_q]
        if project:
            like_sql += " AND project = ?"
            params.append(project)
        if not include_invalid:
            like_sql += " AND invalid_at IS NULL"
        like_sql += " ORDER BY weight DESC, visit_count DESC LIMIT ?"
        params.append(limit)
        return self._query(like_sql, params)

    def knowledge_at(self, query: str, at_time: datetime,
                     project: Optional[str] = None, limit: int = 20) -> list:
        at_upper = (at_time + timedelta(seconds=5)).isoformat()
        at_iso = at_time.isoformat()
        sql = """
            SELECT * FROM knowledge
            WHERE (title LIKE ? OR summary LIKE ?)
              AND valid_at <= ?
              AND (invalid_at IS NULL OR invalid_at > ?)
        """
        like_q = f"%{query}%"
        params: list = [like_q, like_q, at_upper, at_iso]
        if project:
            sql += " AND project = ?"
            params.append(project)
        sql += " LIMIT ?"
        params.append(limit)
        return self._query(sql, params)

    # ── CMB ───────────────────────────────────────────────────────────────────

    def cmb_put(self, atom_id: str, content: dict) -> None:
        self._exec(
            "INSERT OR IGNORE INTO cmb_atoms (id, content) VALUES (?, ?)",
            (atom_id, _jdump(content)),
        )

    def ingest_ganesha_atom(self, entry: str, domain: str = "meta",
                            depth: int = 1) -> Optional[str]:
        try:
            atom_id = self.gen_id(8)
            self.cmb_put(atom_id, {"entry": entry, "domain": domain, "depth": depth})
            return atom_id
        except Exception:
            return None

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def submit_task(self, task: str, submitted_by: str = "ganesha",
                    agent: str = "kart") -> Optional[str]:
        try:
            task_id = self.gen_id(8)
            self._exec(
                "INSERT INTO tasks (id, task, submitted_by, agent) VALUES (?, ?, ?, ?)",
                (task_id, task, submitted_by, agent),
            )
            return task_id
        except Exception:
            return None

    def task_status(self, task_id: str) -> Optional[dict]:
        return self._query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def pending_tasks(self, agent: str = "kart", limit: int = 10) -> list:
        return self._query(
            "SELECT * FROM tasks WHERE agent = ? AND status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?",
            (agent, limit),
        )

    # ── Opus ──────────────────────────────────────────────────────────────────

    def search_opus(self, query: str, limit: int = 20) -> list:
        return self._query(
            "SELECT * FROM opus_atoms WHERE content LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        )

    def ingest_opus_atom(self, content: str, domain: str = "meta",
                         depth: int = 1, source_session: Optional[str] = None) -> Optional[str]:
        try:
            atom_id = self.gen_id(8)
            self._exec(
                "INSERT INTO opus_atoms (id, content, domain, depth, source_session) "
                "VALUES (?, ?, ?, ?, ?)",
                (atom_id, content, domain, depth, source_session),
            )
            return atom_id
        except Exception:
            return None

    def opus_feedback(self, domain: Optional[str] = None) -> list:
        if domain:
            return self._query(
                "SELECT * FROM feedback WHERE domain = ? ORDER BY created_at DESC LIMIT 50",
                (domain,),
            )
        return self._query("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 50")

    def opus_feedback_write(self, domain: str, principle: str,
                            source: str = "self") -> bool:
        try:
            self._exec(
                "INSERT INTO feedback (id, domain, principle, source) VALUES (?, ?, ?, ?)",
                (self.gen_id(8), domain, principle, source),
            )
            return True
        except Exception:
            return False

    def opus_journal_write(self, entry: str,
                           session_id: Optional[str] = None) -> Optional[str]:
        try:
            jid = self.gen_id(8)
            self._exec(
                "INSERT INTO journal (id, entry, session_id) VALUES (?, ?, ?)",
                (jid, entry, session_id),
            )
            return jid
        except Exception:
            return None

    # ── Agents ────────────────────────────────────────────────────────────────

    def agent_create(self, name: str, trust: str = "WORKER",
                     role: str = "", folder_root: Optional[str] = None) -> dict:
        try:
            agent_id = self.gen_id(8)
            self._exec(
                "INSERT INTO agents (id, name, role, trust, folder_root) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET role=excluded.role, trust=excluded.trust, "
                "folder_root=excluded.folder_root",
                (agent_id, name, role, trust, folder_root),
            )
            return {"id": agent_id, "name": name, "status": "created"}
        except Exception as e:
            return {"error": str(e)}

    # ── JELES ─────────────────────────────────────────────────────────────────

    def jeles_register_jsonl(self, agent: str, jsonl_path: str, session_id: str,
                             cwd: Optional[str] = None, turn_count: int = 0,
                             file_size: int = 0) -> dict:
        try:
            jid = self.gen_id(8)
            self._exec(
                "INSERT OR IGNORE INTO jeles_sessions "
                "(id, agent, jsonl_path, session_id, cwd, turn_count, file_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (jid, agent, jsonl_path, session_id, cwd, turn_count, file_size),
            )
            return {"id": jid, "status": "registered"}
        except Exception as e:
            return {"error": str(e)}

    def jeles_extract_atom(self, agent: str, jsonl_id: str, content: str,
                           domain: str = "meta", depth: int = 1,
                           certainty: float = 0.98,
                           title: Optional[str] = None) -> dict:
        try:
            aid = self.gen_id(8)
            self._exec(
                "INSERT INTO jeles_atoms "
                "(id, jsonl_id, agent, content, domain, depth, certainty, title) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (aid, jsonl_id, agent, content, domain, depth, certainty, title),
            )
            return {"id": aid, "status": "extracted"}
        except Exception as e:
            return {"error": str(e)}

    # ── Binder ────────────────────────────────────────────────────────────────

    def binder_file(self, agent: str, jsonl_id: str, dest_path: str) -> dict:
        try:
            fid = self.gen_id(8)
            self._exec(
                "INSERT INTO binder_files (id, agent, jsonl_id, dest_path) VALUES (?, ?, ?, ?)",
                (fid, agent, jsonl_id, dest_path),
            )
            return {"id": fid, "status": "filed"}
        except Exception as e:
            return {"error": str(e)}

    def binder_propose_edge(self, agent: str, source_atom: str,
                            target_atom: str, edge_type: str) -> dict:
        try:
            eid = self.gen_id(8)
            self._exec(
                "INSERT INTO binder_edges (id, agent, source_atom, target_atom, edge_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (eid, agent, source_atom, target_atom, edge_type),
            )
            return {"id": eid, "status": "proposed"}
        except Exception as e:
            return {"error": str(e)}

    # ── Ratify ────────────────────────────────────────────────────────────────

    def ratify(self, agent: str, jsonl_id: str, approve: bool = True,
               cache_path: Optional[str] = None) -> dict:
        try:
            rid = self.gen_id(8)
            self._exec(
                "INSERT INTO ratifications (id, agent, jsonl_id, approved, cache_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (rid, agent, jsonl_id, 1 if approve else 0, cache_path),
            )
            return {"id": rid, "approved": approve, "status": "ratified"}
        except Exception as e:
            return {"error": str(e)}

    # ── Ledger ────────────────────────────────────────────────────────────────

    def ledger_append(self, project: str, event_type: str, content: dict) -> str:
        record_id = str(uuid.uuid4())
        with _lock:
            cur = self.conn.execute(
                "SELECT hash FROM frank_ledger ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            prev_hash = row[0] if row else None
            payload = json.dumps({"event_type": event_type, "content": content}, sort_keys=True)
            new_hash = hashlib.sha256(f"{prev_hash or ''}{payload}".encode()).hexdigest()
            self.conn.execute(
                "INSERT INTO frank_ledger (id, project, event_type, content, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (record_id, project, event_type, _jdump(content), prev_hash, new_hash),
            )
            self.conn.commit()
        return record_id

    def ledger_read(self, project=None, limit=50) -> list:
        if project:
            return self._query(
                "SELECT * FROM frank_ledger WHERE project = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (project, limit),
            )
        return self._query(
            "SELECT * FROM frank_ledger ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    def ledger_verify(self) -> dict:
        with _lock:
            cur = self.conn.execute(
                "SELECT id, event_type, content, prev_hash, hash "
                "FROM frank_ledger ORDER BY created_at ASC"
            )
            rows = cur.fetchall()
        if not rows:
            return {"valid": True, "broken_at": None, "count": 0}
        prev = None
        for record_id, event_type, content_raw, prev_hash, stored_hash in rows:
            content = _jload(content_raw)
            payload = json.dumps({"event_type": event_type, "content": content}, sort_keys=True)
            expected = hashlib.sha256(f"{prev or ''}{payload}".encode()).hexdigest()
            if expected != stored_hash:
                return {"valid": False, "broken_at": record_id, "count": len(rows)}
            if prev_hash != prev:
                return {"valid": False, "broken_at": record_id, "count": len(rows)}
            prev = stored_hash
        return {"valid": True, "broken_at": None, "count": len(rows)}
