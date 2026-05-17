#!/usr/bin/env python3
"""
sap/server.py — SAP MCP Server 2.0
willow-2.0 / SAP MCP 2.0
b20: SAPMCP2  ΔΣ=42

FastMCP rebuild of sap_mcp.py.

Tool prefixes (13 domains):
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
    str(
        Path.home() / "Ashokoa" / "agents" / _MCP_AGENT
        / "index" / "haumana_handoffs" / "handoffs.db"
    ),
)
_DEFAULT_HANDOFF_DIRS = ":".join([
    str(Path.home() / "Ashokoa" / "agents" / _MCP_AGENT / "index" / "haumana_handoffs"),
    str(Path.home() / ".willow" / "Nest" / _MCP_AGENT),
    str(Path.home() / "Ashokoa" / "Filed" / "reference" / "willow-artifacts" / "documents"),
    str(Path.home() / "Ashokoa" / "Filed" / "reference" / "handoffs"),
    str(Path.home() / "Ashokoa" / "Filed" / "narrative" / "session-log"),
    "+" + str(Path.home() / "Ashokoa" / "corpus"),
    "+" + str(Path.home() / "github" / "die-namic-system" / "docs"),
])
HANDOFF_DIRS = os.environ.get("WILLOW_HANDOFF_DIRS", _DEFAULT_HANDOFF_DIRS)

_ONBOARDING = (Path(__file__).parent / "ONBOARDING.md").read_text(encoding="utf-8")

# ── Global state (initialized in lifespan) ────────────────────────────────────
pg:    "PgBridge | None" = None  # type: ignore[type-arg]
store: WillowStore       = None  # type: ignore[assignment]


# ── Startup helpers ───────────────────────────────────────────────────────────

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
