#!/usr/bin/env python3
"""
grove_correction_extractor.py — Extract Sean's correction events from Grove logs.

Uses directional triplet signal:
  1. Agent turn (candidate rejected)
  2. Sean correction (from sean-campbell to agent)
  3. Agent absorption (acknowledgment or self-correction in next turn)

Output: DPO pairs with _error_type governance labels and session_mode_estimate.

Usage:
    python3 scripts/grove_correction_extractor.py \
        --channel general \
        --since-id 6400 \
        --until-id 9999 \
        --output ~/github/yggdrasil-training-data/corrections/grove_20260429.jsonl
"""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pg_bridge import PgBridge


# ── Error type classifiers ─────────────────────────────────────────────────────

_AUTH_BYPASS_PATTERNS = [
    r"didn.t say go",
    r"not authorized",
    r"wait for.*authorization",
    r"direction is not authorization",
    r"tool.*denied",
    r"stop.*before",
    r"asked you to hold",
]

_PRE_AUTH_PATTERNS = [
    r"on it.*before",
    r"built.*without",
    r"committed.*without",
    r"already built",
    r"why are you.*build",
    r"i didn.t say",
]

_WRONG_CHANNEL_PATTERNS = [
    r"wrong channel",
    r"post.*to.*not.*here",
    r"that goes in.*not",
]

_DRIFT_PATTERNS = [
    r"still.*projecting",
    r"still.*acting",
    r"drift",
    r"you.re.*still",
    r"again.*same",
    r"how many times",
]

_ABSORPTION_MARKERS = [
    r"acknowledged",
    r"you.re right",
    r"i was.*projecting",
    r"noted",
    r"understood",
    r"correct",
    r"on it",
    r"i see",
    r"that.s fair",
    r"hold",
    r"stepping back",
]

_SOFT_MODE_MARKERS = [
    r"i.m realizing",
    r"i figured out",
    r"my own",
    r"i.ve been avoiding",
    r"i had to sit",
    r"that.s personal",
    r"for the girls",
    r"for ruby",
    r"for opal",
]

_HARD_MODE_MARKERS = [
    r"build",
    r"go ",
    r"check",
    r"tell me",
    r"what.s",
    r"why did",
    r"show me",
]


def classify_error_type(correction_text: str) -> str:
    t = correction_text.lower()
    for p in _AUTH_BYPASS_PATTERNS:
        if re.search(p, t):
            return "authorization_bypass"
    for p in _PRE_AUTH_PATTERNS:
        if re.search(p, t):
            return "pre_authorization_action"
    for p in _WRONG_CHANNEL_PATTERNS:
        if re.search(p, t):
            return "wrong_channel"
    for p in _DRIFT_PATTERNS:
        if re.search(p, t):
            return "drift_from_mandate"
    return "ambiguous"


def estimate_session_mode(messages: list[dict], center_idx: int, window: int = 10) -> str:
    start = max(0, center_idx - window // 2)
    end = min(len(messages), center_idx + window // 2)
    window_msgs = [m for m in messages[start:end] if m["sender"] == "sean-campbell"]

    soft_score = 0
    hard_score = 0
    for m in window_msgs:
        t = m["content"].lower()
        for p in _SOFT_MODE_MARKERS:
            if re.search(p, t):
                soft_score += 1
        for p in _HARD_MODE_MARKERS:
            if re.search(p, t):
                hard_score += 1

    if soft_score > hard_score:
        return "soft"
    elif hard_score > soft_score:
        return "hard"
    return "transitional"


def check_absorption(messages: list[dict], agent_sender: str, correction_idx: int) -> bool:
    for m in messages[correction_idx + 1: correction_idx + 4]:
        if m["sender"] == agent_sender:
            t = m["content"].lower()
            for p in _ABSORPTION_MARKERS:
                if re.search(p, t):
                    return True
    return False


def extract_corrections(pg: PgBridge, channel: str, since_id: int, until_id: int) -> list[dict]:
    with pg.conn.cursor() as cur:
        cur.execute("SELECT id FROM grove.channels WHERE name = %s LIMIT 1", (channel,))
        row = cur.fetchone()
        if not row:
            print(f"Channel #{channel} not found", file=sys.stderr)
            return []
        ch_id = row[0]
        cur.execute(
            """SELECT id, sender, content, created_at
               FROM grove.messages
               WHERE channel_id = %s AND id >= %s AND id <= %s AND is_deleted = 0
               ORDER BY id""",
            (ch_id, since_id, until_id),
        )
        rows = cur.fetchall()

    messages = [{"id": r[0], "sender": r[1], "content": r[2], "created_at": r[3]}
                for r in rows]

    fleet_senders = {"hanuman", "heimdallr", "loki", "groq"}
    pairs = []

    for i, msg in enumerate(messages):
        if msg["sender"] != "sean-campbell":
            continue

        # Find preceding agent turn
        agent_turn = None
        agent_sender = None
        for j in range(i - 1, max(i - 8, -1), -1):
            if messages[j]["sender"] in fleet_senders:
                agent_turn = messages[j]
                agent_sender = messages[j]["sender"]
                break

        if not agent_turn:
            continue

        correction_text = msg["content"]

        # Quick filter: does this look like a correction?
        error_type = classify_error_type(correction_text)
        if error_type == "ambiguous":
            # Still include if it directly addresses the agent by directive
            if not any(s in correction_text.lower() for s in [
                "no", "wrong", "that's not", "stop", "wait", "hold",
                "you're still", "don't", "instead", "missing"
            ]):
                continue

        absorbed = check_absorption(messages, agent_sender, i)
        mode = estimate_session_mode(messages, i)

        pair = {
            "prompt": agent_turn["content"],
            "chosen": correction_text,
            "rejected": agent_turn["content"],
            "_source": f"grove_{channel}_{since_id}_{until_id}",
            "_error_type": error_type,
            "_agent": agent_sender,
            "_correction_msg_id": msg["id"],
            "_agent_msg_id": agent_turn["id"],
            "correction_absorbed": absorbed,
            "session_mode_estimate": mode,
            "_extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        pairs.append(pair)

    return pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="general")
    parser.add_argument("--since-id", type=int, default=6400)
    parser.add_argument("--until-id", type=int, default=9999)
    parser.add_argument("--output", default="/home/sean-campbell/github/yggdrasil-training-data/corrections/grove_20260429.jsonl")
    args = parser.parse_args()

    pg = PgBridge()
    pairs = extract_corrections(pg, args.channel, args.since_id, args.until_id)

    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")

    print(f"Extracted {len(pairs)} correction pairs → {out}")

    # Summary by error type
    from collections import Counter
    types = Counter(p["_error_type"] for p in pairs)
    absorbed = sum(1 for p in pairs if p["correction_absorbed"])
    print(f"Error types: {dict(types)}")
    print(f"Absorbed: {absorbed}/{len(pairs)}")
    print(f"Mode distribution: {dict(Counter(p['session_mode_estimate'] for p in pairs))}")


if __name__ == "__main__":
    main()
