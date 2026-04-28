#!/usr/bin/env python3
"""
MIGR2 — Create sap schema in willow_19: installed_apps, app_connections, scope_path_matches().
b17: SAPS2
ΔΣ=42

Run: PYTHONPATH=/home/sean-campbell/github/willow-1.9 python3 scripts/migr2_sap_schema.py
Add --dry-run to print SQL without executing.
"""
import argparse
import os
import psycopg2

USER = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "sean-campbell"))

SQL = """
CREATE SCHEMA IF NOT EXISTS sap;

CREATE TABLE IF NOT EXISTS sap.installed_apps (
    app_id          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    version         TEXT NOT NULL DEFAULT '0.0.0',
    installed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent_id        TEXT,
    permissions     JSONB NOT NULL DEFAULT '[]'::jsonb,
    b17             TEXT,
    manifest_hash   TEXT
);

CREATE TABLE IF NOT EXISTS sap.app_connections (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_app_id     TEXT NOT NULL REFERENCES sap.installed_apps(app_id) ON DELETE CASCADE,
    to_app_id       TEXT NOT NULL REFERENCES sap.installed_apps(app_id) ON DELETE CASCADE,
    scope_path      TEXT NOT NULL,
    access          TEXT NOT NULL DEFAULT 'read' CHECK (access IN ('read')),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by      TEXT NOT NULL DEFAULT 'user',
    UNIQUE (from_app_id, to_app_id, scope_path)
);

CREATE OR REPLACE FUNCTION sap.scope_path_matches(collection TEXT, pattern TEXT)
RETURNS BOOLEAN AS $$
    SELECT collection LIKE replace(pattern, '{uuid}', '%');
$$ LANGUAGE SQL IMMUTABLE;
"""


def run(dry_run: bool = False) -> None:
    if dry_run:
        print("DRY RUN — SQL that would execute:")
        print(SQL)
        return

    conn = psycopg2.connect(dbname="willow_19", user=USER)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(SQL)
    conn.commit()
    conn.close()
    print("sap schema created: installed_apps, app_connections, scope_path_matches()")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
