#!/usr/bin/env python3
"""
willow_store.py — SOIL: SQLite-backed user store.
b17: SOIL1  ΔΣ=42

WILLOW_STORE_ROOT defaults to ~/.willow/store/ — never inside the repo.
Each collection is a SQLite database at {root}/{collection}.db.

Security: path sanitization, symlink blocking, 100KB size limit, threading lock.
Rubric: Angular Deviation Rubric v3.0 governs write classification.
Audit: every write is logged to audit_log within each collection DB.
Soft delete: deleted records are invisible to read/search but preserved in audit trail.
"""
import json
import math
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import sqlite_vec
    _VEC_AVAILABLE = True
except ImportError:
    sqlite_vec = None
    _VEC_AVAILABLE = False

try:
    from core.embedder import embed
except ImportError:
    def embed(text):  # noqa: E306
        return None

_DEFAULT_STORE_ROOT = Path.home() / ".willow" / "store"

MAX_RECORD_BYTES = 100_000  # 100KB per record


# ── Angular Deviation Rubric v3.0 ──────────────────────────────────────────────

PI4 = math.pi / 4   # 45°
PI2 = math.pi / 2   # 90°
PI  = math.pi        # 180° — absolute ceiling

class Rubric:
    """Angular deviation rubric with user-configurable thresholds.

    quiet_below: deviations smaller than this are silent (default π/4)
    flag_below:  deviations between quiet and flag are logged (default π/2)
    Above flag_below → stop (requires human ratification).
    """
    def __init__(self, quiet_below: float = math.pi / 4,
                 flag_below: float = math.pi / 2,
                 hard_stops: set | None = None):
        if quiet_below > flag_below:
            raise ValueError("quiet_below must be <= flag_below")
        if flag_below > PI:
            raise ValueError(f"flag_below cannot exceed π ({PI:.4f})")
        self.quiet_below = quiet_below
        self.flag_below = flag_below
        self.hard_stops = hard_stops or set()

    def action(self, deviation: float) -> str:
        mag = abs(deviation)
        for hs in self.hard_stops:
            if mag >= hs:
                return "stop"
        if mag < self.quiet_below:
            return "work_quiet"
        elif mag < self.flag_below:
            return "flag"
        return "stop"

    @classmethod
    def default(cls) -> "Rubric":
        return cls()

    @classmethod
    def verbose(cls) -> "Rubric":
        return cls(quiet_below=math.pi / 8, flag_below=math.pi / 4)

    @classmethod
    def quiet(cls) -> "Rubric":
        return cls(quiet_below=math.pi / 2, flag_below=3 * math.pi / 4)


DEFAULT_RUBRIC = Rubric.default()


def angular_action(deviation: float, rubric: Rubric = None) -> str:
    return (rubric or DEFAULT_RUBRIC).action(deviation)


def net_trajectory(deviations: list[float], rubric: Rubric = None) -> tuple[float, str]:
    if not deviations:
        return 0.0, "stable"
    r = rubric or DEFAULT_RUBRIC
    total = 0.0
    for d in deviations:
        mag = abs(d)
        w = 1.0 if mag >= r.flag_below else (0.5 if mag >= r.quiet_below else 0.25)
        total += d * w
    avg = total / len(deviations)
    if avg > r.quiet_below:
        return avg, "improving"
    elif avg < -r.quiet_below:
        return avg, "degrading"
    return avg, "stable"


# ── Path Security ──────────────────────────────────────────────────────────────

_SAFE_COLLECTION = re.compile(r'^[a-zA-Z0-9_/\-]+$')


def _sanitize_collection(name: str) -> str:
    """Normalize collection name. Block traversal and disallowed characters."""
    clean = "".join(c for c in name if c.isalnum() or c in "/_-")
    while "//" in clean:
        clean = clean.replace("//", "/")
    clean = clean.strip("/")
    parts = [p for p in clean.split("/") if p and p != ".."]
    return "/".join(parts)


def _sanitize_id(record_id: str) -> str:
    """Record IDs: alphanumeric, underscore, hyphen only. No slashes."""
    return "".join(c for c in str(record_id) if c.isalnum() or c in "_-")


# ── Schema migration helpers ───────────────────────────────────────────────────

def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add new columns to existing records tables. Idempotent."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(records)").fetchall()}
    migrations = [
        ("deleted",    "INTEGER DEFAULT 0"),
        ("deviation",  "REAL DEFAULT 0.0"),
        ("action",     "TEXT DEFAULT 'work_quiet'"),
        ("updated_at", "TEXT"),
    ]
    for col, typedef in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE records ADD COLUMN {col} {typedef}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id  TEXT NOT NULL,
            operation  TEXT NOT NULL,
            deviation  REAL,
            action     TEXT,
            timestamp  TEXT NOT NULL
        )
    """)
    conn.commit()


# ── WillowStore ────────────────────────────────────────────────────────────────

class WillowStore:
    def __init__(self, root: Optional[str] = None, rubric: Rubric = None):
        env_root = os.environ.get("WILLOW_STORE_ROOT")
        self.root = Path(root or env_root or _DEFAULT_STORE_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.rubric = rubric or DEFAULT_RUBRIC
        self._lock = threading.Lock()

    def _db_path(self, collection: str) -> Path:
        clean = _sanitize_collection(collection)
        if not clean:
            raise ValueError(f"Invalid collection name: {collection!r}")
        parts = clean.split("/")
        db_dir = self.root / Path(*parts[:-1]) if len(parts) > 1 else self.root
        db_path = (db_dir / f"{parts[-1]}.db").resolve()

        # Block path escape and symlinks
        if not str(db_path).startswith(str(self.root)):
            raise ValueError(f"Path escape blocked: {collection!r}")
        db_dir.mkdir(parents=True, exist_ok=True)
        if db_path.exists() and db_path.is_symlink():
            raise ValueError(f"Symlink blocked: {collection!r}")
        return db_path

    def _conn(self, collection: str) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path(collection)))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id         TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                created    TEXT DEFAULT (datetime('now')),
                updated_at TEXT,
                deleted    INTEGER DEFAULT 0,
                deviation  REAL DEFAULT 0.0,
                action     TEXT DEFAULT 'work_quiet'
            )
        """)
        _ensure_columns(conn)
        if _VEC_AVAILABLE:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS records_vec USING vec0(embedding float[768])"
            )
        return conn

    def _ts_cols(self, conn: sqlite3.Connection) -> list[str]:
        ts_names = {"created", "created_at", "updated_at", "modified_at"}
        all_cols = conn.execute("PRAGMA table_info(records)").fetchall()
        return [row[1] for row in all_cols if row[1] in ts_names]

    # ── Write ──────────────────────────────────────────────────────────────────

    def put(self, collection: str, record: dict, record_id: Optional[str] = None,
            deviation: float = 0.0) -> tuple:
        raw_id = record_id or record.get("_id") or record.get("id") or record.get("b17")
        if not raw_id:
            raise ValueError(
                f"record must have an 'id', '_id', or 'b17' field — got keys: {list(record.keys())}"
            )
        rid = _sanitize_id(str(raw_id))
        if not rid:
            raise ValueError(f"Invalid record ID after sanitization: {raw_id!r}")

        action = angular_action(deviation, self.rubric)
        data = json.dumps(record, default=str)
        if len(data) > MAX_RECORD_BYTES:
            raise ValueError(f"Record too large: {len(data)} bytes (max {MAX_RECORD_BYTES})")

        now = datetime.now().isoformat()
        vec = embed(data[:2000]) if _VEC_AVAILABLE else None

        with self._lock:
            conn = self._conn(collection)
            conn.execute(
                "INSERT OR REPLACE INTO records (id, data, updated_at, deviation, action) VALUES (?, ?, ?, ?, ?)",
                (rid, data, now, deviation, action)
            )
            conn.execute(
                "INSERT INTO audit_log (record_id, operation, deviation, action, timestamp) VALUES (?, 'create', ?, ?, ?)",
                (rid, deviation, action, now)
            )
            if _VEC_AVAILABLE:
                rowid = conn.execute(
                    "SELECT rowid FROM records WHERE id = ?", (rid,)
                ).fetchone()[0]
                if vec is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO records_vec(rowid, embedding) VALUES (?, ?)",
                        (rowid, sqlite_vec.serialize_float32(vec)),
                    )
                else:
                    conn.execute("DELETE FROM records_vec WHERE rowid = ?", (rowid,))
            conn.commit()
            conn.close()
        self._hebbian_auto_link(collection, record)
        return rid, action, []

    def _hebbian_auto_link(self, collection: str, new_record: dict) -> None:
        """Auto-write domain-based edges when a new atom is stored.

        Links new atom to up to 3 existing atoms with same domain in same collection.
        Only fires for hanuman/atoms/store and hanuman/skills/store.
        """
        if collection not in ("hanuman/atoms/store", "hanuman/skills/store"):
            return
        domain = new_record.get("domain")
        if not domain:
            return
        new_id = new_record.get("id")
        if not new_id:
            return

        try:
            existing = self.list(collection) or []
        except Exception:
            return

        peers = [
            a for a in existing
            if a.get("domain") == domain
            and a.get("id") != new_id
            and a.get("invalid_at") is None
        ][:3]

        now = datetime.now().isoformat()
        for peer in peers:
            edge_id = f"edge-{str(new_id)[:8]}-{str(peer['id'])[:8]}"
            try:
                self.put("hanuman/atoms/edges", {
                    "id": edge_id,
                    "source_id": new_id,
                    "target_id": peer["id"],
                    "weight": 0.1,
                    "co_activations": 0,
                    "last_activated": now,
                })
            except Exception:
                pass

    def _increment_edge_weight(self, source_id: str, target_id: str) -> None:
        """Increment weight and co_activations on edge between source and target."""
        try:
            edges = self.list("hanuman/atoms/edges") or []
        except Exception:
            return
        for edge in edges:
            if (edge.get("source_id") == source_id and edge.get("target_id") == target_id) \
                    or (edge.get("source_id") == target_id and edge.get("target_id") == source_id):
                edge["weight"] = round(float(edge.get("weight", 0.1)) + 0.05, 4)
                edge["co_activations"] = int(edge.get("co_activations", 0)) + 1
                edge["last_activated"] = datetime.now().isoformat()
                try:
                    self.update("hanuman/atoms/edges", edge["id"], edge)
                except Exception:
                    pass
                return

    def update(self, collection: str, record_id: str, record: dict,
               deviation: float = 0.0) -> tuple:
        rid = _sanitize_id(str(record_id))
        action = angular_action(deviation, self.rubric)
        now = datetime.now().isoformat()

        with self._lock:
            conn = self._conn(collection)
            existing = conn.execute(
                "SELECT data FROM records WHERE id = ? AND deleted = 0", (rid,)
            ).fetchone()
            if existing:
                merged = json.loads(existing["data"])
                merged.update(record)
                data = json.dumps(merged, default=str)
            else:
                data = json.dumps(record, default=str)

            if len(data) > MAX_RECORD_BYTES:
                conn.close()
                raise ValueError(f"Record too large: {len(data)} bytes (max {MAX_RECORD_BYTES})")

            conn.execute(
                "INSERT OR REPLACE INTO records (id, data, updated_at, deviation, action) VALUES (?, ?, ?, ?, ?)",
                (rid, data, now, deviation, action)
            )
            conn.execute(
                "INSERT INTO audit_log (record_id, operation, deviation, action, timestamp) VALUES (?, 'update', ?, ?, ?)",
                (rid, deviation, action, now)
            )
            if _VEC_AVAILABLE:
                rowid = conn.execute(
                    "SELECT rowid FROM records WHERE id = ?", (rid,)
                ).fetchone()[0]
                conn.execute("DELETE FROM records_vec WHERE rowid = ?", (rowid,))
                vec = embed(data[:2000])
                if vec is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO records_vec(rowid, embedding) VALUES (?, ?)",
                        (rowid, sqlite_vec.serialize_float32(vec)),
                    )
            conn.commit()
            conn.close()
        return rid, action, []

    # ── Read ───────────────────────────────────────────────────────────────────

    def get(self, collection: str, record_id: str) -> Optional[dict]:
        conn = self._conn(collection)
        row = conn.execute(
            "SELECT data FROM records WHERE id = ? AND deleted = 0",
            (_sanitize_id(str(record_id)),)
        ).fetchone()
        conn.close()
        return json.loads(row["data"]) if row else None

    def list(self, collection: str) -> list:
        conn = self._conn(collection)
        ts_cols = self._ts_cols(conn)
        order = f"ORDER BY {ts_cols[0]} DESC" if ts_cols else ""
        rows = conn.execute(
            f"SELECT data FROM records WHERE deleted = 0 {order}"
        ).fetchall()
        conn.close()
        return [json.loads(r["data"]) for r in rows]

    def all(self, collection: str) -> list:
        """Alias for list() — sap_mcp.py compatibility."""
        return self.list(collection)

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(self, collection: str, query: str, after: str | None = None) -> list:
        tokens = query.lower().split()
        if not tokens and not after:
            return self.list(collection)
        conn = self._conn(collection)
        rows = conn.execute(
            "SELECT data FROM records WHERE deleted = 0"
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            if tokens:
                text = row["data"].lower()
                if not all(t in text for t in tokens):
                    continue
            record = json.loads(row["data"])
            if after:
                ts = record.get("timestamp") or record.get("date") or ""
                if ts <= after:
                    continue
            results.append(record)
        return results

    def search_all(self, query: str) -> list:
        """Search across all collections."""
        results = []
        for collection in self.collections():
            results.extend(self.search(collection, query))
        return results

    def search_semantic(self, collection: str, query: str, limit: int = 20) -> list:
        if not _VEC_AVAILABLE:
            return self.search(collection, query)
        vec = embed(query)
        if vec is None:
            return self.search(collection, query)
        conn = self._conn(collection)
        vec_bytes = sqlite_vec.serialize_float32(vec)
        rows = conn.execute("""
            SELECT r.data FROM records r
            JOIN records_vec rv ON rv.rowid = r.rowid
            WHERE rv.embedding MATCH ? AND k = ?
            AND r.deleted = 0
        """, (vec_bytes, limit)).fetchall()
        conn.close()
        return [json.loads(row["data"]) for row in rows]

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete(self, collection: str, record_id: str) -> bool:
        """Soft delete — invisible to read/search but preserved in audit trail."""
        rid = _sanitize_id(str(record_id))
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._conn(collection)
            result = conn.execute(
                "UPDATE records SET deleted = 1, updated_at = ? WHERE id = ? AND deleted = 0",
                (now, rid)
            )
            if result.rowcount == 0:
                conn.close()
                return False
            conn.execute(
                "INSERT INTO audit_log (record_id, operation, timestamp) VALUES (?, 'delete', ?)",
                (rid, now)
            )
            conn.commit()
            conn.close()
        return True

    # ── Edges ──────────────────────────────────────────────────────────────────

    def add_edge(self, from_id: str, to_id: str, relation: str,
                 context: str = "") -> tuple:
        rid = f"{_sanitize_id(from_id)}__{_sanitize_id(relation)}__{_sanitize_id(to_id)}"
        record = {
            "id": rid,
            "from_id": from_id,
            "to_id": to_id,
            "relation": relation,
            "context": context,
        }
        return self.put("_graph/edges", record, record_id=rid)

    def edges_for(self, record_id: str) -> list:
        conn = self._conn("_graph/edges")
        rows = conn.execute(
            "SELECT data FROM records WHERE deleted = 0"
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            edge = json.loads(row["data"])
            if edge.get("from_id") == record_id or edge.get("to_id") == record_id:
                results.append(edge)
        return results

    # ── Audit ──────────────────────────────────────────────────────────────────

    def audit_log(self, collection: str, limit: int = 20) -> list:
        conn = self._conn(collection)
        rows = conn.execute(
            "SELECT record_id, operation, deviation, action, timestamp FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [{"record_id": r[0], "operation": r[1], "deviation": r[2],
                 "action": r[3], "timestamp": r[4]} for r in rows]

    # ── Collections / Stats ────────────────────────────────────────────────────

    def collections(self) -> list:
        result = []
        for db_file in self.root.rglob("*.db"):
            rel = db_file.relative_to(self.root)
            parts = list(rel.parts)
            parts[-1] = parts[-1].replace(".db", "")
            result.append("/".join(parts))
        return sorted(result)

    def stats(self) -> dict:
        result = {}
        for c in self.collections():
            try:
                conn = self._conn(c)
                row = conn.execute(
                    "SELECT COUNT(*) FROM records WHERE deleted = 0"
                ).fetchone()
                devs = [r[0] for r in conn.execute(
                    "SELECT deviation FROM records WHERE deleted = 0 AND deviation != 0.0"
                ).fetchall()]
                conn.close()
                traj_score, traj_label = net_trajectory(devs)
                result[c] = {"count": row[0] if row else 0,
                             "trajectory": traj_label,
                             "score": round(traj_score, 3)}
            except Exception:
                continue
        return result
