#!/usr/bin/env python3
"""
willow_embed_backfill.py — Backfill NULL embeddings across Postgres tables.
b17: SEM01  ΔΣ=42

Run by Kart when queued via willow_embed_backfill task. Processes knowledge,
opus_atoms, and jeles_atoms in batches of 100 with 50ms sleep between batches.
Safe to interrupt and restart — re-queries NULL each pass.

Usage:
    python3 scripts/willow_embed_backfill.py [--limit N] [--dry-run]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.embedder import embed
from core.pg_bridge import PgBridge

BATCH_SIZE = 100
SLEEP_S = 0.05


def _backfill_table(pg: PgBridge, table: str, text_expr: str, dry_run: bool, limit: int) -> int:
    """Backfill NULL embeddings for one table. Returns count of rows processed."""
    processed = 0
    while True:
        with pg.conn.cursor() as cur:
            cur.execute(
                f"SELECT id, {text_expr} AS text FROM {table}"
                f" WHERE embedding IS NULL LIMIT %s",
                (BATCH_SIZE,),
            )
            rows = cur.fetchall()

        if not rows:
            break

        for row_id, text in rows:
            if limit and processed >= limit:
                return processed
            if dry_run:
                processed += 1
                continue
            vec = embed(text or "")
            if vec is None:
                print(f"  [{table}] {row_id}: Ollama unavailable — stopping", flush=True)
                return processed
            vec_str = str(vec)
            with pg.conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} SET embedding = %s::vector WHERE id = %s",
                    (vec_str, row_id),
                )
            pg.conn.commit()
            processed += 1

        print(f"  [{table}] +{len(rows)} embedded (total {processed})", flush=True)
        time.sleep(SLEEP_S)

    return processed


def main():
    parser = argparse.ArgumentParser(description="Backfill NULL embeddings")
    parser.add_argument("--limit", type=int, default=0, help="Max rows per table (0 = unlimited)")
    parser.add_argument("--dry-run", action="store_true", help="Count rows without writing")
    args = parser.parse_args()

    pg = PgBridge()

    tables = [
        ("knowledge",   "COALESCE(title, '') || ' ' || COALESCE(summary, '')"),
        ("opus_atoms",  "content"),
        ("jeles_atoms", "COALESCE(title, '') || ' ' || content"),
    ]

    total = 0
    for table, text_expr in tables:
        with pg.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE embedding IS NULL")
            null_count = cur.fetchone()[0]

        if null_count == 0:
            print(f"[{table}] 0 NULL embeddings — skipping", flush=True)
            continue

        print(f"[{table}] {null_count} NULL embeddings — backfilling...", flush=True)
        n = _backfill_table(pg, table, text_expr, args.dry_run, args.limit)
        total += n
        print(f"[{table}] done: {n} rows {'would be ' if args.dry_run else ''}processed", flush=True)

    print(f"\n[backfill] total: {total} rows processed", flush=True)


if __name__ == "__main__":
    main()
