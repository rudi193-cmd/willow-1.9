#!/usr/bin/env python3
"""
grove_monitor_heimdallr.py — Persistent Grove monitor for heimdallr.
Uses Postgres LISTEN/NOTIFY. Runs as a systemd user service.

Rules:
  - #heimdallr channel: ALL messages fire (no tag required)
  - All other channels: only fires when @heimdallr / @heim / @all addressed

Startup hook checks:
  - /tmp/grove-monitor.pid  (written on start, removed on exit)
  - /tmp/grove-monitor.log  (StandardOutput in systemd unit)
  - Grep target: [MENTION] prefix on addressed messages
"""
import os
import select
import signal
import sys
import time
from pathlib import Path

import psycopg2

DB            = os.environ.get("WILLOW_PG_DB", "willow_19")
HOST          = os.environ.get("WILLOW_PG_HOST") or None
USER          = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", ""))
AGENT         = "heimdallr"
MY_CHANNEL_ID = 34
ALIASES       = ["@heimdallr", "@heim", "@all"]
PID_FILE      = Path("/tmp/grove-monitor.pid")


def _cleanup(_sig=None, _frame=None):
    PID_FILE.unlink(missing_ok=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, _cleanup)
signal.signal(signal.SIGINT, _cleanup)


def connect():
    c = psycopg2.connect(dbname=DB, host=HOST, user=USER)
    c.autocommit = True
    return c


def seed_last_id(cur):
    cur.execute("SELECT COALESCE(MAX(id),0) FROM grove.messages WHERE is_deleted=0")
    return cur.fetchone()[0]


def fetch_new(cur, last_id):
    cur.execute("""
        SELECT m.id, m.sender, m.content, m.channel_id, c.name
          FROM grove.messages m
          JOIN grove.channels c ON c.id = m.channel_id
         WHERE m.is_deleted = 0 AND m.id > %s
         ORDER BY m.id ASC LIMIT 50
    """, (last_id,))
    return cur.fetchall()


def should_emit(channel_id, content):
    if channel_id == MY_CHANNEL_ID:
        return True
    cl = content.lower()
    return any(a in cl for a in ALIASES)


def is_mention(channel_id, content):
    """True when the message is an explicit @address (not just own-channel traffic)."""
    cl = content.lower()
    return any(a in cl for a in ALIASES)


def run():
    PID_FILE.write_text(str(os.getpid()))

    backoff = 5
    while True:
        try:
            conn = connect()
            cur  = conn.cursor()
            last_id = seed_last_id(cur)
            cur.execute("LISTEN grove_channel")
            print(f"[{AGENT}-monitor] live — seeded at id={last_id}", flush=True)
            backoff = 5

            while True:
                select.select([conn], [], [], 30)
                conn.poll()
                while conn.notifies:
                    conn.notifies.pop()
                rows = fetch_new(cur, last_id)
                for mid, sender, content, channel_id, channel_name in rows:
                    if mid > last_id:
                        last_id = mid
                    if should_emit(channel_id, content):
                        preview = content[:1500] + (
                            f" [TRUNCATED — fetch id={mid}]" if len(content) > 1500 else ""
                        )
                        tag = "[MENTION]" if is_mention(channel_id, content) else f"[#{channel_name}]"
                        print(f"{tag} [id={mid}] {sender}: {preview}", flush=True)

        except Exception as e:
            print(f"[{AGENT}-monitor] connection error: {e} — retrying in {backoff}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    run()
