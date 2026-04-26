"""
sap/openclaw_ingest.py — OpenClaw inbound → Willow KB pipeline
b17: OCIN1  ΔΣ=42

Polls openclaw session transcripts for new user messages and ingests them
as knowledge atoms in the hanuman project (openclaw/inbound category).

Usage (standalone / Kart):
    python3 sap/openclaw_ingest.py [--dry-run] [--since-ms <ms>] [--agent-id <id>]

State file: ~/.willow/openclaw_ingest_cursor.json
  {"last_polled_ms": 1234567890000}
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CURSOR_FILE = Path.home() / ".willow" / "openclaw_ingest_cursor.json"
SESSIONS_DIR_TMPL = str(Path.home() / ".openclaw" / "agents" / "{agent_id}" / "sessions")


def _load_cursor() -> int:
    if CURSOR_FILE.exists():
        try:
            return json.loads(CURSOR_FILE.read_text())["last_polled_ms"]
        except Exception:
            pass
    return 0


def _save_cursor(ts_ms: int) -> None:
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_FILE.write_text(json.dumps({"last_polled_ms": ts_ms}))


def _poll_transcripts(since_ms: int, agent_id: str = "main", max_messages: int = 100) -> list[dict]:
    sessions_dir = Path(SESSIONS_DIR_TMPL.format(agent_id=agent_id))
    sessions_file = sessions_dir / "sessions.json"

    if not sessions_file.exists():
        return []

    try:
        # sessions.json is keyed by session_key:
        # {"agent:main:main": {"sessionId": "...", "sessionFile": "/path/to.jsonl", ...}}
        sessions_map = json.loads(sessions_file.read_text())
    except Exception as e:
        print(f"sessions.json unreadable: {e}", file=sys.stderr)
        return []

    messages = []
    for session_key, session in sessions_map.items():
        session_id = session.get("sessionId", "")
        transcript_path = session.get("sessionFile") or (
            str(sessions_dir / f"{session_id}.jsonl") if session_id else ""
        )
        if not transcript_path:
            continue

        transcript = Path(transcript_path)
        if not transcript.exists():
            continue

        try:
            for line in transcript.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if record.get("role") != "user":
                    continue

                ts = record.get("timestamp_ms") or record.get("ts") or record.get("timestamp") or 0
                if isinstance(ts, str):
                    try:
                        ts = int(ts)
                    except ValueError:
                        ts = 0

                if ts <= since_ms:
                    continue

                content = record.get("content", "")
                if isinstance(content, list):
                    parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    content = " ".join(parts)

                if not content.strip():
                    continue

                messages.append({
                    "session_key": session_key,
                    "session_id": session_id,
                    "content": content,
                    "timestamp_ms": ts,
                    "channel": record.get("channel", "unknown"),
                    "sender": record.get("sender", "unknown"),
                    "message_id": record.get("message_id", ""),
                })
        except Exception as e:
            print(f"transcript {session_id} unreadable: {e}", file=sys.stderr)

    messages.sort(key=lambda m: m["timestamp_ms"])
    return messages[:max_messages]


def _ingest_message(pg, msg: dict, dry_run: bool = False) -> bool:
    ts_iso = datetime.fromtimestamp(msg["timestamp_ms"] / 1000, tz=timezone.utc).isoformat()
    title = f"Inbound: {msg['channel']} from {msg['sender']}"
    summary = msg["content"]
    source_id = json.dumps({
        "channel": msg["channel"],
        "sender": msg["sender"],
        "message_id": msg["message_id"],
        "session_key": msg["session_key"],
        "received_at": ts_iso,
    })

    if dry_run:
        print(f"[dry-run] would ingest: {title!r} | {summary[:80]!r}")
        return True

    atom_id = pg.ingest_atom(
        title=title,
        summary=summary,
        source_type="channel_message",
        source_id=source_id,
        category="inbound",
        domain="hanuman",
    )
    if atom_id:
        print(f"ingested: {title!r} | atom={atom_id}")
        return True
    else:
        err = getattr(pg, "_last_ingest_error", "unknown")
        print(f"FAILED: {title!r} | {err}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="OpenClaw inbound → Willow KB ingest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since-ms", type=int, default=None)
    parser.add_argument("--agent-id", default="main")
    parser.add_argument("--reset-cursor", action="store_true")
    args = parser.parse_args()

    if args.reset_cursor and CURSOR_FILE.exists():
        CURSOR_FILE.unlink()
        print("cursor reset")

    since_ms = args.since_ms if args.since_ms is not None else _load_cursor()
    print(f"polling since {since_ms} (agent={args.agent_id})")

    messages = _poll_transcripts(since_ms, agent_id=args.agent_id)
    if not messages:
        print("no new messages")
        return

    print(f"{len(messages)} new message(s)")

    pg = None
    if not args.dry_run:
        from core.pg_bridge import PgBridge
        pg = PgBridge()

    latest_ts = since_ms
    for msg in messages:
        ok = _ingest_message(pg, msg, dry_run=args.dry_run)
        if ok and msg["timestamp_ms"] > latest_ts:
            latest_ts = msg["timestamp_ms"]

    if not args.dry_run and latest_ts > since_ms:
        _save_cursor(latest_ts)
        print(f"cursor updated → {latest_ts}")


if __name__ == "__main__":
    main()
