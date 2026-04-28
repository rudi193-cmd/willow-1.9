"""
sap/core/registry.py — App registry: register, connect, authorize.
b17: SAPS2
ΔΣ=42

Three entry points:
  register()             — upsert app into sap.installed_apps on first run
  request_connection()   — prompt user, insert into sap.app_connections on approval
  authorized_cross_app() — check sap.app_connections before cross-namespace store access
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("sap.registry")


def _pg_params() -> dict:
    params = {
        "dbname": os.environ.get("WILLOW_PG_DB", "willow_19"),
        "user": os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "sean-campbell")),
    }
    host = os.environ.get("WILLOW_PG_HOST")
    if host:
        params["host"] = host
        params["port"] = int(os.environ.get("WILLOW_PG_PORT", "5432"))
        params["password"] = os.environ.get("WILLOW_PG_PASS", "")
    return params


def _manifest_hash(manifest_path: Path) -> Optional[str]:
    try:
        data = manifest_path.read_bytes()
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def register(
    app_id: str,
    name: str,
    version: str,
    permissions: list[str],
    manifest_path: Optional[Path] = None,
    agent_id: Optional[str] = None,
    b17: Optional[str] = None,
) -> None:
    """
    Upsert app into sap.installed_apps. Idempotent — re-registers update version/hash.
    Call on every app startup to keep registry current.
    """
    mhash = _manifest_hash(manifest_path) if manifest_path else None
    try:
        conn = psycopg2.connect(**_pg_params())
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sap.installed_apps
                (app_id, name, version, permissions, agent_id, b17, manifest_hash, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, now())
            ON CONFLICT (app_id) DO UPDATE SET
                name          = EXCLUDED.name,
                version       = EXCLUDED.version,
                permissions   = EXCLUDED.permissions,
                agent_id      = EXCLUDED.agent_id,
                b17           = EXCLUDED.b17,
                manifest_hash = EXCLUDED.manifest_hash,
                updated_at    = now()
            """,
            (app_id, name, version, json.dumps(permissions), agent_id, b17, mhash),
        )
        conn.commit()
        conn.close()
        logger.info("SAP registry: registered %s v%s", app_id, version)
    except Exception as e:
        logger.error("SAP registry: register failed for %s: %s", app_id, e)
        raise


def request_connection(
    from_app_id: str,
    to_app_id: str,
    scope_path: str,
    purpose: str,
    access: str = "read",
    granted_by: str = "user",
    non_interactive: bool = False,
) -> bool:
    """
    Prompt the user for cross-app connection approval, then write to sap.app_connections.

    Returns True if connection was granted (or already exists), False if denied.
    Set non_interactive=True to skip the prompt and auto-deny (for background processes).
    """
    try:
        conn = psycopg2.connect(**_pg_params())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM sap.app_connections
            WHERE from_app_id = %s AND to_app_id = %s AND scope_path = %s
            """,
            (from_app_id, to_app_id, scope_path),
        )
        if cur.fetchone():
            conn.close()
            return True
        conn.close()
    except Exception as e:
        logger.error("SAP registry: connection check failed: %s", e)
        return False

    if non_interactive:
        logger.info("SAP registry: non-interactive mode — denying connection %s→%s", from_app_id, to_app_id)
        return False

    print(f"\n{from_app_id} wants to read your {to_app_id} data.")
    print(f"  Purpose: \"{purpose}\"")
    print(f"  Scope:   {scope_path} ({access}-only)")
    answer = input("\nAllow? [y/N] ").strip().lower()
    if answer != "y":
        print("Denied.")
        return False

    try:
        conn = psycopg2.connect(**_pg_params())
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sap.app_connections
                (from_app_id, to_app_id, scope_path, access, granted_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (from_app_id, to_app_id, scope_path) DO NOTHING
            """,
            (from_app_id, to_app_id, scope_path, access, granted_by),
        )
        conn.commit()
        conn.close()
        logger.info("SAP registry: connection granted %s→%s scope=%s", from_app_id, to_app_id, scope_path)
        return True
    except Exception as e:
        logger.error("SAP registry: connection insert failed: %s", e)
        return False


def authorized_cross_app(
    requesting_app_id: str,
    target_collection: str,
    access: str = "read",
) -> bool:
    """
    Returns True if requesting_app_id has an approved connection to target_collection.
    Checks sap.app_connections — no match = denied. Own namespace always allowed.
    """
    target_app_id = _parse_app_id_from_collection(target_collection)
    if target_app_id is None or target_app_id == requesting_app_id:
        return True

    try:
        conn = psycopg2.connect(**_pg_params())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM sap.app_connections
            WHERE from_app_id = %s
              AND to_app_id   = %s
              AND access      = %s
              AND sap.scope_path_matches(%s, scope_path)
            """,
            (requesting_app_id, target_app_id, access, target_collection),
        )
        result = cur.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error("SAP registry: authorized_cross_app failed: %s", e)
        return False


def _parse_app_id_from_collection(collection: str) -> Optional[str]:
    """
    Extract app_id from a collection path.
    Pattern: user-<uuid>/<app_id>/... or <app_id>/...
    Returns None if collection is ambiguous or empty.
    """
    if not collection:
        return None
    parts = collection.strip("/").split("/")
    if len(parts) >= 2 and parts[0].startswith("user-"):
        return parts[1]
    if len(parts) >= 1:
        return parts[0]
    return None


def list_installed() -> list[dict]:
    """Return all rows from sap.installed_apps as dicts."""
    try:
        conn = psycopg2.connect(**_pg_params())
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT app_id, name, version, installed_at, updated_at, agent_id, permissions, b17 "
            "FROM sap.installed_apps ORDER BY name"
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.error("SAP registry: list_installed failed: %s", e)
        return []
