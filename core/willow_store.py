#!/usr/bin/env python3
"""
willow_store.py — SOIL: SQLite-backed user store.
b17: SOIL1  ΔΣ=42

WILLOW_STORE_ROOT defaults to ~/.willow/store/ — never inside the repo.
Each collection is a SQLite database at {root}/{collection}.db.
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

_DEFAULT_STORE_ROOT = Path.home() / ".willow" / "store"


class WillowStore:
    def __init__(self, root: Optional[str] = None):
        env_root = os.environ.get("WILLOW_STORE_ROOT")
        self.root = Path(root or env_root or _DEFAULT_STORE_ROOT)
        self.root.mkdir(parents=True, exist_ok=True)

    def _db_path(self, collection: str) -> Path:
        parts = collection.split("/")
        db_dir = self.root / Path(*parts[:-1]) if len(parts) > 1 else self.root
        db_dir.mkdir(parents=True, exist_ok=True)
        return db_dir / f"{parts[-1]}.db"

    def _conn(self, collection: str) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path(collection)))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id      TEXT PRIMARY KEY,
                data    TEXT NOT NULL,
                created TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        return conn

    def put(self, collection: str, record: dict) -> str:
        record_id = record.get("_id") or record.get("id") or record.get("b17")
        if not record_id:
            raise ValueError("record must have _id, id, or b17 field")
        conn = self._conn(collection)
        conn.execute(
            "INSERT OR REPLACE INTO records (id, data) VALUES (?, ?)",
            (record_id, json.dumps(record))
        )
        conn.commit()
        conn.close()
        return record_id

    def get(self, collection: str, record_id: str) -> Optional[dict]:
        conn = self._conn(collection)
        row = conn.execute(
            "SELECT data FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        conn.close()
        return json.loads(row["data"]) if row else None

    def list(self, collection: str) -> list:
        conn = self._conn(collection)
        rows = conn.execute("SELECT data FROM records ORDER BY created DESC").fetchall()
        conn.close()
        return [json.loads(r["data"]) for r in rows]

    def search(self, collection: str, query: str) -> list:
        tokens = query.lower().split()
        if not tokens:
            return self.list(collection)
        conn = self._conn(collection)
        rows = conn.execute("SELECT data FROM records").fetchall()
        conn.close()
        results = []
        for row in rows:
            text = row["data"].lower()
            if all(t in text for t in tokens):
                results.append(json.loads(row["data"]))
        return results

    def delete(self, collection: str, record_id: str) -> bool:
        conn = self._conn(collection)
        cur = conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        conn.commit()
        conn.close()
        return cur.rowcount > 0

    def collections(self) -> list:
        result = []
        for db_file in self.root.rglob("*.db"):
            rel = db_file.relative_to(self.root)
            parts = list(rel.parts)
            parts[-1] = parts[-1].replace(".db", "")
            result.append("/".join(parts))
        return sorted(result)
