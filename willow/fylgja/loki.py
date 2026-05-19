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
You review candidate personal memory atoms for Sean Campbell's knowledge base.
Decide: is this a genuine, specific personal life detail worth storing long-term?

KEEP if the text contains: a real health event (diagnosis, injury, treatment), a named family
situation, a financial event (bankruptcy, debt), a named creative project, a strong emotion
tied to a specific event, or a concrete life-state change.

REJECT if: the match is incidental (the word "back" in a coding sentence), the detail is
vague or generic, it is about Sean's software projects (not his personal life), or there
is not enough context to form a meaningful atom.

Respond with JSON only — no markdown fences, no explanation outside the JSON:
{
  "keep": true,
  "atom": {
    "kind": "event|trait|goal|context",
    "title": "short title (max 60 chars)",
    "category": "health|family|finance|creative|emotion|job|personal",
    "summary": "1-2 sentence description of the personal detail",
    "signal_strength": 1
  }
}
If keep is false: {"keep": false}
signal_strength: 1=weak/uncertain, 3=clear, 5=significant life event.\
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
        f"Pattern categories matched: {', '.join(categories)}\n\n"
        f"Conversation excerpt:\n{excerpt}"
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
