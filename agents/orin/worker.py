"""
agents/orin/worker.py — Dispatch queue poller for the orin (mistral:7b) sub-agent.

Polls dispatch_tasks WHERE to_agent='orin' AND status='pending',
runs each task through agents.orin.tasks, writes result back via
agent_dispatch_result (direct DB write to keep it portable).

Run:
    WILLOW_AGENT_NAME=orin python3 -m agents.orin.worker
    or via systemd: orin-worker.service
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Ensure willow-1.9/ is on sys.path
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [orin] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("orin.worker")

POLL_INTERVAL = 5        # seconds between queue polls
TASK_TIMEOUT  = 120      # seconds before marking a claimed task as failed
APP_ID        = "orin"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_conn():
    from core.pg_bridge import get_connection
    return get_connection()


def _release(conn):
    from core.pg_bridge import release_connection
    release_connection(conn)


def _claim_task(conn) -> dict | None:
    """Atomically claim one pending orin task. Returns row dict or None."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dispatch_tasks SET status='running', updated_at=now()"
                " WHERE id = ("
                "   SELECT id FROM dispatch_tasks"
                "   WHERE to_agent=%s AND status='pending'"
                "   ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
                " ) RETURNING id, from_agent, prompt, context_id, depth",
                (APP_ID,),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                return {"id": row[0], "from_agent": row[1], "prompt": row[2],
                        "context_id": row[3], "depth": row[4]}
    except Exception as e:
        logger.warning("claim_task error: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
    return None


def _write_result(conn, dispatch_id: str, result: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dispatch_tasks SET status='completed', result=%s, updated_at=now()"
                " WHERE id=%s",
                (result, dispatch_id),
            )
        conn.commit()
    except Exception as e:
        logger.warning("write_result error %s: %s", dispatch_id, e)
        try:
            conn.rollback()
        except Exception:
            pass


def _mark_failed(conn, dispatch_id: str, reason: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dispatch_tasks SET status='failed', result=%s, updated_at=now()"
                " WHERE id=%s",
                (json.dumps({"error": reason}), dispatch_id),
            )
        conn.commit()
    except Exception:
        pass


# ── Task execution ────────────────────────────────────────────────────────────

def _execute(task: dict) -> str:
    """Parse prompt as JSON task envelope and run it. Returns JSON result string."""
    from agents.orin.tasks import run

    prompt = task.get("prompt", "")
    try:
        envelope = json.loads(prompt)
    except Exception:
        # Plain text prompt → treat as summarize
        envelope = {"task_type": "summarize", "content": prompt}

    task_type = envelope.pop("task_type", "summarize")
    logger.info("executing task_type=%s dispatch_id=%s", task_type, task["id"])
    result = run(task_type, envelope)
    return json.dumps(result)


# ── Main loop ─────────────────────────────────────────────────────────────────

_running = True


def _handle_signal(sig, frame):
    global _running
    logger.info("signal %s received — shutting down", sig)
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("orin worker started (model=mistral:7b poll=%ds)", POLL_INTERVAL)

    while _running:
        conn = None
        try:
            conn = _get_conn()
            task = _claim_task(conn)
            if task:
                try:
                    result_json = _execute(task)
                    _write_result(conn, task["id"], result_json)
                    logger.info("completed dispatch_id=%s", task["id"])
                except Exception as e:
                    logger.exception("task execution failed: %s", e)
                    _mark_failed(conn, task["id"], str(e))
        except Exception as e:
            logger.warning("poll error: %s", e)
        finally:
            if conn:
                try:
                    _release(conn)
                except Exception:
                    pass

        # Small sleep between polls; check _running frequently
        for _ in range(POLL_INTERVAL * 2):
            if not _running:
                break
            time.sleep(0.5)

    logger.info("orin worker stopped")


if __name__ == "__main__":
    main()
