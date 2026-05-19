# willow/fylgja/loki.py — Personal signal gate. b20: LOKI1  ΔΣ=42
"""
Drains personal/candidates SOIL → LLM evaluation → sean.db.
Called from shutdown.py as run_loki_review().

Signal flow:
  stop.py stages candidates  →  loki.py evaluates  →  sean.db atom written
  status: pending            →  ratified | rejected
"""
import json
import urllib.request
from datetime import datetime, timezone

from willow.fylgja._mcp import call
from willow.fylgja._state import AGENT

OLLAMA_URL = "http://localhost:11434/api/chat"
_MODEL = "mistral:7b"
_TIMEOUT = 25
_COLLECTION = "personal/candidates"

_SYSTEM = """\
You are a strict personal memory gate. Your job is to reject false positives.

The keyword detector upstream is noisy — it flags words like "back", "feel", "doctor"
that often appear in non-personal contexts. Read the CONTENT, not the keyword labels.

DEFAULT: REJECT. Only keep if clearly personal.

KEEP only when the excerpt contains a specific, durable personal life detail:
- Health: a named diagnosis, injury, or active medical situation
- Family: a named person in Sean's life + something that happened
- Finance: a concrete financial event (bankruptcy, job loss, specific debt amount)
- Creative: a named project (Books of Mann, Gerald Dispatches, Oakenscroll, UTETY, r/DispatchesFromReality)
- Life change: a concrete state change (new job started, moved city, relationship change)
- Emotion: a strong feeling tied to a specific named event — not a passing comment

REJECT when:
- The excerpt is about software, AI, coding, or Sean's agent fleet (Willow, Grove, Kart, heimdallr, hanuman, etc.)
- The keyword fired in a different sense ("contributing back", "feel this is right", "back-end")
- No specific event or named person is present
- You are not certain — a missed atom is recoverable; a wrong atom is noise forever

Respond with JSON only, no markdown:
{"keep": true, "atom": {"kind": "event|trait|goal|context", "title": "max 60 chars", "category": "health|family|finance|creative|emotion|job|personal", "summary": "1-2 sentences", "signal_strength": 1}}
If rejecting: {"keep": false}
signal_strength: 1=weak, 3=clear, 5=significant life event.\
"""


def _parse_response(text: str) -> dict:
    """Parse LLM JSON response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        # Take the content of the first fence block
        inner = parts[1] if len(parts) > 1 else text
        if inner.startswith("json"):
            inner = inner[4:]
        text = inner.strip()
    return json.loads(text)


def _ask_loki(categories: list[str], excerpt: str) -> dict:
    """Call mistral:7b to evaluate a candidate. Returns parsed JSON dict."""
    user_msg = (
        f"Conversation excerpt:\n{excerpt}\n\n"
        f"(Triggered patterns: {', '.join(categories)} — treat as hints only, not labels)"
    )
    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read())
    text = body.get("message", {}).get("content", "").strip()
    return _parse_response(text)


def _mark(record: dict, status: str) -> None:
    try:
        call("store_update", {
            "app_id": AGENT,
            "collection": _COLLECTION,
            "record_id": record["id"],
            "record": {**record, "status": status, "reviewed_by": "loki"},
        }, timeout=5)
    except Exception:
        pass


def run_loki_review() -> dict:
    """Drain personal/candidates, evaluate with LLM, write to sean.db.

    Returns {"reviewed": n, "ratified": n, "rejected": n, "errors": n}.
    """
    reviewed = ratified = rejected = errors = 0

    try:
        records = call("store_list", {"app_id": AGENT, "collection": _COLLECTION}, timeout=10)
    except Exception:
        return {"reviewed": 0, "ratified": 0, "rejected": 0, "errors": 0}

    if not isinstance(records, list):
        records = [records] if isinstance(records, dict) else []

    pending = [r for r in records if isinstance(r, dict) and r.get("status") == "pending"]
    if not pending:
        return {"reviewed": 0, "ratified": 0, "rejected": 0, "errors": 0}

    now = datetime.now(timezone.utc).isoformat()

    try:
        from core.sean_db import open_sean_db
        db_ctx = open_sean_db()
    except Exception:
        return {"reviewed": 0, "ratified": 0, "rejected": 0, "errors": 1}

    with db_ctx as conn:
        for record in pending:
            reviewed += 1
            categories = record.get("categories", [])
            excerpt = record.get("text_excerpt", "")

            try:
                result = _ask_loki(categories, excerpt)
            except Exception:
                _mark(record, "error")
                errors += 1
                continue

            if not result.get("keep"):
                _mark(record, "rejected")
                rejected += 1
                continue

            atom = result.get("atom") or {}
            title = atom.get("title", "").strip()
            if not title:
                _mark(record, "rejected")
                rejected += 1
                continue

            try:
                conn.execute(
                    """INSERT INTO atoms
                       (kind, title, category, summary, signal_strength,
                        layer, proposed_by, proposed_at)
                       VALUES (?, ?, ?, ?, ?, 'named', 'loki', ?)""",
                    (
                        atom.get("kind", "context"),
                        title,
                        atom.get("category", categories[0] if categories else "personal"),
                        atom.get("summary", ""),
                        atom.get("signal_strength", 3),
                        now,
                    ),
                )
                _mark(record, "ratified")
                ratified += 1
            except Exception:
                _mark(record, "error")
                errors += 1

    return {"reviewed": reviewed, "ratified": ratified, "rejected": rejected, "errors": errors}
