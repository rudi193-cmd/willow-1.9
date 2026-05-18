#!/usr/bin/env python3
"""
Markdown docs indexer (Layer 3) — indexes all .md files in github/ and agents/
into public.knowledge (project='docs').
One atom per file. Short files (<3000 chars) = full content. Longer = first 3000 chars.
Streams files in batches of 100 to keep memory flat.
"""
import os
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    raise

DB_PARAMS = {"dbname": "willow_19", "user": "sean-campbell"}

ROOTS = [str(p) for p in [
    Path.home() / "github",
    Path.home() / "Ashokoa" / "agents",
] if p.exists()]

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".mypy_cache",
    "dist", "build", ".next", ".nuxt", "venv", ".venv",
}

MAX_CONTENT = 3000
BATCH_SIZE = 100


def should_skip_path(path: str) -> bool:
    return bool(set(Path(path).parts) & SKIP_DIRS)


def make_atom_id(filepath: str) -> str:
    return "D" + hashlib.sha1(filepath.encode()).hexdigest()[:7].upper()


def make_title(filepath: str) -> str:
    p = Path(filepath)
    try:
        return str(p.relative_to("/home/sean-campbell"))
    except ValueError:
        return p.name


def iter_md_files():
    for root in ROOTS:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(".md"):
                    yield os.path.join(dirpath, fn)


def get_existing_ids(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM public.knowledge WHERE project='docs'")
        return {row[0] for row in cur.fetchall()}


def flush_batch(cur, batch):
    psycopg2.extras.execute_values(cur, """
        INSERT INTO public.knowledge
            (id, project, valid_at, invalid_at, created_at, title, summary, content,
             source_type, category, embedding)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
    """, batch, template="(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)")


def main():
    print("[docs] Connecting to DB...", flush=True)
    conn = psycopg2.connect(**DB_PARAMS)
    existing_ids = get_existing_ids(conn)
    print(f"[docs] {len(existing_ids)} existing doc atoms (will skip). Scanning...", flush=True)

    now = datetime.now(timezone.utc)
    batch = []
    inserted = skipped = errors = scanned = 0

    with conn.cursor() as cur:
        for fp in iter_md_files():
            scanned += 1
            atom_id = make_atom_id(fp)
            if atom_id in existing_ids:
                skipped += 1
                if scanned % 500 == 0:
                    print(f"  scanned {scanned}, inserted {inserted}, skipped {skipped}...", flush=True)
                continue
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(MAX_CONTENT + 1)
                if len(text.strip()) < 20:
                    skipped += 1
                    continue
                summary = text[:MAX_CONTENT].strip()
            except Exception:
                errors += 1
                continue

            batch.append((
                atom_id, "docs", now, None, now,
                make_title(fp), summary,
                json.dumps({"file_path": fp}),
                "file", "reference", None,
            ))
            existing_ids.add(atom_id)

            if len(batch) >= BATCH_SIZE:
                flush_batch(cur, batch)
                conn.commit()
                inserted += len(batch)
                batch = []
                print(f"  scanned {scanned}, inserted {inserted}, skipped {skipped}...", flush=True)

        if batch:
            flush_batch(cur, batch)
            conn.commit()
            inserted += len(batch)

    conn.close()
    print(f"[docs] Done. scanned={scanned} inserted={inserted} skipped={skipped} errors={errors}", flush=True)


if __name__ == "__main__":
    main()
