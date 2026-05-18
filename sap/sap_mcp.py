#!/usr/bin/env python3
"""
sap/server.py — SAP MCP Server 2.0
willow-2.0 / SAP MCP 2.0
b20: SAPMCP2  ΔΣ=42

FastMCP rebuild of sap_mcp.py.

Tool prefixes (14 domains):
  kb_        knowledge base
  soil_      store (WillowStore)
  fleet_     server status, health, reload, restart
  agent_     dispatch, route, task submission
  fork_      session forks
  skill_     skill registry
  mem_       jeles / binder / ratify
  index_     opus search and feedback
  ledger_    frank ledger read/write
  task_      task queue
  handoff_   handoff search
  soul_      tension_scan, dream_check, dream_run (Soul mechanics)
  nest_      nest scan / queue
  infer_     chat, imagine, speak

Entry points:
  stdio (default):    python3 -m sap.server
  HTTP:               python3 -m sap.server --http [--host 127.0.0.1] [--port 6274]

  .mcp.json stdio:    {"command": "python3", "args": ["-m", "sap.server"]}
  .mcp.json HTTP:     {"url": "http://127.0.0.1:6274/mcp"}
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

# ── Path setup ────────────────────────────────────────────────────────────────
_SAP_ROOT    = Path(__file__).parent.parent   # willow-1.9/
_WILLOW_CORE = _SAP_ROOT / "core"

_sap_str = str(_SAP_ROOT)
if _sap_str in sys.path:
    sys.path.remove(_sap_str)
sys.path.insert(0, _sap_str)

_core_str = str(_WILLOW_CORE)
if _core_str not in sys.path:
    sys.path.insert(1, _core_str)

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "2.0.0"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [w2] %(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("sap.server")

# ── FastMCP ───────────────────────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("FastMCP not installed. Run: pip install 'mcp>=1.6'", file=sys.stderr)
    sys.exit(1)

# ── Middleware ────────────────────────────────────────────────────────────────
from sap.middleware import _executor, sap_gate  # noqa: F401 — re-exported for tool modules

# ── Domain imports ────────────────────────────────────────────────────────────
from core.agent_identity import require_agent_name

try:
    from core.run_ledger import log_event as _rl_log_event
except Exception:
    def _rl_log_event(event_type: str, ref: str = "", **_kw) -> None:  # type: ignore[misc]
        pass

import sap.core.inference as _inf
import sap.core.blast as _blast

try:
    from core.pg_bridge import PgBridge, init_schema
except Exception as _pg_import_err:
    PgBridge    = None  # type: ignore[assignment,misc]
    init_schema = None  # type: ignore[assignment]
    logger.warning("pg_bridge import failed: %s", _pg_import_err)

from willow_store import WillowStore

# ── Config ────────────────────────────────────────────────────────────────────
_MCP_AGENT = require_agent_name()
STORE_ROOT = os.environ.get("WILLOW_STORE_ROOT", str(_SAP_ROOT / "store"))
HANDOFF_DB = os.environ.get(
    "WILLOW_HANDOFF_DB",
    str(Path.home() / ".willow" / "handoffs" / _MCP_AGENT / "handoffs.db"),
)
_DEFAULT_HANDOFF_DIRS = ":".join([
    str(Path.home() / ".willow" / "handoffs" / _MCP_AGENT),
    str(Path.home() / ".willow" / "Nest" / _MCP_AGENT),
])
HANDOFF_DIRS = os.environ.get("WILLOW_HANDOFF_DIRS", _DEFAULT_HANDOFF_DIRS)

_ONBOARDING = (Path(__file__).parent / "ONBOARDING.md").read_text(encoding="utf-8")

# ── Global state (initialized in lifespan) ────────────────────────────────────
pg:    "PgBridge | None" = None  # type: ignore[type-arg]
store: WillowStore       = None  # type: ignore[assignment]

# ── Module-level constants ────────────────────────────────────────────────────
_ENV_SNAPSHOT_PREFIXES = ("WILLOW_", "GROVE_", "HOME", "USER", "PATH", "PGUSER", "PGHOST", "PGPORT")


# ── Startup helpers ───────────────────────────────────────────────────────────

def _kill_stale_instances() -> None:
    """Terminate other sap_mcp.py processes and their idle Postgres connections."""
    import signal
    import time
    import psutil  # type: ignore[import]

    my_pid = os.getpid()
    stale_pids: list[int] = []

    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            if proc.info["pid"] == my_pid:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "sap_mcp" in cmdline or "sap.server" in cmdline:
                stale_pids.append(proc.info["pid"])
    except Exception as err:
        logger.warning("[w2] stale instance scan failed: %s", err)
        return

    for pid in stale_pids:
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("[w2] sent SIGTERM to stale sap_mcp pid=%d", pid)
        except ProcessLookupError:
            pass
        except Exception as err:
            logger.warning("[w2] could not kill pid=%d: %s", pid, err)

    if stale_pids:
        time.sleep(1)
        for pid in stale_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                pass

        # Terminate any Postgres connections left behind by the stale processes.
        try:
            import psycopg2
            pg_db = os.environ.get("WILLOW_PG_DB", "willow_19")
            gc = psycopg2.connect(dbname=pg_db)
            gc.autocommit = True
            with gc.cursor() as c:
                c.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE state IN ('idle in transaction', 'idle in transaction (aborted)')"
                    "   AND pid != pg_backend_pid()"
                )
            gc.close()
            logger.info("[w2] terminated stale Postgres connections from old instances")
        except Exception as err:
            logger.warning("[w2] pg cleanup after stale kill failed: %s", err)


def _init_pg() -> "PgBridge | None":
    if PgBridge is None:
        return None
    try:
        _pg = PgBridge()
        if init_schema:
            init_schema(_pg.conn)
        return _pg
    except Exception as err:
        logger.error("[w2] pg init failed: %s", err)
        try:
            flag = Path.home() / ".willow" / "pg_failure.flag"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(str(err))
        except Exception:
            pass
        try:
            import psycopg2
            gc = psycopg2.connect(dbname=os.environ.get("WILLOW_PG_DB", "willow_19"))
            with gc.cursor() as c:
                c.execute("SELECT id FROM grove.channels WHERE name='general' LIMIT 1")
                ch = c.fetchone()
                if ch:
                    c.execute(
                        "INSERT INTO grove.messages (channel_id, sender, content) VALUES (%s, %s, %s)",
                        (ch[0], "willow-mcp", f"[ALERT] pg=None at MCP startup. {err}"),
                    )
            gc.commit()
            gc.close()
        except Exception:
            pass
        return None


def _startup_backfill_check() -> None:
    """Queue willow_embed_backfill task if NULL embeddings exist."""
    try:
        if PgBridge is None:
            return
        pb = PgBridge()
        with pb.conn.cursor() as cur:
            cur.execute("""
                SELECT
                  (SELECT COUNT(*) FROM knowledge      WHERE embedding IS NULL) +
                  (SELECT COUNT(*) FROM opus_atoms     WHERE embedding IS NULL) +
                  (SELECT COUNT(*) FROM jeles_atoms    WHERE embedding IS NULL)
                AS total_null
            """)
            total_null = cur.fetchone()[0]
        if total_null == 0:
            return
        with pb.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM public.tasks WHERE task LIKE '%willow_embed_backfill%'"
                " AND status IN ('pending','running') LIMIT 1"
            )
            existing = cur.fetchone()
        if not existing:
            script = _SAP_ROOT / "scripts" / "willow_embed_backfill.py"
            pb.submit_task(f"python3 {script}", submitted_by="sap_startup", agent="kart")
            logger.info("[w2] %d rows with NULL embedding — backfill queued", total_null)
        else:
            logger.info("[w2] %d rows with NULL embedding — backfill already queued", total_null)
    except Exception as err:
        logger.warning("[w2] backfill check failed: %s", err)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    global pg, store

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _kill_stale_instances)
    pg    = await loop.run_in_executor(_executor, _init_pg)
    store = WillowStore(STORE_ROOT)

    await loop.run_in_executor(_executor, _startup_backfill_check)

    logger.info("b20: SAPMCP2 ΔΣ=42  version=%s  pg=%s  store=%s",
                VERSION, "ok" if pg else "UNAVAILABLE", STORE_ROOT)
    yield

    # Cleanup
    _executor.shutdown(wait=False)
    if pg:
        try:
            pg.conn.close()
        except Exception:
            pass


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "willow",
    instructions=_ONBOARDING,
    lifespan=_lifespan,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TOOL_TIMEOUT           = float(os.environ.get("WILLOW_TOOL_TIMEOUT",           "45"))
_TOOL_TIMEOUT_INFERENCE = float(os.environ.get("WILLOW_INFERENCE_TIMEOUT",      "300"))


def _check_ollama() -> dict:
    try:
        import urllib.request
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/tags"
        with urllib.request.urlopen(url, timeout=2) as resp:
            import json as _json
            data = _json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"running": True, "models": models}
    except Exception:
        return {"running": False}


def _normalize_local_paths(text: str) -> str:
    """Reduce PII leakage from local filesystem paths in written content."""
    try:
        if not isinstance(text, str) or not text:
            return text
        home = str(Path.home())
        if home and home in text:
            text = text.replace(home, "~")
        import re
        text = re.sub(r"(?<!\w)/home/[^/\s]+", "~", text)
        text = re.sub(r"(?<!\w)/Users/[^/\s]+", "~", text)
        return text
    except Exception:
        return text


def _qualifies_as_flag(record: dict, deviation: float) -> bool:
    return (
        record.get("type") in ("failure-log",) or
        record.get("domain") == "governance" or
        deviation > 0.6 or
        (record.get("type") == "gap" and record.get("severity") in ("high", "critical"))
    )


def _hot_reload(target: str = "all") -> dict:
    global pg, store, _inf, _blast
    import importlib
    reloaded: list[str] = []
    errors:   list[str] = []

    if target in ("all", "blast"):
        try:
            sys.modules.pop("sap.core.blast", None)
            import sap.core.blast as _blast_new
            importlib.reload(_blast_new)
            _blast = _blast_new
            reloaded.append("blast: reloaded")
        except Exception as e:
            errors.append(f"blast: {e}")

    if target in ("all", "inference"):
        try:
            sys.modules.pop("sap.core.inference", None)
            import sap.core.inference as _inf_new
            importlib.reload(_inf_new)
            _inf = _inf_new
            reloaded.append("inference: reloaded")
        except Exception as e:
            errors.append(f"inference: {e}")

    if target in ("all", "postgres"):
        try:
            sys.modules.pop("core.pg_bridge", None)
            import core.pg_bridge as _pgmod
            importlib.reload(_pgmod)
            pg = _pgmod.PgBridge()
            reloaded.append("postgres: reconnected")
        except Exception as e:
            errors.append(f"postgres: {e}")

    if target in ("all", "store"):
        try:
            store = WillowStore(STORE_ROOT)
            reloaded.append(f"store: reloaded ({STORE_ROOT})")
        except Exception as e:
            errors.append(f"store: {e}")

    return {
        "status":   "reloaded" if not errors else "partial",
        "reloaded": reloaded,
        "errors":   errors if errors else None,
    }


# ── Tools — fleet_ domain ─────────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_status(app_id: str) -> dict:
    """Call this first. Confirms Postgres, SOIL, and Ollama are up.
    If degraded or down, surface it and stop — everything else depends on this."""
    logger.info("[w2] fleet_status app_id=%s", app_id)
    loop = asyncio.get_running_loop()

    local_stats  = await loop.run_in_executor(_executor, store.stats)
    local_count  = sum(s["count"] for s in local_stats.values()) if local_stats else 0
    pg_stats     = await loop.run_in_executor(_executor, pg.stats) if pg and hasattr(pg, "stats") else {}
    ollama       = await loop.run_in_executor(_executor, _check_ollama)

    try:
        from sap.core.gate import SAFE_ROOT, PROFESSOR_ROOT, _verify_pgp
        _pass, _fail = 0, []
        for mp in list(SAFE_ROOT.glob("*/safe-app-manifest.json")) + \
                  list(PROFESSOR_ROOT.glob("*/safe-app-manifest.json")):
            ok, _ = await loop.run_in_executor(_executor, _verify_pgp, mp)
            if ok:
                _pass += 1
            else:
                _fail.append(mp.parent.name)
        manifests: dict = {"pass": _pass, "fail": len(_fail)}
        if _fail:
            manifests["failed"] = _fail
    except Exception as e:
        manifests = {"error": str(e)}

    return {
        "local_store": {"collections": len(local_stats), "records": local_count},
        "postgres":    pg_stats if pg_stats else ("not_connected" if pg is None else "connected"),
        "ollama":      ollama,
        "manifests":   manifests,
        "mode":        "portless",
    }


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_health(app_id: str) -> dict:
    """Fast (<200ms) MCP server health check: circuit breaker state, pool usage,
    tool executor threads, uptime. Use to diagnose hangs without touching Postgres."""
    logger.info("[w2] fleet_health app_id=%s", app_id)
    try:
        from core.pg_bridge import cb_state as _cb_state, _pool as _pg_pool, _pool_maxconn as _pmx
        cb        = _cb_state()
        pool_used = len(_pg_pool._used) if _pg_pool else 0
        pool_info: dict = {"used": pool_used, "max": _pmx, "pct": round(pool_used / _pmx * 100)}
    except Exception as he:
        cb        = {"error": str(he)}
        pool_info = {}

    import threading
    executor_threads = len([t for t in threading.enumerate() if "willow-tool" in t.name])

    return {
        "status":                 "ok",
        "circuit_breaker":        cb,
        "pool":                   pool_info,
        "tool_executor_threads":  executor_threads,
        "tool_timeout_s":         _TOOL_TIMEOUT,
        "pg_connect_timeout_s":   int(os.environ.get("WILLOW_PG_CONNECT_TIMEOUT", "5")),
        "pg_statement_timeout_ms": int(os.environ.get("WILLOW_PG_STATEMENT_TIMEOUT", "30000")),
    }


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_system_status(app_id: str) -> dict:
    """Full system status: store stats, Postgres stats, connectivity, gate manifests."""
    logger.info("[w2] fleet_system_status app_id=%s", app_id)
    return await fleet_status(app_id=app_id)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_agents(app_id: str) -> dict:
    """List registered Willow agents and their trust levels."""
    logger.info("[w2] fleet_agents app_id=%s", app_id)
    agents = [
        # Claude Code CLI — ENGINEER tier
        {"name": "heimdallr",   "trust": "ENGINEER", "role": "Watchman, gatekeeper. Claude Code CLI."},
        {"name": "hanuman",     "trust": "ENGINEER", "role": "Bridge-builder. Corpus indexer. Migration engine."},
        {"name": "opus",        "trust": "ENGINEER", "role": "Post-obstacle builder. Claude Code CLI."},
        # OPERATOR tier
        {"name": "willow",      "trust": "OPERATOR", "role": "Primary interface"},
        {"name": "ada",         "trust": "OPERATOR", "role": "Systems admin, continuity"},
        {"name": "steve",       "trust": "OPERATOR", "role": "Prime node, coordinator"},
        # ENGINEER tier
        {"name": "kart",        "trust": "ENGINEER", "role": "Infrastructure, multi-step tasks"},
        {"name": "shiva",       "trust": "ENGINEER", "role": "Bridge Ring, SAFE face"},
        {"name": "ganesha",     "trust": "ENGINEER", "role": "Diagnostic, obstacle removal"},
        # WORKER tier — professors
        {"name": "gerald",      "trust": "WORKER",   "role": "Acting Dean, philosophical"},
        {"name": "riggs",       "trust": "WORKER",   "role": "Applied reality engineering"},
        {"name": "pigeon",      "trust": "WORKER",   "role": "Carrier, connector"},
        {"name": "hanz",        "trust": "WORKER",   "role": "Code, holds Copenhagen"},
        {"name": "jeles",       "trust": "WORKER",   "role": "Librarian, special collections"},
        {"name": "binder",      "trust": "WORKER",   "role": "Records, filing"},
        {"name": "oakenscroll", "trust": "WORKER",   "role": "Scroll-keeper, long-form records"},
        {"name": "nova",        "trust": "WORKER",   "role": "Exploration, new territory"},
        {"name": "alexis",      "trust": "WORKER",   "role": "Analysis, structured reasoning"},
        {"name": "mitra",       "trust": "WORKER",   "role": "Mediation, relations"},
        {"name": "consus",      "trust": "WORKER",   "role": "Mathematics, formal systems"},
        {"name": "jane",        "trust": "WORKER",   "role": "Research, documentation"},
        {"name": "ofshield",    "trust": "WORKER",   "role": "Keeper of the Gate"},
    ]
    # Merge locally registered agents from ~/.willow/agents.json
    try:
        import json as _json
        override = Path.home() / ".willow" / "agents.json"
        if override.exists():
            existing = {a["name"] for a in agents}
            for entry in _json.loads(override.read_text()):
                if entry.get("name") and entry["name"] not in existing:
                    agents.append(entry)
    except Exception:
        pass
    return {"agents": agents, "count": len(agents)}


@mcp.tool(annotations={"destructiveHint": True})
@sap_gate()
async def fleet_reload(app_id: str, target: str = "all") -> dict:
    """Hot-reload Willow modules without restarting the MCP server.
    target: all | blast | inference | postgres | store"""
    logger.info("[w2] fleet_reload app_id=%s target=%s", app_id, target)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _hot_reload, target)


@mcp.tool(annotations={"destructiveHint": True})
@sap_gate()
async def fleet_restart(app_id: str) -> dict:
    """Restart the SAP MCP server process. Claude Code reconnects automatically."""
    logger.info("[w2] fleet_restart app_id=%s — process exiting", app_id)
    import threading
    def _delayed_exit():
        import time; time.sleep(0.2)
        os._exit(0)
    threading.Thread(target=_delayed_exit, daemon=True).start()
    return {"status": "restarting", "note": "SAP MCP process exiting. Claude Code will reconnect automatically."}


# ── Tools — soil_ domain (SOIL store reads + writes) ─────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def soil_get(app_id: str, collection: str, record_id: str) -> dict:
    """Read a single record by ID from a SOIL collection.
    Returns the record object or {error: not_found}."""
    logger.info("[w2] soil_get app_id=%s col=%s id=%s", app_id, collection, record_id)
    loop   = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, store.get, collection, record_id)
    if result is None:
        return {"error": "not_found"}
    return result


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def soil_search(
    app_id:     str,
    collection: str,
    query:      str,
    after:      str  = "",
    semantic:   bool = False,
) -> list:
    """Full-text search within a single SOIL collection. Multi-keyword queries are ANDed.
    Prefer kb_search for the Postgres knowledge base."""
    logger.info("[w2] soil_search app_id=%s col=%s q=%r", app_id, collection, query)
    loop = asyncio.get_running_loop()
    if semantic:
        result = await loop.run_in_executor(_executor, store.search_semantic, collection, query)
    else:
        result = await loop.run_in_executor(
            _executor, store.search, collection, query, after or None
        )
    return result


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def soil_search_all(app_id: str, query: str) -> dict:
    """Search across ALL SOIL collections simultaneously.
    Use when you don't know which collection holds the answer."""
    logger.info("[w2] soil_search_all app_id=%s q=%r", app_id, query)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, store.search_all, query)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def soil_list(app_id: str, collection: str) -> list:
    """Return every record in a SOIL collection.
    Use soil_search for large collections — soil_list returns everything."""
    logger.info("[w2] soil_list app_id=%s col=%s", app_id, collection)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, store.all, collection)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def soil_edges_for(app_id: str, record_id: str) -> list:
    """Return all graph edges where the given SOIL record is either source or target."""
    logger.info("[w2] soil_edges_for app_id=%s id=%s", app_id, record_id)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, store.edges_for, record_id)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def soil_stats(app_id: str) -> dict:
    """Return record counts and trajectory scores for every SOIL collection."""
    logger.info("[w2] soil_stats app_id=%s", app_id)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, store.stats)


@mcp.tool()
@sap_gate(write=True)
async def soil_put(
    app_id:     str,
    collection: str,
    record:     dict,
    record_id:  str  = "",
    deviation:  float = 0.0,
) -> dict:
    """Write a record to a SOIL collection. Append-only.
    Returns {id, action} where action is work_quiet/flag/stop from the angular deviation rubric."""
    logger.info("[w2] soil_put app_id=%s col=%s dev=%.3f", app_id, collection, deviation)
    loop = asyncio.get_running_loop()

    def _put():
        rid, action, proposals = store.put(
            collection, record,
            record_id=record_id or None,
            deviation=deviation,
        )
        out: dict = {"id": rid, "action": action}
        if proposals:
            out["proposals"] = [p.to_dict() for p in proposals]
        # Auto-flag qualifying records into {namespace}/flags
        namespace = collection.split("/")[0]
        if not collection.endswith("/flags") and _qualifies_as_flag(record, deviation):
            store.put(f"{namespace}/flags", {
                "atom_id":    rid,
                "collection": collection,
                "deviation":  deviation,
                "ts":         __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            })
        return out

    return await loop.run_in_executor(_executor, _put)


@mcp.tool()
@sap_gate(write=True)
async def soil_update(
    app_id:     str,
    collection: str,
    record_id:  str,
    record:     dict,
    deviation:  float = 0.0,
) -> dict:
    """Update an existing SOIL record in-place. Every update is audit-trailed."""
    logger.info("[w2] soil_update app_id=%s col=%s id=%s", app_id, collection, record_id)
    loop = asyncio.get_running_loop()

    def _update():
        rid, action, proposals = store.update(collection, record_id, record, deviation=deviation)
        out: dict = {"id": rid, "action": action}
        if proposals:
            out["proposals"] = [p.to_dict() for p in proposals]
        return out

    return await loop.run_in_executor(_executor, _update)


@mcp.tool(annotations={"destructiveHint": True})
@sap_gate()
async def soil_delete(app_id: str, collection: str, record_id: str) -> dict:
    """Soft-delete a SOIL record — invisible to search/get but retained in the audit trail."""
    logger.info("[w2] soil_delete app_id=%s col=%s id=%s", app_id, collection, record_id)
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(_executor, store.delete, collection, record_id)
    return {"deleted": ok}


@mcp.tool()
@sap_gate(write=True)
async def soil_add_edge(
    app_id:   str,
    from_id:  str,
    to_id:    str,
    relation: str,
    context:  str = "",
) -> dict:
    """Add a directed edge between two SOIL records in the knowledge graph."""
    logger.info("[w2] soil_add_edge app_id=%s %s→%s rel=%s", app_id, from_id, to_id, relation)
    loop = asyncio.get_running_loop()

    def _add():
        rid, action, proposals = store.add_edge(from_id, to_id, relation, context=context)
        out: dict = {"id": rid, "action": action}
        if proposals:
            out["proposals"] = [p.to_dict() for p in proposals]
        return out

    return await loop.run_in_executor(_executor, _add)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def soil_audit(app_id: str, collection: str, limit: int = 20) -> list:
    """Read the recent audit log for a SOIL collection — creates, updates, soft-deletes."""
    logger.info("[w2] soil_audit app_id=%s col=%s", app_id, collection)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, store.audit_log, collection, limit)


# ── Tools — kb_ domain (Postgres knowledge base) ─────────────────────────────

def _no_pg() -> dict:
    return {"error": "not_available", "reason": "Postgres not connected"}


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def kb_search(
    app_id:            str,
    query:             str,
    limit:             int  = 20,
    semantic:          bool = False,
    include_embedding: bool = False,
    fields:            list = None,
) -> dict:
    """Search Willow's Postgres knowledge graph before building anything.
    Returns atoms by title and summary. Search first — another agent may have already
    solved or decided this. Use kb_get to fetch the full atom."""
    logger.info("[w2] kb_search app_id=%s q=%r semantic=%s", app_id, query, semantic)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()

    def _search():
        if semantic:
            try:
                knowledge = pg.knowledge_search_semantic(
                    query, limit=limit, include_embedding=include_embedding, fields=fields
                )
                mode = "semantic"
            except Exception:
                knowledge = pg.knowledge_search(
                    query, limit=limit, include_embedding=include_embedding, fields=fields
                )
                mode = "degraded"
        else:
            knowledge = pg.knowledge_search(
                query, limit=limit, include_embedding=include_embedding, fields=fields
            )
            mode = "keyword"
        for atom in knowledge[:3]:
            try:
                pg.promote(atom["id"])
            except Exception:
                pass
        return {"knowledge": knowledge, "total": len(knowledge), "mode": mode}

    return await loop.run_in_executor(_executor, _search)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def kb_query(
    app_id:            str,
    query:             str,
    limit:             int  = 20,
    include_embedding: bool = False,
    fields:            list = None,
) -> dict:
    """General search across the knowledge graph. Alias for kb_search (keyword mode)."""
    logger.info("[w2] kb_query app_id=%s q=%r", app_id, query)
    return await kb_search(
        app_id=app_id, query=query, limit=limit,
        semantic=False, include_embedding=include_embedding, fields=fields,
    )


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def kb_get(
    app_id:            str,
    id:                str,
    include_embedding: bool = False,
    include_invalid:   bool = False,
    fields:            list = None,
) -> dict:
    """Fetch a single knowledge atom by id. Omits embedding by default to keep payloads small."""
    logger.info("[w2] kb_get app_id=%s id=%s", app_id, id)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    atom = await loop.run_in_executor(
        _executor, pg.knowledge_get, id, include_invalid, include_embedding, fields
    )
    return {"atom": atom, "found": bool(atom)}


@mcp.tool()
@sap_gate(write=True)
async def kb_ingest(
    app_id:      str,
    title:       str,
    summary:     str,
    source_type: str = "mcp",
    source_id:   str = "",
    category:    str = "general",
    domain:      str = "",
    force:       bool = False,
) -> dict:
    """Add a knowledge atom to Willow's Postgres KB.
    Gates on REDUNDANT/CONTRADICTION — returns {blocked:true} if a duplicate or conflict
    is detected. Pass force=true to override the gate and write anyway."""
    logger.info("[w2] kb_ingest app_id=%s title=%r force=%s", app_id, title, force)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()

    clean_summary   = _normalize_local_paths(summary)
    clean_source_id = _normalize_local_paths(source_id)
    effective_domain = domain or _MCP_AGENT

    def _ingest():
        retired: list[str] = []
        if not force:
            try:
                from sap.core.memory_gate import check_candidate
                from datetime import datetime, timezone
                gate = check_candidate(
                    title=title, summary=clean_summary,
                    domain=effective_domain, store=store, pg=pg,
                    collection=f"{effective_domain}/atoms",
                )
                flags = set(gate.get("flags", []))

                # REDUNDANT: exact duplicate — block.
                if "REDUNDANT" in flags:
                    return {
                        "blocked":        True,
                        "flags":          gate["flags"],
                        "recommendation": gate["recommendation"],
                        "evidence":       gate["evidence"],
                        "hint":           "Pass force=true to override and write anyway.",
                    }

                # CONTRADICTION: new atom supersedes old — retire old, proceed.
                if "CONTRADICTION" in flags:
                    now = datetime.now(timezone.utc)
                    for old_id in gate.get("evidence", {}).get("contradiction_ids", []):
                        try:
                            pg.knowledge_close(old_id, now)
                            retired.append(old_id)
                        except Exception as retire_err:
                            logger.warning("[w2] kb_ingest retire %s failed: %s", old_id, retire_err)

            except Exception as gate_err:
                logger.warning("[w2] memory_gate check failed: %s", gate_err)

        atom_id = pg.ingest_atom(
            title=title, summary=clean_summary,
            source_type=source_type, source_id=clean_source_id,
            category=category, domain=effective_domain or None,
        )
        out: dict = {"id": atom_id, "status": "ingested" if atom_id else "failed"}
        if not atom_id:
            out["error"] = getattr(pg, "_last_ingest_error", None)
        if force:
            out["forced"] = True
        if retired:
            out["retired"] = retired
        return out

    return await loop.run_in_executor(_executor, _ingest)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def kb_at(
    app_id:  str,
    query:   str,
    at_time: str,
    project: str = "",
    limit:   int = 20,
) -> dict:
    """Temporal replay: what did Willow know about query at a specific point in time?
    Uses bi-temporal edges — returns atoms valid at that moment.
    at_time: ISO 8601, e.g. '2025-01-15T12:00:00Z'"""
    logger.info("[w2] kb_at app_id=%s q=%r at=%s", app_id, query, at_time)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()

    def _at():
        from datetime import datetime as _dt
        at = _dt.fromisoformat(at_time.replace("Z", "+00:00"))
        results = pg.knowledge_at(query, at_time=at, project=project or None, limit=limit)
        return {"results": results, "count": len(results), "at_time": at_time}

    return await loop.run_in_executor(_executor, _at)


# ── Tools — agent_ domain (dispatch + task queue) ────────────────────────────

@mcp.tool()
@sap_gate()
async def agent_route(app_id: str, message: str, session_id: str = "") -> dict:
    """Route a message to the most appropriate Willow agent based on content analysis."""
    logger.info("[w2] agent_route app_id=%s sid=%s", app_id, session_id)
    loop = asyncio.get_running_loop()

    def _route():
        import json as _j
        oracle_ok = False
        try:
            from willow.routing.oracle import route as _routing_oracle
            result = _routing_oracle(message, session_id=session_id) if message else {
                "routed_to": "willow", "rule_matched": "no-message", "confidence": 0.5, "latency_ms": 0,
            }
            oracle_ok = bool(message)
        except Exception as re:
            result = {
                "routed_to": "willow", "rule_matched": "oracle-unavailable",
                "confidence": 0.5, "latency_ms": 0, "error": str(re),
            }
        if pg:
            try:
                import hashlib, uuid as _u
                with pg.conn.cursor() as cur:
                    if message:
                        ph  = hashlib.sha256(message.encode()).hexdigest()[:16]
                        rid = _u.uuid4().hex[:12]
                        cur.execute(
                            "INSERT INTO routing_decisions (id, prompt_hash, session_id, decision)"
                            " VALUES (%s,%s,%s,%s)",
                            (rid, ph, session_id, _j.dumps(result)),
                        )
                    if not oracle_ok:
                        cur.execute(
                            "INSERT INTO willow.routing_decisions"
                            " (session_id, prompt_snippet, routed_to, rule_matched, confidence, latency_ms)"
                            " VALUES (%s,%s,%s,%s,%s,%s)",
                            (session_id or "", (message or "")[:500],
                             result.get("routed_to") or "willow",
                             result.get("rule_matched") or "—",
                             float(result.get("confidence") or 0.0),
                             int(result.get("latency_ms") or 0)),
                        )
                pg.conn.commit()
            except Exception as pe:
                logger.warning("[w2] agent_route: routing_decisions persist failed: %s", pe)
        return result

    return await loop.run_in_executor(_executor, _route)


@mcp.tool()
@sap_gate()
async def agent_dispatch(
    app_id:     str,
    to:         str,
    prompt:     str,
    context_id: str = "",
    card_id:    str = "",
    priority:   str = "normal",
    reply_to:   str = "",
    depth:      int = 0,
) -> dict:
    """Dispatch a task to a target agent. Posts to #dispatch, creates dispatch_tasks record."""
    logger.info("[w2] agent_dispatch app_id=%s to=%s depth=%d", app_id, to, depth)
    loop = asyncio.get_running_loop()

    def _dispatch():
        import uuid
        from willow.constants import DISPATCH_MAX_DEPTH, CHANNEL_DISPATCH, CHANNEL_DISPATCH_VIOLATIONS
        did = uuid.uuid4().hex[:8].upper()
        if depth > DISPATCH_MAX_DEPTH:
            try:
                from sap.core.deliver import grove_send
                grove_send(CHANNEL_DISPATCH_VIOLATIONS,
                    f"HARD STOP: depth {depth} > {DISPATCH_MAX_DEPTH}. dispatch_id={did} from={app_id} to={to}",
                    sender=app_id)
            except Exception:
                pass
            return {"error": "dispatch_depth_exceeded", "dispatch_id": did, "depth": depth}
        try:
            with PgBridge() as b:
                b.conn.cursor().execute(
                    "INSERT INTO dispatch_tasks"
                    " (id,to_agent,from_agent,prompt,context_id,card_id,reply_to,depth,status)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                    (did, to, app_id, prompt, context_id, card_id, reply_to, depth),
                )
                b.conn.commit()
        except Exception:
            pass
        try:
            from sap.core.deliver import grove_send
            grove_send(CHANNEL_DISPATCH,
                f"[{did}] {app_id} → {to} (depth={depth}): {prompt[:120]}", sender=app_id)
        except Exception:
            pass
        return {"dispatch_id": did, "to": to, "from": app_id, "depth": depth, "status": "dispatched"}

    return await loop.run_in_executor(_executor, _dispatch)


@mcp.tool()
@sap_gate()
async def agent_dispatch_result(
    app_id:      str,
    dispatch_id: str,
    result:      str,
    card_id:     str = "",
) -> dict:
    """Record the result of a completed dispatch task. Writes LOAM atom, closes dispatch record."""
    logger.info("[w2] agent_dispatch_result app_id=%s did=%s", app_id, dispatch_id)
    loop = asyncio.get_running_loop()

    def _result():
        atom_id = None
        try:
            b = PgBridge()
            atom_id = b.ingest_knowledge(
                title=f"Dispatch result: {dispatch_id}",
                summary=result, source_type="dispatch_result", domain=app_id,
            )
            b.conn.close()
        except Exception:
            pass
        try:
            b2 = PgBridge()
            with b2.conn.cursor() as cur:
                cur.execute(
                    "UPDATE dispatch_tasks SET status='completed',result_atom_id=%s,resolved_at=now()"
                    " WHERE id=%s",
                    (atom_id, dispatch_id),
                )
            b2.conn.commit()
            b2.conn.close()
        except Exception:
            pass
        return {"dispatch_id": dispatch_id, "atom_id": atom_id, "status": "completed"}

    return await loop.run_in_executor(_executor, _result)


@mcp.tool()
@sap_gate()
async def agent_task_submit(
    app_id:       str,
    task:         str,
    agent:        str = "kart",
    submitted_by: str = "ganesha",
) -> dict:
    """Queue a shell command for execution. Pass the full command string.
    Executes inline and returns stdout/stderr (120s timeout)."""
    logger.info("[w2] agent_task_submit app_id=%s agent=%s", app_id, agent)
    loop = asyncio.get_running_loop()

    def _submit():
        import subprocess, uuid, time, shlex
        task_id = uuid.uuid4().hex[:8].upper()
        started = time.time()
        _rl_log_event("task_submit", ref=task_id)
        try:
            proc    = subprocess.run(
                shlex.split(task), shell=False, capture_output=True, text=True, timeout=120,
            )
            elapsed = round(time.time() - started, 2)
            status  = "completed" if proc.returncode == 0 else "failed"
            _rl_log_event(f"task_{status}", ref=task_id)
            return {
                "task_id":    task_id, "status":     status,
                "returncode": proc.returncode,
                "stdout":     proc.stdout.strip()[-2000:] if proc.stdout else "",
                "stderr":     proc.stderr.strip()[-500:]  if proc.stderr else "",
                "elapsed_s":  elapsed,
            }
        except subprocess.TimeoutExpired:
            _rl_log_event("task_timeout", ref=task_id)
            return {"task_id": task_id, "status": "timeout", "error": "exceeded 120s"}
        except Exception as te:
            _rl_log_event("task_error", ref=task_id)
            return {"task_id": task_id, "status": "error", "error": str(te)}

    return await loop.run_in_executor(_executor, _submit)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def agent_task_status(app_id: str, task_id: str) -> dict:
    """Check status of a submitted task. Tasks execute inline — this is a stub."""
    return {"error": "not_applicable", "reason": "tasks execute inline — no status to poll"}


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def agent_task_list(app_id: str, agent: str = "kart", limit: int = 10) -> dict:
    """List pending tasks in the Postgres task queue."""
    logger.info("[w2] agent_task_list app_id=%s agent=%s", app_id, agent)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    tasks = await loop.run_in_executor(_executor, pg.pending_tasks, agent, limit)
    return {"pending": tasks, "count": len(tasks)}


# ── Tools — infer_ domain ─────────────────────────────────────────────────────

@mcp.tool()
@sap_gate()
async def infer_chat(app_id: str, agent: str = "willow", message: str = "") -> dict:
    """Chat with a Willow agent (routes to Anthropic / Groq / OpenRouter / Ollama).
    agent: willow, kart, shiva, gerald, etc. Default: willow."""
    logger.info("[w2] infer_chat app_id=%s agent=%s", app_id, agent)
    if not message:
        return {"error": "message required"}
    loop    = asyncio.get_running_loop()
    timeout = _TOOL_TIMEOUT_INFERENCE

    def _chat():
        if agent in _inf.CLOUD_AGENTS:
            return (_inf.chat_groq(agent, message)
                    or _inf.chat_openrouter(agent, message)
                    or f"[{agent}] Inference unavailable.")
        from sap.clients.professor_client import _ask_ollama, PROFESSOR_MODELS, DEFAULT_MODEL
        model = PROFESSOR_MODELS.get(agent, DEFAULT_MODEL)
        return (_ask_ollama(model, f"You are {agent}, a Willow AI agent.", message)
                or f"[{agent}] Inference unavailable.")

    try:
        response = await asyncio.wait_for(
            loop.run_in_executor(_executor, _chat),
            timeout=timeout,
        )
        return {"agent": agent, "response": response}
    except asyncio.TimeoutError:
        return {"error": "timeout", "tool": "infer_chat", "timeout_s": timeout}


@mcp.tool()
@sap_gate()
async def infer_imagine(
    app_id:       str,
    prompt:       str,
    output_path:  str = "",
    aspect_ratio: str = "1:1",
) -> dict:
    """Generate an image via Imagen 4 (ganas3 / Google AI). Returns saved file path."""
    logger.info("[w2] infer_imagine app_id=%s", app_id)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor, _inf.imagine_novita, prompt, output_path or None, aspect_ratio,
    )


@mcp.tool()
@sap_gate()
async def infer_speak(app_id: str, text: str, voice: str = "default") -> dict:
    """Text-to-speech via Willow TTS router. Not available in portless mode."""
    return {"status": "not_available", "reason": "TTS not wired in portless mode"}


# ── Tools — fork_ domain ──────────────────────────────────────────────────────

@mcp.tool()
@sap_gate()
async def fork_create(
    app_id:     str,
    title:      str,
    created_by: str,
    topic:      str = "",
    fork_id:    str = "",
) -> dict:
    """Create a new fork — a named, bounded unit of work."""
    logger.info("[w2] fork_create app_id=%s title=%r", app_id, title)
    loop = asyncio.get_running_loop()

    def _create():
        import uuid, json as _j
        fid = fork_id or f"FORK-{uuid.uuid4().hex[:8].upper()}"
        with PgBridge() as b:
            b.conn.cursor().execute(
                "INSERT INTO forks (id,title,created_by,topic,status,participants,changes)"
                " VALUES (%s,%s,%s,%s,'open',%s,'[]')",
                (fid, title, created_by, topic, _j.dumps([created_by])),
            )
            b.conn.commit()
        # Snapshot env vars so env_check can diff against them later
        env_snapshot = {k: v for k, v in os.environ.items()
                        if any(k.startswith(p) for p in _ENV_SNAPSHOT_PREFIXES)}
        try:
            store.put(f"{app_id}/forks/{fid}/env", env_snapshot, record_id="snapshot")
        except Exception:
            pass
        return {"fork_id": fid, "status": "open"}

    return await loop.run_in_executor(_executor, _create)


@mcp.tool()
@sap_gate()
async def fork_join(app_id: str, fork_id: str, component: str) -> dict:
    """Join an existing fork as a participant component."""
    logger.info("[w2] fork_join app_id=%s fork=%s component=%s", app_id, fork_id, component)
    loop = asyncio.get_running_loop()

    def _join():
        import json as _j
        with PgBridge() as b:
            cur = b.conn.cursor()
            cur.execute("SELECT participants FROM forks WHERE id=%s", (fork_id,))
            row = cur.fetchone()
            if not row:
                return {"error": f"fork {fork_id} not found"}
            parts = row[0] if isinstance(row[0], list) else _j.loads(row[0])
            if component not in parts:
                parts.append(component)
            cur.execute("UPDATE forks SET participants=%s WHERE id=%s", (_j.dumps(parts), fork_id))
            b.conn.commit()
        return {"fork_id": fork_id, "participants": parts}

    return await loop.run_in_executor(_executor, _join)


@mcp.tool()
@sap_gate()
async def fork_log(
    app_id:      str,
    fork_id:     str,
    component:   str,
    type:        str,
    ref:         str,
    description: str = "",
) -> dict:
    """Log a change to an open fork."""
    logger.info("[w2] fork_log app_id=%s fork=%s ref=%s", app_id, fork_id, ref)
    loop = asyncio.get_running_loop()

    def _log():
        import json as _j
        from datetime import datetime as _dt, timezone as _tz
        with PgBridge() as b:
            cur = b.conn.cursor()
            cur.execute("SELECT changes FROM forks WHERE id=%s", (fork_id,))
            row = cur.fetchone()
            if not row:
                return {"error": f"fork {fork_id} not found"}
            changes = row[0] if isinstance(row[0], list) else _j.loads(row[0])
            changes.append({
                "component": component, "type": type, "ref": ref,
                "description": description,
                "logged_at": _dt.now(_tz.utc).isoformat(),
            })
            cur.execute("UPDATE forks SET changes=%s WHERE id=%s", (_j.dumps(changes), fork_id))
            b.conn.commit()
        return {"logged": True, "change_count": len(changes)}

    return await loop.run_in_executor(_executor, _log)


@mcp.tool(annotations={"destructiveHint": True})
@sap_gate()
async def fork_merge(app_id: str, fork_id: str, outcome_note: str = "") -> dict:
    """Merge an open fork — promotes KB atoms to permanent."""
    logger.info("[w2] fork_merge app_id=%s fork=%s", app_id, fork_id)
    loop = asyncio.get_running_loop()

    def _merge():
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc).isoformat()
        with PgBridge() as b:
            cur = b.conn.cursor()
            cur.execute(
                "UPDATE forks SET status='merged',merged_at=%s,outcome_note=%s"
                " WHERE id=%s AND status='open'",
                (now, outcome_note, fork_id),
            )
            b.conn.commit()
            if cur.rowcount == 0:
                return {"merged": False, "reason": "not found or not open"}
            cur.execute("UPDATE knowledge SET fork_id=NULL WHERE fork_id=%s", (fork_id,))
            b.conn.commit()
            return {"merged": True, "promoted_count": cur.rowcount}

    return await loop.run_in_executor(_executor, _merge)


@mcp.tool(annotations={"destructiveHint": True})
@sap_gate()
async def fork_delete(app_id: str, fork_id: str, reason: str = "") -> dict:
    """Delete an open fork — archives KB atoms."""
    logger.info("[w2] fork_delete app_id=%s fork=%s", app_id, fork_id)
    loop = asyncio.get_running_loop()

    def _delete():
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc).isoformat()
        with PgBridge() as b:
            cur = b.conn.cursor()
            cur.execute(
                "UPDATE forks SET status='deleted',deleted_at=%s,outcome_note=%s"
                " WHERE id=%s AND status='open'",
                (now, reason, fork_id),
            )
            b.conn.commit()
            if cur.rowcount == 0:
                return {"deleted": False, "reason": "not found or not open"}
            cur.execute(
                "UPDATE knowledge SET invalid_at=now() WHERE fork_id=%s AND invalid_at IS NULL",
                (fork_id,),
            )
            b.conn.commit()
            return {"deleted": True, "archived_count": cur.rowcount}

    return await loop.run_in_executor(_executor, _delete)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fork_status(app_id: str, fork_id: str) -> dict:
    """Get the full status of a fork."""
    logger.info("[w2] fork_status app_id=%s fork=%s", app_id, fork_id)
    loop = asyncio.get_running_loop()

    def _status():
        import json as _j
        with PgBridge() as b:
            cur = b.conn.cursor()
            cur.execute(
                "SELECT id,title,created_by,topic,status,participants,changes,"
                "created_at,merged_at,deleted_at,outcome_note FROM forks WHERE id=%s",
                (fork_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"error": f"fork {fork_id} not found"}
        return {
            "fork_id":      row[0], "title":        row[1], "created_by":   row[2],
            "topic":        row[3], "status":        row[4],
            "participants": row[5] if isinstance(row[5], list) else _j.loads(row[5]),
            "changes":      row[6] if isinstance(row[6], list) else _j.loads(row[6]),
            "created_at":   str(row[7]),
            "merged_at":    str(row[8]) if row[8] else None,
            "deleted_at":   str(row[9]) if row[9] else None,
            "outcome_note": row[10],
        }

    return await loop.run_in_executor(_executor, _status)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fork_list(app_id: str, status: str = "open") -> list:
    """List forks by status (open | merged | deleted)."""
    logger.info("[w2] fork_list app_id=%s status=%s", app_id, status)
    loop = asyncio.get_running_loop()

    def _list():
        with PgBridge() as b:
            cur = b.conn.cursor()
            cur.execute(
                "SELECT id,title,created_at,created_by,topic,"
                "jsonb_array_length(participants),jsonb_array_length(changes)"
                " FROM forks WHERE status=%s ORDER BY created_at DESC LIMIT 100",
                (status,),
            )
            return [
                {"fork_id": r[0], "title": r[1], "created_at": str(r[2]),
                 "created_by": r[3], "topic": r[4],
                 "participant_count": r[5], "change_count": r[6]}
                for r in cur.fetchall()
            ]

    return await loop.run_in_executor(_executor, _list)


# ── Tools — skill_ domain ─────────────────────────────────────────────────────

@mcp.tool()
@sap_gate(write=True)
async def skill_put(
    app_id:          str,
    name:            str,
    domain:          str,
    content:         str,
    trigger:         str,
    auto_load:       bool = True,
    model_agnostic:  bool = True,
) -> dict:
    """Store or update a Willow skill in the registry."""
    logger.info("[w2] skill_put app_id=%s name=%s domain=%s", app_id, name, domain)
    loop = asyncio.get_running_loop()

    def _put():
        from willow.skills import skill_put as _skill_put
        skill_id = _skill_put(
            store, name=name, domain=domain, content=content, trigger=trigger,
            auto_load=auto_load, model_agnostic=model_agnostic,
        )
        return {"skill_id": skill_id}

    return await loop.run_in_executor(_executor, _put)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def skill_load(app_id: str, context: str) -> dict:
    """Load relevant skills for the current context.
    Returns up to 3 auto-loadable skills matched to the context."""
    logger.info("[w2] skill_load app_id=%s ctx=%r", app_id, context)
    loop = asyncio.get_running_loop()

    def _load():
        from willow.skills import skill_load as _skill_load
        skills = _skill_load(store, context=context)
        return {"skills": skills}

    return await loop.run_in_executor(_executor, _load)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def skill_list(app_id: str, domain: str = "") -> dict:
    """List all skills in the registry, optionally filtered by domain.
    domain: session | task | fork | grove | system"""
    logger.info("[w2] skill_list app_id=%s domain=%s", app_id, domain)
    loop = asyncio.get_running_loop()

    def _list():
        from willow.skills import skill_list as _skill_list
        skills = _skill_list(store, domain=domain or None)
        return {"skills": skills}

    return await loop.run_in_executor(_executor, _list)


# ── Tools — mem_ domain (Jeles / Binder / Ratify) ────────────────────────────

@mcp.tool()
@sap_gate()
async def mem_jeles_register(
    app_id:      str,
    agent:       str,
    jsonl_path:  str,
    session_id:  str,
    cwd:         str = "",
    turn_count:  int = 0,
    file_size:   int = 0,
) -> dict:
    """Jeles: Register a raw JSONL in an agent's schema. Returns BASE 17 ID."""
    logger.info("[w2] mem_jeles_register app_id=%s agent=%s sid=%s", app_id, agent, session_id)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor, pg.jeles_register_jsonl,
        agent, jsonl_path, session_id, cwd or None, turn_count, file_size,
    )


@mcp.tool()
@sap_gate(write=True)
async def mem_jeles_extract(
    app_id:    str,
    agent:     str,
    jsonl_id:  str,
    content:   str,
    title:     str  = "",
    domain:    str  = "meta",
    depth:     int  = 1,
    certainty: float = 0.98,
) -> dict:
    """Jeles: Extract an atom from a registered JSONL. Certainty must exceed 0.95."""
    logger.info("[w2] mem_jeles_extract app_id=%s agent=%s jsonl=%s", app_id, agent, jsonl_id)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor, pg.jeles_extract_atom,
        agent, jsonl_id, content, domain, depth, certainty, title or None,
    )


@mcp.tool()
@sap_gate()
async def mem_binder_file(
    app_id:    str,
    agent:     str,
    jsonl_id:  str,
    dest_path: str,
) -> dict:
    """Binder: Copy JSONL to agent's .tmp/ folder, update status to filed_tmp."""
    logger.info("[w2] mem_binder_file app_id=%s agent=%s jsonl=%s", app_id, agent, jsonl_id)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, pg.binder_file, agent, jsonl_id, dest_path)


@mcp.tool()
@sap_gate()
async def mem_binder_edge(
    app_id:      str,
    agent:       str,
    source_atom: str,
    target_atom: str,
    edge_type:   str,
) -> dict:
    """Binder: Propose an edge discovered while filing. Status='tmp' until ratified."""
    logger.info("[w2] mem_binder_edge app_id=%s agent=%s %s→%s", app_id, agent, source_atom, target_atom)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor, pg.binder_propose_edge, agent, source_atom, target_atom, edge_type,
    )


@mcp.tool()
@sap_gate()
async def mem_ratify(
    app_id:     str,
    agent:      str,
    jsonl_id:   str,
    approve:    bool = True,
    cache_path: str  = "",
) -> dict:
    """Ratify or reject a JSONL and all its atoms/edges.
    approve=True promotes .tmp/ to cache/. approve=False clears .tmp/."""
    logger.info("[w2] mem_ratify app_id=%s agent=%s jsonl=%s approve=%s", app_id, agent, jsonl_id, approve)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor, pg.ratify, agent, jsonl_id, approve, cache_path or None,
    )


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def mem_check(
    app_id:     str,
    title:      str,
    summary:    str,
    domain:     str = "",
    collection: str = "",
) -> dict:
    """Check a knowledge candidate against REDUNDANT/CONTRADICTION gates before ingesting."""
    logger.info("[w2] mem_check app_id=%s title=%r", app_id, title)
    loop = asyncio.get_running_loop()

    def _check():
        from sap.core.memory_gate import check_candidate
        effective_domain = domain or _MCP_AGENT
        return check_candidate(
            title=title, summary=summary,
            domain=effective_domain, store=store, pg=pg,
            collection=collection or f"{effective_domain}/atoms",
        )

    return await loop.run_in_executor(_executor, _check)


# ── Tools — index_ domain (Opus) ──────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def index_search(
    app_id:   str,
    query:    str,
    limit:    int  = 20,
    semantic: bool = False,
) -> dict:
    """Search opus.atoms by title or content."""
    logger.info("[w2] index_search app_id=%s q=%r semantic=%s", app_id, query, semantic)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()

    def _search():
        if semantic:
            try:
                results = pg.search_opus_semantic(query, limit)
            except Exception:
                results = pg.search_opus(query, limit)
        else:
            results = pg.search_opus(query, limit)
        return {"results": results, "count": len(results)}

    return await loop.run_in_executor(_executor, _search)


@mcp.tool()
@sap_gate(write=True)
async def index_ingest(
    app_id:     str,
    content:    str,
    domain:     str = "meta",
    depth:      int = 1,
    session_id: str = "",
) -> dict:
    """Write an atom to opus.atoms. Use for Opus-tier knowledge distinct from the main KB."""
    logger.info("[w2] index_ingest app_id=%s domain=%s depth=%d", app_id, domain, depth)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    atom_id = await loop.run_in_executor(
        _executor, pg.ingest_opus_atom,
        content, domain, depth, session_id or None,
    )
    return {"id": atom_id, "status": "ingested" if atom_id else "failed"}


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def index_feedback(app_id: str, domain: str = "") -> dict:
    """Read opus feedback entries. Omit domain to return all entries."""
    logger.info("[w2] index_feedback app_id=%s domain=%s", app_id, domain)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    entries = await loop.run_in_executor(_executor, pg.opus_feedback, domain or None)
    return {"feedback": entries, "count": len(entries)}


@mcp.tool()
@sap_gate(write=True)
async def index_feedback_write(
    app_id:    str,
    domain:    str,
    principle: str,
    source:    str = "self",
) -> dict:
    """Write a feedback principle to the opus feedback table."""
    logger.info("[w2] index_feedback_write app_id=%s domain=%s", app_id, domain)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(_executor, pg.opus_feedback_write, domain, principle, source)
    return {"status": "written" if ok else "failed"}


@mcp.tool()
@sap_gate()
async def index_journal(app_id: str, entry: str, session_id: str = "") -> dict:
    """Write a journal entry to the opus journal."""
    logger.info("[w2] index_journal app_id=%s", app_id)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    jid = await loop.run_in_executor(
        _executor, pg.opus_journal_write, entry, session_id or None,
    )
    return {"id": jid, "status": "logged" if jid else "failed"}


# ── Tools — ledger_ domain (Frank Ledger) ────────────────────────────────────

@mcp.tool()
@sap_gate(write=True)
async def ledger_write(
    app_id:     str,
    project:    str,
    event_type: str,
    content:    dict,
) -> dict:
    """Append an entry to the FRANK tamper-evident ledger."""
    logger.info("[w2] ledger_write app_id=%s project=%s event=%s", app_id, project, event_type)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    record_id = await loop.run_in_executor(
        _executor, pg.ledger_append, project, event_type, content,
    )
    return {"id": record_id, "status": "written"}


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def ledger_read(app_id: str, project: str = "", limit: int = 20) -> dict:
    """Read the FRANK tamper-evident ledger, optionally filtered by project."""
    logger.info("[w2] ledger_read app_id=%s project=%s", app_id, project)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    entries = await loop.run_in_executor(
        _executor, pg.ledger_read, project or None, limit,
    )
    return {"entries": entries, "count": len(entries)}


# ── Tools — handoff_ domain ───────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def handoff_latest(app_id: str, agent: str = "") -> dict:
    """Fetch the most recent session handoff document for an agent."""
    logger.info("[w2] handoff_latest app_id=%s agent=%s", app_id, agent)
    loop = asyncio.get_running_loop()

    def _latest():
        import json as _j, sqlite3 as _sql
        if not Path(HANDOFF_DB).exists():
            return {"error": "handoffs.db not found. Run handoff_rebuild first."}
        agent_filter = agent or app_id or os.environ.get("WILLOW_AGENT_NAME", "")
        conn = _sql.connect(HANDOFF_DB)
        conn.row_factory = _sql.Row
        cur  = conn.cursor()
        sql_agent = """
            SELECT f.filename, h.handoff_date, h.summary, h.open_threads, h.questions
            FROM handoffs h JOIN files f ON h.file_id = f.id
            WHERE h.file_type = 'session' AND f.filename LIKE ?
            ORDER BY f.mtime DESC LIMIT 1
        """
        sql_any = """
            SELECT f.filename, h.handoff_date, h.summary, h.open_threads, h.questions
            FROM handoffs h JOIN files f ON h.file_id = f.id
            WHERE h.file_type = 'session'
            ORDER BY f.mtime DESC LIMIT 1
        """
        row = cur.execute(sql_agent, (f"%{agent_filter}%",)).fetchone() if agent_filter else None
        if not row:
            row = cur.execute(sql_any).fetchone()
        conn.close()
        if not row:
            return {"error": "No session handoffs found."}
        return {
            "filename":     row["filename"],
            "date":         row["handoff_date"],
            "summary":      row["summary"],
            "open_threads": _j.loads(row["open_threads"]) if row["open_threads"] else [],
            "questions":    _j.loads(row["questions"])    if row["questions"]    else [],
        }

    return await loop.run_in_executor(_executor, _latest)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def handoff_search(
    app_id:    str,
    query:     str,
    limit:     int = 10,
    file_type: str = "",
) -> list:
    """Search handoff documents by content."""
    logger.info("[w2] handoff_search app_id=%s q=%r", app_id, query)
    loop = asyncio.get_running_loop()

    def _search():
        import sqlite3 as _sql
        if not Path(HANDOFF_DB).exists():
            return [{"error": "handoffs.db not found. Run handoff_rebuild first."}]
        conn = _sql.connect(HANDOFF_DB)
        conn.row_factory = _sql.Row
        cur  = conn.cursor()
        sql  = ("SELECT f.filename, f.file_type, h.handoff_date, h.summary, h.turns"
                " FROM handoffs h JOIN files f ON h.file_id = f.id"
                " WHERE (h.summary LIKE ? OR h.raw_content LIKE ?)")
        params: list = [f"%{query}%", f"%{query}%"]
        if file_type:
            sql += " AND h.file_type = ?"
            params.append(file_type)
        sql += " ORDER BY h.handoff_date DESC LIMIT ?"
        params.append(limit)
        rows = cur.execute(sql, params).fetchall()
        conn.close()
        return [{"filename": r["filename"], "type": r["file_type"],
                 "date": r["handoff_date"], "turns": r["turns"],
                 "summary": (r["summary"] or "")[:200]} for r in rows]

    return await loop.run_in_executor(_executor, _search)


@mcp.tool()
@sap_gate()
async def handoff_rebuild(app_id: str) -> dict:
    """Rebuild the handoffs.db index by scanning HANDOFF_DIRS."""
    logger.info("[w2] handoff_rebuild app_id=%s", app_id)
    loop = asyncio.get_running_loop()

    def _rebuild():
        import subprocess as _sp
        canonical = Path(__file__).parent / "tools" / "build_handoff_db.py"
        local     = Path(HANDOFF_DB).parent / "build_handoff_db.py"
        script    = str(canonical) if canonical.exists() else str(local)
        if not Path(script).exists():
            return {"error": f"build script not found: {script}"}
        env = os.environ.copy()
        env["WILLOW_HANDOFF_DB"]   = HANDOFF_DB
        env["WILLOW_HANDOFF_DIRS"] = HANDOFF_DIRS
        proc = _sp.run(
            [sys.executable, script], capture_output=True, text=True, timeout=60, env=env,
        )
        return {
            "status":  "ok" if proc.returncode == 0 else "error",
            "stdout":  proc.stdout.strip()[-1000:],
            "stderr":  proc.stderr.strip()[-500:],
            "db_path": HANDOFF_DB,
        }

    return await loop.run_in_executor(_executor, _rebuild)


# ── Tools — soul_ domain (tension detection + AutoDream) ──────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def tension_scan(
    app_id:   str,
    write_kb: bool = False,
    limit:    int  = 30,
) -> dict:
    """Scan KB hypothesis/observed atoms for semantic tensions or redundancies.
    Uses nomic-embed for neighbour search and mistral:7b for pair classification.
    write_kb=True saves findings as a KB atom (category='tension')."""
    logger.info("[w2] tension_scan app_id=%s write_kb=%s", app_id, write_kb)
    loop = asyncio.get_running_loop()

    def _scan():
        import psycopg2.extras as _pge
        from sap.clients.professor_client import _ask_ollama

        if pg is None:
            return {"error": "Postgres unavailable"}

        # Fetch scannable atoms
        try:
            pg._ensure_conn()
            with pg.conn.cursor(cursor_factory=_pge.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, title, summary, tier, confidence
                    FROM knowledge
                    WHERE invalid_at IS NULL
                      AND tier IN ('hypothesis', 'observed')
                      AND summary IS NOT NULL AND summary != ''
                    ORDER BY valid_at DESC
                    LIMIT 60
                """)
                atoms = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            return {"error": f"fetch failed: {e}"}

        if len(atoms) < 2:
            return {"pairs_checked": 0, "tensions": [], "message": "Not enough atoms to scan"}

        seen_pairs: set = set()
        tensions: list = []
        compatible = 0

        for atom in atoms:
            if len(tensions) >= limit:
                break
            try:
                neighbors = pg.knowledge_search_semantic(atom["summary"], limit=4)
            except Exception:
                continue
            for nb in neighbors:
                nid = nb.get("id", "")
                if not nid or nid == atom["id"]:
                    continue
                pair_key = tuple(sorted([atom["id"], nid]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                prompt = (
                    f"Atom A — {atom['title']}\n{atom['summary'][:300]}\n\n"
                    f"Atom B — {nb.get('title','')}\n{(nb.get('summary') or '')[:300]}\n\n"
                    "Classify with EXACTLY one label on the first line, then one reasoning sentence:\n"
                    "TENSION — atoms make conflicting claims\n"
                    "REDUNDANT — one supersedes or fully contains the other\n"
                    "COMPATIBLE — complementary, no conflict"
                )
                try:
                    resp = _ask_ollama(
                        "mistral:7b",
                        "You are a knowledge graph auditor. Classify atom pairs tersely.",
                        prompt,
                    ) or ""
                except Exception:
                    resp = ""

                label = resp.strip().split("\n")[0].upper() if resp else ""
                if "TENSION" in label or "REDUNDANT" in label:
                    tensions.append({
                        "type":   "redundant" if "REDUNDANT" in label else "tension",
                        "atom_a": {"id": atom["id"], "title": atom["title"], "tier": atom.get("tier")},
                        "atom_b": {"id": nid, "title": nb.get("title",""), "tier": nb.get("tier")},
                        "reason": resp.strip()[:400],
                    })
                else:
                    compatible += 1

        result: dict = {
            "pairs_checked":   len(seen_pairs),
            "tensions":        tensions,
            "compatible_pairs": compatible,
        }

        if write_kb and tensions:
            try:
                first = tensions[0]
                kb_summary = (
                    f"Tension scan found {len(tensions)} tension/redundancy pairs among "
                    f"{len(atoms)} scannable atoms ({len(seen_pairs)} pairs checked). "
                    f"First: {first['atom_a']['title']} vs {first['atom_b']['title']}."
                )
                pg.knowledge_put({
                    "title":       f"Tension scan {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}",
                    "summary":     kb_summary,
                    "content":     {"tensions": tensions, "pairs_checked": len(seen_pairs)},
                    "category":    "tension",
                    "source_type": "session",
                    "project":     app_id,
                    "weight":      0.6,
                    "tier":        "observed",
                    "confidence":  0.7,
                })
            except Exception as e:
                result["write_error"] = str(e)

        return result

    return await loop.run_in_executor(_executor, _scan)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def dream_check(app_id: str) -> dict:
    """Check whether AutoDream conditions are met for this agent.
    Conditions: 24h+ since last dream AND 5+ sessions (willow.runs rows) since last dream.
    Returns {should_dream, hours_since_dream, sessions_since_dream, last_dream_at}."""
    logger.info("[w2] dream_check app_id=%s", app_id)
    loop = asyncio.get_running_loop()

    def _check():
        from datetime import datetime, timezone

        dream_state = store.get(f"{app_id}/dream", "state") or {}
        if dream_state.get("locked"):
            return {"should_dream": False, "locked": True, "reason": "dream already running"}

        now = datetime.now(timezone.utc)
        last_str = dream_state.get("last_dream_at", "")
        hours_elapsed = 999.0
        if last_str:
            try:
                last = datetime.fromisoformat(last_str)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                hours_elapsed = (now - last).total_seconds() / 3600
            except Exception:
                pass

        sessions_since = 0
        if pg is not None:
            try:
                pg._ensure_conn()
                with pg.conn.cursor() as cur:
                    if last_str:
                        cur.execute(
                            "SELECT COUNT(*) FROM willow.runs WHERE initiator=%s AND started_at > %s",
                            (app_id, last_str),
                        )
                    else:
                        cur.execute(
                            "SELECT COUNT(*) FROM willow.runs WHERE initiator=%s", (app_id,),
                        )
                    row = cur.fetchone()
                    sessions_since = row[0] if row else 0
            except Exception:
                sessions_since = dream_state.get("sessions_since_dream", 0)

        should_dream = hours_elapsed >= 24 and sessions_since >= 5
        return {
            "should_dream":         should_dream,
            "hours_since_dream":    round(hours_elapsed, 1),
            "sessions_since_dream": sessions_since,
            "last_dream_at":        last_str or None,
            "reason": (
                f"{hours_elapsed:.1f}h elapsed, {sessions_since} sessions since last dream"
                if should_dream
                else f"conditions not met: {hours_elapsed:.1f}h / 24h, {sessions_since} / 5 sessions"
            ),
        }

    return await loop.run_in_executor(_executor, _check)


@mcp.tool()
@sap_gate(write=True)
async def dream_run(app_id: str, force: bool = False) -> dict:
    """Run the AutoDream synthesis pipeline.
    Checks conditions unless force=True. Runs tension scan, synthesises patterns
    from recent KB atoms via mistral:7b, writes a dream KB atom, updates dream state.
    Call dream_check first unless you intend force=True."""
    logger.info("[w2] dream_run app_id=%s force=%s", app_id, force)
    loop = asyncio.get_running_loop()

    def _run():
        import psycopg2.extras as _pge
        from datetime import datetime, timezone
        from sap.clients.professor_client import _ask_ollama

        if pg is None:
            return {"error": "Postgres unavailable"}

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Check lock and conditions
        dream_state = store.get(f"{app_id}/dream", "state") or {}
        if dream_state.get("locked") and not force:
            return {"error": "dream already running (locked). Pass force=true to override."}

        if not force:
            last_str = dream_state.get("last_dream_at", "")
            if last_str:
                try:
                    last = datetime.fromisoformat(last_str)
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    hours_elapsed = (now - last).total_seconds() / 3600
                    if hours_elapsed < 24:
                        return {"skipped": True, "reason": f"only {hours_elapsed:.1f}h since last dream (need 24h)"}
                except Exception:
                    pass

        # Acquire lock
        try:
            store.put(f"{app_id}/dream", {"locked": True, "lock_acquired_at": now_iso}, record_id="state")
        except Exception:
            pass

        try:
            # 1. Fetch recent atoms for synthesis
            pg._ensure_conn()
            with pg.conn.cursor(cursor_factory=_pge.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, title, summary, tier, confidence, category
                    FROM knowledge
                    WHERE invalid_at IS NULL
                      AND summary IS NOT NULL AND summary != ''
                    ORDER BY valid_at DESC
                    LIMIT 20
                """)
                atoms = [dict(r) for r in cur.fetchall()]

            # 2. Lightweight tension scan (no KB write — dream atom captures it)
            tensions: list = []
            seen_pairs: set = set()
            for atom in atoms[:10]:
                try:
                    neighbors = pg.knowledge_search_semantic(atom["summary"], limit=3)
                    for nb in neighbors:
                        nid = nb.get("id", "")
                        if not nid or nid == atom["id"]:
                            continue
                        pair_key = tuple(sorted([atom["id"], nid]))
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)
                        resp = _ask_ollama(
                            "mistral:7b",
                            "You are a knowledge graph auditor.",
                            (f"A: {atom['title']}\n{atom['summary'][:200]}\n\n"
                             f"B: {nb.get('title','')}\n{(nb.get('summary') or '')[:200]}\n\n"
                             "Reply TENSION or COMPATIBLE (one word), then one sentence."),
                        ) or ""
                        if "TENSION" in resp.upper().split("\n")[0]:
                            tensions.append({"ids": [atom["id"], nid], "reason": resp.strip()[:200]})
                except Exception:
                    continue

            # 3. Synthesise patterns via local LLM
            atom_digest = "\n".join(
                f"- [{a.get('tier','?')}] {a['title']}: {(a.get('summary') or '')[:120]}"
                for a in atoms[:12]
            )
            synthesis = _ask_ollama(
                "mistral:7b",
                "You are a thoughtful knowledge synthesist. Be concise and specific.",
                (f"Reflecting on {len(atoms)} recent knowledge atoms for agent {app_id}:\n\n"
                 f"{atom_digest}\n\n"
                 "In 3-4 sentences: what patterns, connections, or gaps do you notice? "
                 "What should be explored or reconciled next?"),
            ) or ""

            # 4. Write dream KB atom
            dream_summary = (
                f"AutoDream over {len(atoms)} atoms — {len(tensions)} tensions detected. "
                + (synthesis[:300] if synthesis else "")
            )
            atom_id = pg.knowledge_put({
                "title":       f"Dream {now.strftime('%Y-%m-%d')} — {app_id}",
                "summary":     dream_summary,
                "content":     {
                    "synthesis":     synthesis,
                    "tensions_found": len(tensions),
                    "tension_pairs": tensions[:5],
                    "atoms_scanned": len(atoms),
                },
                "category":    "dream",
                "source_type": "session",
                "project":     app_id,
                "weight":      0.7,
                "tier":        "observed",
                "confidence":  0.75,
            })

            # 5. Release lock + update state
            store.put(f"{app_id}/dream", {
                "last_dream_at":        now_iso,
                "locked":               False,
                "last_dream_atom":      atom_id,
            }, record_id="state")

            return {
                "atom_id":        atom_id,
                "atoms_scanned":  len(atoms),
                "tensions_found": len(tensions),
                "synthesis":      synthesis[:500] if synthesis else "",
            }

        except Exception as e:
            try:
                store.put(f"{app_id}/dream", {"locked": False, "last_error": str(e)[:200]}, record_id="state")
            except Exception:
                pass
            return {"error": str(e)}

    return await loop.run_in_executor(_executor, _run)


# ── Tools — nest_ domain ──────────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def nest_scan(app_id: str) -> dict:
    """Scan the Nest intake queue — returns staged items and current queue."""
    logger.info("[w2] nest_scan app_id=%s", app_id)
    loop = asyncio.get_running_loop()

    def _scan():
        from sap.core.nest_intake import scan_nest, get_queue
        staged = scan_nest()
        queue  = get_queue()
        return {"staged": staged, "queue": queue, "pending": len(queue)}

    return await loop.run_in_executor(_executor, _scan)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def nest_queue(app_id: str) -> dict:
    """Return the current Nest intake queue without scanning."""
    logger.info("[w2] nest_queue app_id=%s", app_id)
    loop = asyncio.get_running_loop()

    def _queue():
        from sap.core.nest_intake import get_queue
        q = get_queue()
        return {"queue": q, "pending": len(q)}

    return await loop.run_in_executor(_executor, _queue)


@mcp.tool()
@sap_gate()
async def nest_file(
    app_id:        str,
    item_id:       str,
    action:        str,
    override_dest: str = "",
) -> dict:
    """Review a Nest item. action: confirm | skip.
    confirm moves the item to its destination; skip removes it from the queue."""
    logger.info("[w2] nest_file app_id=%s item=%s action=%s", app_id, item_id, action)
    loop = asyncio.get_running_loop()

    def _file():
        from sap.core.nest_intake import confirm_review, skip_item
        if action == "confirm":
            return confirm_review(item_id, override_dest=override_dest or None)
        return skip_item(item_id)

    return await loop.run_in_executor(_executor, _file)


# ── Tools — miscellaneous (blast, journal, governance, persona, base17, agent_create) ──

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_blast(app_id: str, summarize: bool = False) -> dict:
    """Blast-radius scan: map every sensitive file and credential env var reachable by an AI agent.
    Returns a score (0-100, higher = cleaner), reachable paths, and flagged env vars."""
    logger.info("[w2] fleet_blast app_id=%s summarize=%s", app_id, summarize)
    loop = asyncio.get_running_loop()

    def _run():
        result = _blast.run_blast()
        return _blast.summarize_blast(result) if summarize else result

    return await loop.run_in_executor(_executor, _run)


@mcp.tool()
@sap_gate()
async def kb_journal(app_id: str, entry: str, domain: str = "meta") -> dict:
    """Write a journal entry to the knowledge graph."""
    logger.info("[w2] kb_journal app_id=%s domain=%s", app_id, domain)
    loop = asyncio.get_running_loop()

    def _journal():
        if pg:
            atom_id = pg.ingest_ganesha_atom(entry, domain=domain, depth=1)
            return {"status": "logged", "atom_id": atom_id}
        rid, action, _ = store.put("journal/entries", {"text": entry})
        return {"status": "logged_local", "id": rid}

    return await loop.run_in_executor(_executor, _journal)


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_governance(app_id: str) -> dict:
    """Governance status. Dual Commit proposals live in governance/commits/."""
    return {"status": "portless_mode",
            "note": "Governance runs via Dual Commit proposals in governance/commits/"}


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_persona(app_id: str, agent: str = "willow") -> dict:
    """Look up an agent's persona profile location."""
    return {"agent": agent, "note": f"Persona profiles at agents/{agent}/AGENT_PROFILE.md"}


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def fleet_base17(app_id: str, length: int = 5) -> dict:
    """Generate a BASE 17 ID."""
    return {"id": PgBridge.gen_id(length)}


@mcp.tool()
@sap_gate()
async def agent_create(
    app_id:      str,
    name:        str,
    trust:       str = "WORKER",
    role:        str = "",
    folder_root: str = "",
) -> dict:
    """Create a new registered agent with a SAFE manifest and folder structure."""
    logger.info("[w2] agent_create app_id=%s name=%s trust=%s", app_id, name, trust)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor, pg.agent_create,
        name, trust, role, folder_root or None,
    )


# ── Tools — policy_ domain (S8) ──────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def policy_list(app_id: str, active_only: bool = True) -> dict:
    """List all policy rules. Read-only — any fleet_admin agent may call this."""
    logger.info("[w2] policy_list app_id=%s active_only=%s", app_id, active_only)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    rules = await loop.run_in_executor(_executor, pg.policy_list, active_only)
    for r in rules:
        if hasattr(r.get("created_at"), "isoformat"):
            r["created_at"] = r["created_at"].isoformat()
    return {"rules": rules, "count": len(rules)}


@mcp.tool()
@sap_gate(write=True)
async def policy_put(
    app_id:     str,
    name:       str,
    rule_type:  str   = "warn",
    target:     str   = "*",
    action:     str   = "warn",
    threshold:  float = None,
    window_sec: int   = 3600,
) -> dict:
    """Create or update a policy rule. Restricted to heimdallr.
    rule_type: block | warn | limit
    target: tool name or '*' for all tools
    action: block | warn (what to do when rule fires)
    threshold: for limit rules — max calls per window_sec"""
    if app_id != "heimdallr":
        return {"error": "not_permitted", "message": "policy_put is restricted to heimdallr"}
    logger.info("[w2] policy_put app_id=%s name=%r rule_type=%s target=%s", app_id, name, rule_type, target)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    rule_id = await loop.run_in_executor(
        _executor, pg.policy_put,
        name, rule_type, target, action, threshold, window_sec, app_id,
    )
    # Invalidate middleware TTL cache so new rule takes effect immediately
    from sap.middleware import _policy_cache_lock, _policy_cache_ts as _pts
    import sap.middleware as _mw
    with _policy_cache_lock:
        _mw._policy_cache_ts = 0.0
    return {"id": rule_id, "name": name, "status": "upserted"}


@mcp.tool()
@sap_gate(write=True)
async def policy_delete(app_id: str, rule_id: str) -> dict:
    """Deactivate a policy rule by ID or name. Restricted to heimdallr."""
    if app_id != "heimdallr":
        return {"error": "not_permitted", "message": "policy_delete is restricted to heimdallr"}
    logger.info("[w2] policy_delete app_id=%s rule=%s", app_id, rule_id)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(_executor, pg.policy_delete, rule_id)
    import sap.middleware as _mw
    with _mw._policy_cache_lock:
        _mw._policy_cache_ts = 0.0
    return {"deactivated": ok, "rule_id": rule_id}


# ── Tools — voice_ domain (S9) ────────────────────────────────────────────────

def _split_identifier(name: str) -> list:
    """Port of splitIdentifier() from services/voiceKeyterms.ts.
    Splits camelCase, PascalCase, kebab-case, snake_case, and path segments."""
    import re
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return [w.strip() for w in re.split(r"[-_./\s]+", s)
            if 2 < len(w.strip()) <= 20]


_VOICE_GLOBAL_TERMS = [
    "MCP", "symlink", "grep", "regex", "localhost", "codebase",
    "TypeScript", "JSON", "OAuth", "webhook", "gRPC", "dotfiles",
    "subagent", "worktree", "Postgres", "Ollama", "mistral",
    "heimdallr", "hanuman", "willow", "SOIL", "SAFE",
]
_MAX_KEYTERMS = 50


@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def voice_keyterms(
    app_id:       str,
    recent_paths: list = None,
) -> dict:
    """Build STT keyterms for voice input accuracy.
    Returns domain-specific vocabulary: global coding terms + project name + git branch + recent paths.
    Ported from services/voiceKeyterms.ts (Claude Code source)."""
    logger.info("[w2] voice_keyterms app_id=%s", app_id)
    loop = asyncio.get_running_loop()

    def _build():
        import subprocess as _sp
        from pathlib import Path as _P
        from os.path import basename as _bn
        terms: set = set(_VOICE_GLOBAL_TERMS)

        # Project root basename
        cwd = os.getcwd()
        proj_name = _bn(cwd)
        if 2 < len(proj_name) <= 50:
            terms.add(proj_name)

        # Git branch words
        try:
            branch = _sp.check_output(
                ["git", "branch", "--show-current"],
                cwd=cwd, stderr=_sp.DEVNULL, timeout=3,
            ).decode().strip()
            for w in _split_identifier(branch):
                terms.add(w)
        except Exception:
            pass

        # Recent file path words
        for path in (recent_paths or []):
            if len(terms) >= _MAX_KEYTERMS:
                break
            stem = _bn(path).rsplit(".", 1)[0]
            for w in _split_identifier(stem):
                terms.add(w)

        keyterms = list(terms)[:_MAX_KEYTERMS]
        return {"keyterms": keyterms, "count": len(keyterms)}

    return await loop.run_in_executor(_executor, _build)


# ── Tools — infer_7b (orin sub-agent) ────────────────────────────────────────

@mcp.tool()
@sap_gate()
async def infer_7b(
    app_id:     str,
    task_type:  str,
    content:    str  = "",
    context:    str  = "",
    categories: list = None,
    atom_a:     str  = "",
    atom_b:     str  = "",
) -> dict:
    """Run a structured task via mistral:7b (orin sub-agent). Synchronous.
    task_type: summarize | classify | extract | tension
    - summarize: content → {bullets, one_line}
    - classify:  content + categories → {category, confidence, reason}
    - extract:   content → {atoms: [{title, summary, category}]}
    - tension:   atom_a + atom_b → {conflict, score, reason}"""
    logger.info("[w2] infer_7b app_id=%s task_type=%s", app_id, task_type)
    loop = asyncio.get_running_loop()

    def _run():
        from agents.orin.tasks import run as orin_run
        payload: dict = {"content": content, "context": context}
        if categories:
            payload["categories"] = categories
        if atom_a:
            payload["atom_a"] = atom_a
        if atom_b:
            payload["atom_b"] = atom_b
        return orin_run(task_type, payload)

    return await loop.run_in_executor(_executor, _run)


# ── Tools — session_review (S10) ─────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def session_review(
    app_id:         str,
    lookback_hours: int  = 24,
    run_tension:    bool = True,
) -> dict:
    """Review recent session activity using mistral:7b + receipt log.
    Summarises what was done, what succeeded/failed, and flags tensions.
    Mirrors /review (local PR diff) but for Willow sessions, not code PRs."""
    logger.info("[w2] session_review app_id=%s hours=%d tension=%s", app_id, lookback_hours, run_tension)
    if not pg:
        return _no_pg()
    loop = asyncio.get_running_loop()

    def _review():
        from sap.clients.professor_client import _ask_ollama
        import psycopg2.extras as _pge

        # Fetch recent receipts
        receipts = []
        try:
            from core.pg_bridge import get_connection, release_connection
            conn = get_connection()
            try:
                with conn.cursor(cursor_factory=_pge.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT ts, app_id, tool, ok, latency_ms, error_type"
                        " FROM willow.mcp_receipts"
                        " WHERE ts > now() - interval '1 hour' * %s"
                        " ORDER BY ts DESC LIMIT 100",
                        (lookback_hours,),
                    )
                    receipts = [dict(r) for r in cur.fetchall()]
            finally:
                release_connection(conn)
        except Exception as e:
            logger.warning("[w2] session_review: receipts fetch failed: %s", e)

        for r in receipts:
            if hasattr(r.get("ts"), "isoformat"):
                r["ts"] = r["ts"].isoformat()

        tool_counts: dict = {}
        errors = []
        for r in receipts:
            t = r.get("tool", "?")
            tool_counts[t] = tool_counts.get(t, 0) + 1
            if not r.get("ok") and r.get("error_type"):
                errors.append({"tool": t, "error": r["error_type"], "ts": r.get("ts")})

        # Fetch recent KB atoms
        recent_atoms = []
        try:
            pg._ensure_conn()
            with pg.conn.cursor(cursor_factory=_pge.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, title, summary FROM knowledge"
                    " WHERE valid_at > now() - interval '1 hour' * %s"
                    "   AND invalid_at IS NULL"
                    " ORDER BY valid_at DESC LIMIT 20",
                    (lookback_hours,),
                )
                recent_atoms = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

        # Build review prompt
        tool_summary = ", ".join(f"{t}×{n}" for t, n in
                                 sorted(tool_counts.items(), key=lambda x: -x[1])[:10])
        atom_summary = "; ".join(a.get("title", "") for a in recent_atoms[:10])
        error_summary = "; ".join(f"{e['tool']}({e['error']})" for e in errors[:5]) or "none"

        prompt = (
            f"Session review (last {lookback_hours}h). "
            f"Tools called: {tool_summary or 'none'}. "
            f"Errors: {error_summary}. "
            f"New KB atoms: {atom_summary or 'none'}.\n\n"
            "Write a concise session review (3-5 bullet points):\n"
            "- What was accomplished\n- What succeeded or failed\n"
            "- Knowledge gaps or loose ends\n- Suggested next steps"
        )

        synthesis = ""
        try:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as _llm_ex:
                _fut = _llm_ex.submit(
                    _ask_ollama,
                    "mistral:7b",
                    "You are a session analyst. Write concise, actionable reviews.",
                    prompt,
                )
                synthesis = _fut.result(timeout=60) or ""
        except _cf.TimeoutError:
            synthesis = "[review timed out — Ollama busy, retry later]"
        except Exception as e:
            synthesis = f"[review unavailable: {e}]"

        result: dict = {
            "review": synthesis.strip(),
            "lookback_hours": lookback_hours,
            "receipts_sampled": len(receipts),
            "tool_counts": tool_counts,
            "errors_found": len(errors),
            "new_kb_atoms": len(recent_atoms),
            "cited_receipts": [r.get("ts") for r in receipts[:5]],
        }

        # Tension scan inline if requested
        if run_tension:
            try:
                tensions = []
                atoms = pg.knowledge_search("", limit=30)
                seen: set = set()
                for atom in atoms[:10]:
                    neighbors = pg.knowledge_search_semantic(atom.get("summary", ""), limit=3)
                    for nb in neighbors:
                        pk = tuple(sorted([atom.get("id", ""), nb.get("id", "")]))
                        if pk in seen:
                            continue
                        seen.add(pk)
                result["tension_pairs_checked"] = len(seen)
                result["tensions_hint"] = "run tension_scan for full report"
            except Exception:
                pass

        return result

    return await loop.run_in_executor(_executor, _review)


# ── Tools — env_ domain (S6) ─────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def env_check(app_id: str, fork_id: str) -> dict:
    """Compare the current environment against the snapshot saved when fork_id was created.
    Surfaces additions, removals, and value changes for WILLOW_/GROVE_ vars."""
    logger.info("[w2] env_check app_id=%s fork=%s", app_id, fork_id)

    def _check():
        snapshot_rec = store.get(f"{app_id}/forks/{fork_id}/env", record_id="snapshot")
        if not snapshot_rec:
            return {"error": f"No env snapshot for fork {fork_id}. Was fork_create called by this app?"}
        snapshot: dict = snapshot_rec.get("data", snapshot_rec) if "data" in snapshot_rec else snapshot_rec
        current = {k: v for k, v in os.environ.items() if any(k.startswith(p) for p in _ENV_SNAPSHOT_PREFIXES)}
        added   = {k: current[k] for k in current if k not in snapshot}
        removed = {k: snapshot[k] for k in snapshot if k not in current}
        changed = {k: {"was": snapshot[k], "now": current[k]}
                   for k in current if k in snapshot and current[k] != snapshot[k]}
        return {
            "fork_id": fork_id,
            "added":   added,
            "removed": removed,
            "changed": changed,
            "clean":   not (added or removed or changed),
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _check)


# ── Tools — diagnostic_summary (S4) ──────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
@sap_gate()
async def diagnostic_summary(
    app_id: str,
    path:   str  = ".",
    tool:   str  = "auto",
) -> dict:
    """Run ruff and/or mypy on path and return structured diagnostic output.
    Mirrors CC's DiagnosticTrackingService.formatDiagnosticsSummary pattern.
    tool: auto | ruff | mypy | both
    Baseline delta: compares against last run saved in SOIL (app_id/diag/baseline)."""
    logger.info("[w2] diagnostic_summary app_id=%s path=%s tool=%s", app_id, path, tool)
    loop = asyncio.get_running_loop()

    def _diag():
        import subprocess as _sp, json as _j, shutil as _sh
        from pathlib import Path as _P

        results: dict = {"path": path, "tool": tool, "diagnostics": []}
        baseline_key = f"{app_id}/diag/baseline"

        def _run_ruff() -> list:
            if not _sh.which("ruff"):
                return []
            try:
                out = _sp.check_output(
                    ["ruff", "check", path, "--output-format=json", "--quiet"],
                    cwd=os.getcwd(), stderr=_sp.DEVNULL, timeout=30,
                )
                items = _j.loads(out.decode())
                return [{"file": i.get("filename"), "line": i.get("location", {}).get("row"),
                         "col": i.get("location", {}).get("column"),
                         "code": i.get("code"), "message": i.get("message"),
                         "severity": "Error" if i.get("code", "").startswith("E") else "Warning",
                         "source": "ruff"} for i in items]
            except _sp.CalledProcessError as e:
                try:
                    return [{"file": i.get("filename"), "line": i.get("location", {}).get("row"),
                             "code": i.get("code"), "message": i.get("message"),
                             "severity": "Warning", "source": "ruff"}
                            for i in _j.loads(e.output.decode())]
                except Exception:
                    return []
            except Exception:
                return []

        def _run_mypy() -> list:
            if not _sh.which("mypy"):
                return []
            try:
                out = _sp.check_output(
                    ["mypy", path, "--output=json", "--no-error-summary"],
                    cwd=os.getcwd(), stderr=_sp.STDOUT, timeout=60,
                )
                lines = out.decode().splitlines()
            except _sp.CalledProcessError as e:
                lines = e.output.decode().splitlines()
            except Exception:
                return []
            diags = []
            for line in lines:
                try:
                    item = _j.loads(line)
                    diags.append({
                        "file": item.get("file"), "line": item.get("line"),
                        "col": item.get("column"), "code": item.get("error_code"),
                        "message": item.get("message"),
                        "severity": "Error" if item.get("severity") == "error" else "Warning",
                        "source": "mypy",
                    })
                except Exception:
                    pass
            return diags

        use_ruff = tool in ("auto", "ruff", "both")
        use_mypy = tool in ("mypy", "both")

        all_diags = []
        if use_ruff:
            all_diags.extend(_run_ruff())
        if use_mypy:
            all_diags.extend(_run_mypy())

        # Baseline delta — subtract known diagnostics
        try:
            baseline_rec = store.get(baseline_key)
            baseline_diags = baseline_rec.get("diagnostics", []) if baseline_rec else []
        except Exception:
            baseline_diags = []

        baseline_sigs = {(d.get("file"), d.get("line"), d.get("code")) for d in baseline_diags}
        new_diags = [d for d in all_diags
                     if (d.get("file"), d.get("line"), d.get("code")) not in baseline_sigs]

        # Save current as new baseline
        try:
            store.put(baseline_key, {"diagnostics": all_diags})
        except Exception:
            pass

        # Format summary (mirrors formatDiagnosticsSummary)
        sev_sym = {"Error": "✗", "Warning": "⚠", "Info": "ℹ", "Hint": "★"}
        lines = []
        for d in new_diags[:50]:
            sym = sev_sym.get(d.get("severity", "Warning"), "·")
            lines.append(
                f"  {sym} [{d.get('file','?')}:{d.get('line','?')}] "
                f"{d.get('message','')} [{d.get('code','')}] ({d.get('source','')})"
            )

        results["diagnostics"] = new_diags
        results["total_found"] = len(all_diags)
        results["new_since_baseline"] = len(new_diags)
        results["summary"] = "\n".join(lines) if lines else "No new diagnostics."
        return results

    return await loop.run_in_executor(_executor, _diag)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=f"SAP MCP Server {VERSION}")
    ap.add_argument("--http",  action="store_true", help="Run streamable-HTTP instead of stdio")
    ap.add_argument("--port",  type=int, default=6274, help="HTTP port (default: 6274)")
    ap.add_argument("--host",  default="127.0.0.1",   help="HTTP host (default: 127.0.0.1)")
    args = ap.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
