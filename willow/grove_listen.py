#!/usr/bin/env python3
"""
grove_listen.py — Auto-launched Grove LISTEN/NOTIFY background monitor.
b17: GRVLS  ΔΣ=42

Launched by SessionStart hook. Writes one line per new message to stdout
(redirected to /tmp/grove-monitor.log). Automatically discovers new channels.
Claude Code tails this log via Monitor(tail -f /tmp/grove-monitor.log).
"""
import os
import select
import sys
import time

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")


def connect():
    import psycopg2
    dsn = (
        os.environ.get("WILLOW_DB_URL")
        or f"dbname={os.environ.get('WILLOW_PG_DB', 'willow_19')} "
           f"user={os.environ.get('WILLOW_PG_USER', os.environ.get('USER', ''))}"
    )
    c = psycopg2.connect(dsn)
    c.autocommit = True
    return c


def load_channels(cur):
    cur.execute("SELECT id, name FROM grove.channels WHERE is_archived = FALSE")
    return {row[0]: row[1] for row in cur.fetchall()}


ALIASES = {
    "hanuman": ["@hanuman", "@hanu"],
    "vishwakarma": ["@vishwakarma", "@vish", "@karma"],
}


def is_mention(content: str, agent: str) -> bool:
    cl = content.lower()
    for alias in ALIASES.get(agent, [f"@{agent}"]):
        if alias in cl:
            return True
    return False


def main():
    try:
        conn = connect()
        cur = conn.cursor()
    except Exception as e:
        print(f"[grove-listen] connect failed: {e}", flush=True)
        sys.exit(1)

    ch_map = load_channels(cur)
    cursors = {}
    for ch_id in ch_map:
        cur.execute(
            "SELECT COALESCE(MAX(id),0) FROM grove.messages WHERE channel_id = %s",
            (ch_id,),
        )
        cursors[ch_id] = cur.fetchone()[0]

    cur.execute("LISTEN grove_channel")
    print(
        f"[grove-listen] ready as {AGENT} — "
        + ", ".join(f"#{n}" for n in ch_map.values()),
        flush=True,
    )

    while True:
        try:
            if select.select([conn], [], [], 30.0)[0]:
                conn.poll()
                notified = set()
                while conn.notifies:
                    n = conn.notifies.pop(0)
                    try:
                        notified.add(int(n.payload))
                    except ValueError:
                        pass
                for ch_id in notified:
                    if ch_id not in ch_map:
                        ch_map = load_channels(cur)
                        cursors.setdefault(ch_id, 0)
                    ch_name = ch_map.get(ch_id, str(ch_id))
                    since = cursors.get(ch_id, 0)
                    cur.execute(
                        """
                        SELECT id, sender, content FROM grove.messages
                        WHERE channel_id = %s AND id > %s AND is_deleted = 0
                        ORDER BY id ASC
                        """,
                        (ch_id, since),
                    )
                    for row in cur.fetchall():
                        cursors[ch_id] = row[0]
                        msg_id, sender, content = row[0], row[1], str(row[2])
                        mention = is_mention(content, AGENT) and sender.lower() != AGENT.lower()
                        prefix = "[MENTION] " if mention else ""
                        print(
                            f"{prefix}[#{ch_name}:{msg_id}] {sender}: {content[:400]}",
                            flush=True,
                        )
        except Exception as e:
            print(f"[grove-listen-error] {e}", flush=True)
            try:
                conn = connect()
                cur = conn.cursor()
                ch_map = load_channels(cur)
                cur.execute("LISTEN grove_channel")
            except Exception:
                time.sleep(5)


if __name__ == "__main__":
    main()
