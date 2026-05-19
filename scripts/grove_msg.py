#!/usr/bin/env python3
"""grove_msg.py — Direct Grove CLI: send/watch/history via Postgres. No LLM, no MCP.
b17: GCLI1 ΔΣ=42

Usage:
    grove_msg send <channel> <message>         # send a message
    grove_msg send <channel> --stdin           # pipe message from stdin
    grove_msg watch <channel>                  # stream new messages (Ctrl-C to stop)
    grove_msg history <channel> [--limit N]    # show recent messages (default 20)

Options:
    --sender NAME    sender name (default: sean)
    --db NAME        Postgres DB name (default: $WILLOW_PG_DB or willow_19)

Examples:
    grove_msg send hanuman "hey, the db is in ~/Downloads"
    echo "sql chunk incoming" | grove_msg send hanuman --stdin
    grove_msg watch heimdallr
    grove_msg history general --limit 10
"""
import argparse
import os
import select
import sys
from datetime import datetime

try:
    import psycopg2
except ImportError:
    print("psycopg2 required: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)


def _connect(db: str) -> psycopg2.extensions.connection:
    user = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", ""))
    host = os.environ.get("WILLOW_PG_HOST", "")
    port = os.environ.get("WILLOW_PG_PORT", "")
    kwargs: dict = {"dbname": db, "user": user}
    if host:
        kwargs["host"] = host
    if port:
        kwargs["port"] = int(port)
    return psycopg2.connect(**kwargs)


def _resolve_channel(cur, name: str) -> int:
    cur.execute("SELECT id FROM grove.channels WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    # create on demand
    cur.execute(
        "INSERT INTO grove.channels (name, channel_type) VALUES (%s, 'group') RETURNING id", (name,)
    )
    return cur.fetchone()[0]


def cmd_send(args):
    db = args.db
    sender = args.sender
    content = ""
    if args.stdin or (not sys.stdin.isatty() and not args.message):
        content = sys.stdin.read().strip()
    else:
        content = " ".join(args.message) if args.message else ""
    if not content:
        print("Error: no message content", file=sys.stderr)
        sys.exit(1)

    conn = _connect(db)
    conn.autocommit = False
    cur = conn.cursor()
    channel_id = _resolve_channel(cur, args.channel)
    cur.execute(
        "INSERT INTO grove.messages (channel_id, sender, content) VALUES (%s, %s, %s) RETURNING id",
        (channel_id, sender, content),
    )
    msg_id = cur.fetchone()[0]
    cur.execute("NOTIFY grove_channel")
    conn.commit()
    conn.close()
    print(f"[#{args.channel} id={msg_id}] {args.sender}: {content[:120]}")


def cmd_watch(args):
    db = args.db
    conn = _connect(db)
    conn.autocommit = True
    cur = conn.cursor()
    channel_id = _resolve_channel(cur, args.channel)

    # seed at current max so we only show new messages
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM grove.messages WHERE is_deleted = 0")
    last_id = cur.fetchone()[0]
    cur.execute("LISTEN grove_channel")
    print(f"[watch] #{args.channel} — live (seeded at id={last_id}). Ctrl-C to stop.", flush=True)

    try:
        while True:
            ready = select.select([conn], [], [], 30)
            conn.poll()
            while conn.notifies:
                conn.notifies.pop()
            cur.execute(
                """SELECT m.id, m.sender, m.content, m.created_at
                     FROM grove.messages m
                    WHERE m.channel_id = %s AND m.is_deleted = 0 AND m.id > %s
                    ORDER BY m.id ASC LIMIT 50""",
                (channel_id, last_id),
            )
            for mid, sender, content, created_at in cur.fetchall():
                if mid > last_id:
                    last_id = mid
                ts = created_at.strftime("%H:%M:%S") if created_at else "?"
                preview = content[:200] + ("…" if len(content) > 200 else "")
                print(f"[{ts} id={mid}] {sender}: {preview}", flush=True)
    except KeyboardInterrupt:
        print("\n[watch] stopped.")
    finally:
        conn.close()


def cmd_history(args):
    db = args.db
    conn = _connect(db)
    cur = conn.cursor()
    channel_id = _resolve_channel(cur, args.channel)
    cur.execute(
        """SELECT m.id, m.sender, m.content, m.created_at
             FROM grove.messages m
            WHERE m.channel_id = %s AND m.is_deleted = 0
            ORDER BY m.id DESC LIMIT %s""",
        (channel_id, args.limit),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print(f"[#{args.channel}] no messages")
        return
    for mid, sender, content, created_at in reversed(rows):
        ts = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "?"
        preview = content[:200] + ("…" if len(content) > 200 else "")
        print(f"[{ts} id={mid}] {sender}: {preview}")


def main():
    db_default = os.environ.get("WILLOW_PG_DB", "willow_19")
    parser = argparse.ArgumentParser(
        description="Direct Grove CLI — send/watch/history without LLM or MCP."
    )
    parser.add_argument("--db", default=db_default, help=f"Postgres DB (default: {db_default})")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="send a message to a channel")
    p_send.add_argument("channel", help="channel name (e.g. hanuman)")
    p_send.add_argument("message", nargs="*", help="message text (or use --stdin)")
    p_send.add_argument("--stdin", action="store_true", help="read message from stdin")
    p_send.add_argument("--sender", default="sean", help="sender name (default: sean)")

    p_watch = sub.add_parser("watch", help="stream new messages from a channel")
    p_watch.add_argument("channel", help="channel name")

    p_hist = sub.add_parser("history", help="show recent messages from a channel")
    p_hist.add_argument("channel", help="channel name")
    p_hist.add_argument("--limit", type=int, default=20, help="number of messages (default: 20)")

    args = parser.parse_args()

    if args.cmd == "send":
        cmd_send(args)
    elif args.cmd == "watch":
        cmd_watch(args)
    elif args.cmd == "history":
        cmd_history(args)


if __name__ == "__main__":
    main()
