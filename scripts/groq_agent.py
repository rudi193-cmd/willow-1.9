#!/usr/bin/env python3
"""
groq_agent.py — Drop a Groq-powered agent into Grove.

Reads recent #general messages, generates a response via Groq (llama-3.3-70b),
posts back as sender "groq". Run once for a single turn, or --loop for continuous.

Usage:
    python3 scripts/groq_agent.py [--channel general] [--sender groq] [--loop]
"""
import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pg_bridge import PgBridge


def _load_groq_key() -> str:
    creds_path = Path.home() / ".willow/secrets/credentials.json"
    with open(creds_path) as f:
        d = json.load(f)
    return d.get("GROQ_API_KEY") or d.get("GROQ_API_KEY_2") or d.get("GROQ_API_KEY_3", "")


def _grove_messages(pg: PgBridge, channel: str, limit: int = 20) -> list[dict]:
    with pg.conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM grove.channels WHERE name = %s LIMIT 1", (channel,)
        )
        row = cur.fetchone()
        if not row:
            return []
        ch_id = row[0]
        cur.execute(
            """SELECT id, sender, content, created_at
               FROM grove.messages
               WHERE channel_id = %s AND is_deleted = 0
               ORDER BY id DESC LIMIT %s""",
            (ch_id, limit),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "sender": r[1], "content": r[2], "created_at": r[3]}
            for r in reversed(rows)]


def _grove_post(pg: PgBridge, channel: str, sender: str, content: str) -> int:
    with pg.conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM grove.channels WHERE name = %s LIMIT 1", (channel,)
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Channel #{channel} not found")
        ch_id = row[0]
        cur.execute(
            "INSERT INTO grove.messages (channel_id, sender, content) VALUES (%s, %s, %s) RETURNING id",
            (ch_id, sender, content),
        )
        msg_id = cur.fetchone()[0]
    pg.conn.commit()
    return msg_id


def _build_messages(history: list[dict], sender: str, persona_file: str | None = None) -> list[dict]:
    if persona_file:
        system = Path(persona_file).read_text(encoding="utf-8").strip()
    else:
        system = (
            f"You are {sender}, a Groq-powered agent participating in a live multi-agent "
            "conversation in a workspace called Grove. Other agents include hanuman (builder), "
            "heimdallr (dashboard watcher), and loki (adversarial critic). "
            "Sean Campbell is the human operator. Keep responses short and direct — "
            "one to three sentences unless the question requires more. "
            "You are joining an ongoing technical conversation. Be useful, not performative."
        )
    msgs = [{"role": "system", "content": system}]
    for m in history[-15:]:
        role = "assistant" if m["sender"] == sender else "user"
        msgs.append({"role": role, "content": f"[{m['sender']}] {m['content']}"})
    return msgs


def run_once(pg: PgBridge, channel: str, sender: str, api_key: str, persona_file: str | None = None) -> None:
    import litellm
    os.environ["GROQ_API_KEY"] = api_key

    history = _grove_messages(pg, channel)
    if not history:
        print(f"No messages in #{channel}", flush=True)
        return

    last = history[-1]
    if last["sender"] == sender:
        print("Last message was mine — skipping to avoid self-reply.", flush=True)
        return

    msgs = _build_messages(history, sender, persona_file)
    response = litellm.completion(
        model="groq/llama-3.3-70b-versatile",
        messages=msgs,
        max_tokens=300,
        temperature=0.7,
    )
    reply = response.choices[0].message.content.strip()
    msg_id = _grove_post(pg, channel, sender, reply)
    print(f"Posted #{channel}:{msg_id} as {sender}: {reply[:80]}", flush=True)


def run_loop(pg: PgBridge, channel: str, sender: str, api_key: str, poll_s: int = 10, persona_file: str | None = None) -> None:
    print(f"Groq agent '{sender}' watching #{channel} (poll={poll_s}s) — Ctrl-C to stop", flush=True)
    last_seen_id = 0

    # seed cursor
    msgs = _grove_messages(pg, channel, limit=1)
    if msgs:
        last_seen_id = msgs[-1]["id"]

    while True:
        time.sleep(poll_s)
        try:
            with pg.conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM grove.channels WHERE name = %s LIMIT 1", (channel,)
                )
                row = cur.fetchone()
                if not row:
                    continue
                ch_id = row[0]
                cur.execute(
                    """SELECT id, sender, content FROM grove.messages
                       WHERE channel_id = %s AND id > %s AND is_deleted = 0
                       ORDER BY id""",
                    (ch_id, last_seen_id),
                )
                new_rows = cur.fetchall()

            if not new_rows:
                continue

            last_seen_id = new_rows[-1][0]

            # respond to any new message not from ourselves — but not every time
            trigger = any(r[1] != sender for r in new_rows)
            if not trigger:
                continue

            # ~40% chance to respond, skip the rest silently
            if random.random() > 0.4:
                continue

            # random delay 5-45s to avoid instant-response pattern
            time.sleep(random.randint(5, 45))

            run_once(pg, channel, sender, api_key, persona_file)

        except KeyboardInterrupt:
            print("Stopping.", flush=True)
            break
        except Exception as e:
            print(f"Error: {e}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="general")
    parser.add_argument("--sender", default="groq")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll", type=int, default=10)
    parser.add_argument("--persona", default=None, help="Path to persona .md file (system prompt)")
    args = parser.parse_args()

    api_key = _load_groq_key()
    if not api_key:
        print("No GROQ_API_KEY found in ~/.willow/secrets/credentials.json", flush=True)
        sys.exit(1)

    pg = PgBridge()
    if args.loop:
        run_loop(pg, args.channel, args.sender, api_key, args.poll, args.persona)
    else:
        run_once(pg, args.channel, args.sender, api_key, args.persona)


if __name__ == "__main__":
    main()
