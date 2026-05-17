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

# ── Tools ─────────────────────────────────────────────────────────────────────
# Phase 2+: tool implementations added here by domain.
# Phase 1: server boots, tools/list returns 0 tools, no import errors.


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
