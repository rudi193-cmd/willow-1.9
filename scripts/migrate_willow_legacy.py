#!/usr/bin/env python3
"""
scripts/migrate_willow_legacy.py
Migrate knowledge atoms from legacy 'willow' Postgres DB into willow_19.
Uses direct psycopg2 — no PgBridge pool to avoid contention with MCP server.

Usage:
    PYTHONPATH=/home/sean-campbell/github/willow-1.9 python3 scripts/migrate_willow_legacy.py
    python3 scripts/migrate_willow_legacy.py --limit 500 --dry-run
"""
import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
import psycopg2.extras


BATCH = 1000


def _pg_kwargs(dbname: str) -> dict:
    return dict(
        dbname=dbname,
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
        host=os.environ.get("WILLOW_PG_HOST") or None,
        port=os.environ.get("WILLOW_PG_PORT") or None,
    )


def gen_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max atoms (0=all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    print("Connecting to legacy 'willow' DB...", flush=True)
    src = psycopg2.connect(**_pg_kwargs("willow"))
    src.set_session(readonly=True, autocommit=True)
    src_cur = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    src_cur.execute("SELECT COUNT(*) FROM knowledge")
    total = src_cur.fetchone()["count"]
    print(f"  source atoms: {total:,}", flush=True)

    if not args.dry_run:
        print("Connecting to willow_19...", flush=True)
        dst = psycopg2.connect(**_pg_kwargs("willow_19"))
        dst_cur = dst.cursor()
    else:
        dst = dst_cur = None
        print("DRY RUN — no writes.", flush=True)

    ingested = errors = skipped = 0
    offset = args.offset
    limit = args.limit or total

    INSERT = """
        INSERT INTO knowledge
            (id, project, valid_at, invalid_at, title, summary, content, source_type, category)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    """

    try:
        while (ingested + skipped + errors) < limit:
            batch_n = min(BATCH, limit - ingested - skipped - errors)
            src_cur.execute(
                "SELECT * FROM knowledge ORDER BY created_at ASC LIMIT %s OFFSET %s",
                (batch_n, offset),
            )
            rows = src_cur.fetchall()
            if not rows:
                break

            for row in rows:
                title   = (row.get("title") or "").strip()[:500]
                summary = (row.get("summary") or "").strip()
                if not title and not summary:
                    skipped += 1
                    offset += 1
                    continue

                summary  = summary[:4000]
                domain   = row.get("lattice_domain") or row.get("project") or "global"
                src_type = row.get("source_type") or "legacy"
                src_id   = str(row.get("source_id") or row.get("b17") or row.get("id") or "")
                category = row.get("category") or "general"
                valid_at = row.get("valid_at") or row.get("created_at") or datetime.now(timezone.utc)
                invalid_at = row.get("invalid_at")
                content  = psycopg2.extras.Json({"source_id": src_id, "legacy_id": str(row.get("id") or "")})

                if args.dry_run:
                    ingested += 1
                    offset += 1
                    continue

                try:
                    dst_cur.execute(INSERT, (
                        gen_id(), domain, valid_at, invalid_at,
                        title, summary, content, src_type, category,
                    ))
                    ingested += 1
                except Exception as e:
                    errors += 1
                    print(f"  ERR row {offset}: {e}", flush=True)
                offset += 1

            if not args.dry_run:
                dst.commit()

            done = ingested + skipped + errors
            pct = done / limit * 100
            print(f"  {done:,}/{limit:,} ({pct:.1f}%) — {ingested} ingested, {skipped} skipped, {errors} errors", flush=True)

    finally:
        src_cur.close()
        src.close()
        if dst:
            dst_cur.close()
            dst.close()

    print(f"\nDone. {ingested} ingested, {skipped} skipped, {errors} errors.", flush=True)


if __name__ == "__main__":
    main()
