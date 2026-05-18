#!/usr/bin/env python3
"""
Python codebase indexer (Layer 2) — indexes .py files from github/ and agents/
into public.knowledge (project='codebase').
Extracts: file path, module docstring, function/class signatures.
One atom per file. Skips generated, tiny, and test files.
Streams files in batches of 100 to keep memory flat.
"""
import os
import ast
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
    "migrations", "alembic",
}

MIN_LINES = 10
MAX_SUMMARY = 3000
BATCH_SIZE = 100


def make_atom_id(filepath: str) -> str:
    return "P" + hashlib.sha1(filepath.encode()).hexdigest()[:7].upper()


def make_title(filepath: str) -> str:
    try:
        return str(Path(filepath).relative_to("/home/sean-campbell"))
    except ValueError:
        return Path(filepath).name


def extract_signatures(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    parts = []
    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        parts.append(f"Module: {mod_doc[:300]}")

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ""
            args = [a.arg for a in node.args.args]
            sig = f"def {node.name}({', '.join(args)})"
            if doc:
                sig += f"  # {doc[:120]}"
            parts.append(sig)
        elif isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            methods = [n.name for n in ast.iter_child_nodes(node)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            sig = f"class {node.name}"
            if doc:
                sig += f"  # {doc[:120]}"
            if methods:
                sig += f"  [methods: {', '.join(methods[:8])}]"
            parts.append(sig)

    return "\n".join(parts)


def iter_py_files():
    for root in ROOTS:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def get_existing_ids(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM public.knowledge WHERE project='codebase'")
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
    print("[code] Connecting to DB...", flush=True)
    conn = psycopg2.connect(**DB_PARAMS)
    existing_ids = get_existing_ids(conn)
    print(f"[code] {len(existing_ids)} existing code atoms (will skip). Scanning...", flush=True)

    now = datetime.now(timezone.utc)
    batch = []
    inserted = skipped = errors = scanned = 0

    with conn.cursor() as cur:
        for fp in iter_py_files():
            scanned += 1
            atom_id = make_atom_id(fp)
            if atom_id in existing_ids:
                skipped += 1
                if scanned % 500 == 0:
                    print(f"  scanned {scanned}, inserted {inserted}, skipped {skipped}...", flush=True)
                continue

            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read(MAX_SUMMARY * 3)  # read enough for AST + summary
                lines = source.count("\n")
                if lines < MIN_LINES:
                    skipped += 1
                    continue

                sigs = extract_signatures(source)
                summary = (sigs[:MAX_SUMMARY] if sigs and len(sigs) > 50
                           else source[:MAX_SUMMARY].strip())
            except Exception:
                errors += 1
                continue

            batch.append((
                atom_id, "codebase", now, None, now,
                make_title(fp), summary,
                json.dumps({"file_path": fp, "lines": lines}),
                "file", "code", None,
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
    print(f"[code] Done. scanned={scanned} inserted={inserted} skipped={skipped} errors={errors}", flush=True)


if __name__ == "__main__":
    main()
