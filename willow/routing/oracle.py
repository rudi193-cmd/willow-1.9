"""
routing/oracle.py — willow_route oracle.
Hybrid: rule-based fast path (SOIL store) + Yggdrasil LLM fallback.
b17: ROUT1  ΔΣ=42
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from willow.fylgja._mcp import call as mcp_call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
DEFAULT_AGENT = "willow"
RULES_COLLECTION = "willow/routing/rules"
OLLAMA_MODEL = os.environ.get("WILLOW_ROUTE_MODEL", "hf.co/Rudi193/yggdrasil-v9:Q4_K_M")
OLLAMA_URL = "http://localhost:11434/api/chat"

_AGENT_ROSTER = [
    {"name": "willow",   "role": "Primary interface — general conversation and KB queries"},
    {"name": "kart",     "role": "Infrastructure — multi-step tasks, builds, deployments, automation"},
    {"name": "ganesha",  "role": "Diagnostics — debugging, error analysis, obstacle removal"},
    {"name": "shiva",    "role": "Bridge Ring — SAFE protocol, user-facing coordination"},
    {"name": "jeles",    "role": "Librarian — search, retrieval, indexing, special collections"},
    {"name": "gerald",   "role": "Philosophical — reasoning, ethics, deep analysis"},
    {"name": "hanz",     "role": "Code — implementation, refactoring, technical work"},
    {"name": "grove",    "role": "Comms — Grove messages, channels, notifications, posts"},
    {"name": "ada",      "role": "Systems admin — continuity, infrastructure admin"},
    {"name": "pigeon",   "role": "Carrier — cross-system coordination and delivery"},
]

_rules_cache: Optional[list] = None
_cache_session: Optional[str] = None


def _load_rules_from_store() -> list:
    try:
        result = mcp_call("store_list", {
            "app_id": AGENT,
            "collection": RULES_COLLECTION,
        }, timeout=3)
        if isinstance(result, list):
            return sorted(result, key=lambda r: r.get("priority", 0), reverse=True)
    except Exception:
        pass
    return []


def load_rules(session_id: str = "") -> list:
    global _rules_cache, _cache_session
    if _rules_cache is None or _cache_session != session_id:
        _rules_cache = _load_rules_from_store()
        _cache_session = session_id
    return _rules_cache


def match_rules(prompt: str, rules: list) -> Optional[dict]:
    for rule in rules:
        pattern = rule.get("pattern", "")
        if not pattern:
            continue
        try:
            if re.search(pattern, prompt, re.IGNORECASE):
                return rule
        except re.error:
            continue
    return None


def _llm_route(prompt: str) -> Optional[dict]:
    try:
        import urllib.request
        roster_text = "\n".join(f"- {a['name']}: {a['role']}" for a in _AGENT_ROSTER)
        system = (
            "You are a routing oracle for a multi-agent AI system. "
            "Given a user prompt, choose the single best agent to handle it. "
            "Reply with JSON only: {\"agent\": \"<name>\", \"confidence\": <0.0-1.0>}. "
            "Use confidence 1.0 for obvious matches, lower for ambiguous ones. "
            "Default to 'willow' for general conversation."
        )
        user = f"Agents:\n{roster_text}\n\nPrompt: {prompt[:200]}\n\nRoute to:"
        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read()).get("message", {}).get("content", "").strip()
            data = json.loads(raw)
            agent = data.get("agent", DEFAULT_AGENT)
            confidence = float(data.get("confidence", 0.5))
            known = {a["name"] for a in _AGENT_ROSTER}
            if agent not in known:
                agent = DEFAULT_AGENT
            return {"agent": agent, "confidence": round(confidence, 3)}
    except Exception:
        return None


def _write_decision(decision: dict) -> None:
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))
        from pg_bridge import PgBridge
        pg = PgBridge()
        with pg.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO willow.routing_decisions
                    (ts, session_id, prompt_snippet, routed_to, rule_matched, confidence, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                decision["ts"], decision.get("session_id", ""),
                decision.get("prompt_snippet", ""),
                decision["routed_to"], decision["rule_matched"],
                decision["confidence"], decision["latency_ms"],
            ))
            cur.execute("""
                DELETE FROM willow.routing_decisions
                WHERE id NOT IN (
                    SELECT id FROM willow.routing_decisions ORDER BY ts DESC LIMIT 1000
                )
            """)
        pg.conn.commit()
        pg.conn.close()
    except Exception:
        pass


def route(prompt: str, session_id: str = "") -> dict:
    t0 = time.monotonic()
    snippet = prompt.strip()[:40]
    rules = load_rules(session_id)
    matched = match_rules(prompt, rules)

    if matched:
        latency = round((time.monotonic() - t0) * 1000)
        decision = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "prompt_snippet": snippet,
            "routed_to": matched["agent"],
            "rule_matched": matched["id"],
            "confidence": 1.0,
            "latency_ms": latency,
        }
    else:
        llm = _llm_route(prompt)
        latency = round((time.monotonic() - t0) * 1000)
        decision = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "prompt_snippet": snippet,
            "routed_to": llm["agent"] if llm else DEFAULT_AGENT,
            "rule_matched": "llm-fallback",
            "confidence": llm["confidence"] if llm else 0.5,
            "latency_ms": latency,
        }

    _write_decision(decision)
    return decision
