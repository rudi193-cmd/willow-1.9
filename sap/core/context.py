"""
SAP Context Assembler
b17: A3979
ΔΣ=42

Assembles authorized context for delivery to a model's context window.
Pulls from Willow KB (Postgres + local store) scoped to the app's permitted data streams.

Only runs after gate.authorized() returns True.
The manifest's data_streams list defines what can be pulled.
"""

import json
import logging
from typing import Optional

from sap.core.gate import get_manifest, authorized, SAFE_ROOT

logger = logging.getLogger("sap.context")


def _pg_params() -> dict:
    """Unix socket by default. TCP only if WILLOW_PG_HOST is set. Mirrors pg_bridge._pg_params()."""
    import os
    params = {
        "dbname": os.environ.get("WILLOW_PG_DB", "willow"),
        "user": os.environ.get("WILLOW_PG_USER", "sean-campbell"),
    }
    host = os.environ.get("WILLOW_PG_HOST")
    if host:
        params["host"] = host
        params["port"] = int(os.environ.get("WILLOW_PG_PORT", "5432"))
        params["password"] = os.environ.get("WILLOW_PG_PASS", "")
    return params


def _resolve_b17_context(b17_ids: list, max_chars: int = 4000) -> str:
    """
    Resolve a list of b17 IDs to KB atom content.
    Queries Postgres for atoms whose summary contains 'b17: <ID>'.
    Returns concatenated title + summary, truncated to max_chars total.
    """
    if not b17_ids:
        return ""
    try:
        import psycopg2
        conn = psycopg2.connect(**_pg_params())
        conn.autocommit = True
        cur = conn.cursor()
        parts = []
        total = 0
        for b17 in b17_ids:
            cur.execute(
                "SELECT title, summary FROM knowledge WHERE summary LIKE %s ORDER BY id ASC LIMIT 1",
                (f"%b17: {b17}%",),
            )
            row = cur.fetchone()
            if not row:
                continue
            title, summary = row
            chunk = f"[{title}]\n{(summary or '')[:500]}"
            remaining = max_chars - total
            if remaining <= 0:
                break
            parts.append(chunk[:remaining])
            total += len(chunk[:remaining])
        cur.close()
        conn.close()
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning("b17 context resolution failed: %s", e)
        return ""


def assemble(
    app_id: str,
    query: str = "",
    max_chars: int = 4000,
    skip_cache: bool = False,
    category_filter: Optional[list] = None,
    cache_app_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Assemble context for an authorized app.

    Args:
        app_id:          SAFE app ID (gate check + manifest source).
        query:           Query string for KB search.
        max_chars:       Max total chars of KB atoms to include.
        skip_cache:      If True, do not inject the app's cache/context.json.
        category_filter: If provided, KB query is restricted to these categories.
        cache_app_id:    If provided, load cache from this app's folder instead.

    Returns None if not authorized.
    """
    if not authorized(app_id):
        logger.warning("Context assembly denied for unauthorized app: %s", app_id)
        return None

    manifest = get_manifest(app_id)
    if not manifest:
        return None

    permitted_streams = [s["id"] for s in manifest.get("data_streams", [])]

    # Load cached context if available (and not skipped)
    cache_data = None
    if not skip_cache:
        effective_cache_id = cache_app_id or app_id
        cache_path = SAFE_ROOT / effective_cache_id / "cache" / "context.json"
        if cache_path.exists():
            try:
                raw = cache_path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                if "b17" in parsed:
                    cache_data = _resolve_b17_context(parsed["b17"], max_chars)
                else:
                    cache_data = parsed.get("content", raw)
            except json.JSONDecodeError:
                cache_data = raw
            except Exception as e:
                logger.warning("Cache read failed for %s: %s", effective_cache_id, e)

    atoms = _query_willow(query, permitted_streams, max_chars, category_filter)

    return {
        "app_id": app_id,
        "query": query,
        "permitted_streams": permitted_streams,
        "atoms": atoms,
        "cache": cache_data,
        "manifest": manifest,
    }


def _query_willow(query: str, permitted_streams: list[str], max_chars: int, category_filter: Optional[list] = None) -> list[dict]:
    """
    Query Willow KB for atoms relevant to the query.
    Scoped to permitted data streams. Falls back gracefully if Postgres unavailable.
    """
    if not query:
        return []

    try:
        import psycopg2
        conn = psycopg2.connect(**_pg_params())
        conn.autocommit = True
        cur = conn.cursor()

        STOPWORDS = {"what", "does", "that", "this", "with", "from", "have",
                     "into", "they", "about", "there", "their", "which", "when",
                     "relationship", "between", "systems", "cannot"}
        words = [w.strip("?.,!") for w in query.split() if len(w) > 3]
        keywords = [w for w in words if w.lower() not in STOPWORDS][:5]

        if not keywords:
            keywords = [query[:40]]

        conditions = " OR ".join(
            ["(title ILIKE %s OR summary ILIKE %s)"] * len(keywords)
        )
        params = []
        for kw in keywords:
            params += [f"%{kw}%", f"%{kw}%"]

        category_clause = ""
        if category_filter:
            placeholders = ", ".join(["%s"] * len(category_filter))
            category_clause = f" AND category IN ({placeholders})"
            params += list(category_filter)

        cur.execute(
            f"""
            SELECT id, title, summary, source_type, category, created_at
            FROM knowledge
            WHERE ({conditions}){category_clause}
            ORDER BY created_at DESC
            LIMIT 10
            """,
            params,
        )
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()

        atoms = []
        total = 0
        for row in rows:
            entry = dict(zip(col_names, row))
            summary = str(entry.get("summary", "") or "")[:400]
            entry["_injectable"] = f"{entry.get('title', '')}: {summary}"
            chars = len(entry["_injectable"])
            if total + chars > max_chars:
                break
            atoms.append(entry)
            total += chars

        return atoms

    except Exception as e:
        logger.warning("Willow KB query failed (non-fatal): %s", e)
        return []
