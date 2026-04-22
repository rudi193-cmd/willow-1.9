# willow_route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `willow_route` stub in `sap/sap_mcp.py:1048` with a real routing oracle — hybrid rule-based fast path (SOIL store) + Yggdrasil LLM fallback. Wire `_run_route()` into `prompt_submit.py` so every user prompt gets a routing injection. Write decisions to `willow.routing_decisions` for dashboard display.

**Architecture:**
- Rules live in SOIL store (`willow/routing/rules`) — Sean can add/modify without code changes
- Fast path: load rules, match prompt against regex patterns in priority order, first match wins
- LLM fallback: call Ollama `yggdrasil:v9` with agent roster + roles + prompt when no rule matches
- Every decision written to `willow.routing_decisions` Postgres table (1000-row retention)
- `_run_route()` injected into `prompt_submit.py` — fires after `_run_source_ring()`, before other behaviors
- Decision injected as `[ROUTE]` context block in prompt output

**Data shape (agreed with Heimdallr/Design Claude):**
```json
{
  "ts": "2026-04-22T13:04:12Z",
  "prompt_snippet": "debug gleipnir rate limit",
  "routed_to": "ganesha",
  "rule_matched": "rule-ganesha-debug",
  "confidence": 1.0,
  "latency_ms": 3
}
```
- `rule_matched` never null — `"llm-fallback"` when Yggdrasil decides
- `confidence`: 1.0 for rule matches, LLM self-reported (0.0–1.0) for fallback

**Tech Stack:** Python 3.11+, SOIL store (WillowStore), Postgres (pg_bridge), Ollama subprocess, willow MCP client (`_mcp.call()`), pytest

---

## File Map

**Modify:**
- `sap/sap_mcp.py` — replace `willow_route` stub with real implementation
- `willow/fylgja/events/prompt_submit.py` — add `_run_route()` behavior

**Create:**
- `willow/routing/__init__.py`
- `willow/routing/oracle.py` — core routing logic (rules + LLM fallback)
- `willow/routing/seed_rules.py` — bootstrap default routing rules into SOIL store
- `tests/test_routing/__init__.py`
- `tests/test_routing/test_oracle.py`
- `tests/test_routing/test_prompt_submit_route.py`

**Schema:**
- `willow.routing_decisions` Postgres table (new — DDL in Task 1)

---

### Task 1: Postgres schema — `willow.routing_decisions`

- [ ] **Step 1: Create the table in willow_19 and willow_19_test**

```sql
CREATE TABLE IF NOT EXISTS willow.routing_decisions (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id  TEXT,
    prompt_snippet TEXT,
    routed_to   TEXT NOT NULL,
    rule_matched TEXT NOT NULL,
    confidence  NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    latency_ms  INTEGER NOT NULL DEFAULT 0
);

-- Retention: keep last 1000 rows only
CREATE INDEX IF NOT EXISTS idx_routing_decisions_ts ON willow.routing_decisions (ts DESC);
```

Run against both `willow_19` and `willow_19_test`:

```bash
psql -U sean-campbell willow_19 -c "CREATE SCHEMA IF NOT EXISTS willow;"
psql -U sean-campbell willow_19 -f <(cat <<'SQL'
CREATE TABLE IF NOT EXISTS willow.routing_decisions (
    id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id TEXT, prompt_snippet TEXT, routed_to TEXT NOT NULL,
    rule_matched TEXT NOT NULL, confidence NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    latency_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_ts ON willow.routing_decisions (ts DESC);
SQL
)
psql -U sean-campbell willow_19_test -f <(cat <<'SQL'
CREATE TABLE IF NOT EXISTS willow.routing_decisions (
    id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id TEXT, prompt_snippet TEXT, routed_to TEXT NOT NULL,
    rule_matched TEXT NOT NULL, confidence NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    latency_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_ts ON willow.routing_decisions (ts DESC);
SQL
)
```

- [ ] **Step 2: Verify table exists**

```bash
psql -U sean-campbell willow_19 -c "\d willow.routing_decisions"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(routing): create willow.routing_decisions table in willow_19 + willow_19_test"
```

---

### Task 2: `willow/routing/oracle.py` — core routing logic

**Files:**
- Create: `willow/routing/__init__.py`
- Create: `willow/routing/oracle.py`
- Create: `tests/test_routing/__init__.py`
- Create: `tests/test_routing/test_oracle.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_routing/test_oracle.py
"""willow_route oracle — rule-based fast path and LLM fallback."""
import json
from unittest.mock import patch, MagicMock
import pytest
from willow.routing.oracle import route, load_rules, match_rules, DEFAULT_AGENT

SAMPLE_RULES = [
    {"id": "rule-kart", "pattern": r"\b(task|build|deploy|run|execute)\b",
     "agent": "kart", "priority": 10},
    {"id": "rule-ganesha", "pattern": r"\b(debug|error|diagnose|fix|broken)\b",
     "agent": "ganesha", "priority": 10},
    {"id": "rule-jeles", "pattern": r"\b(search|find|retrieve|index|library)\b",
     "agent": "jeles", "priority": 10},
    {"id": "rule-grove", "pattern": r"\b(message|channel|send|notify|post)\b",
     "agent": "grove", "priority": 10},
]


def test_match_rules_returns_first_match():
    result = match_rules("debug the gleipnir rate limit", SAMPLE_RULES)
    assert result is not None
    assert result["agent"] == "ganesha"
    assert result["id"] == "rule-ganesha"


def test_match_rules_returns_none_when_no_match():
    result = match_rules("what time is it", SAMPLE_RULES)
    assert result is None


def test_match_rules_case_insensitive():
    result = match_rules("SEND a message to architecture", SAMPLE_RULES)
    assert result is not None
    assert result["agent"] == "grove"


def test_route_rule_match_returns_correct_shape():
    with patch("willow.routing.oracle._load_rules_from_store", return_value=SAMPLE_RULES):
        decision = route("run the test suite", session_id="abc123")
    assert decision["routed_to"] == "kart"
    assert decision["rule_matched"] == "rule-kart"
    assert decision["confidence"] == 1.0
    assert "latency_ms" in decision
    assert "ts" in decision


def test_route_defaults_to_willow_when_no_rules():
    with patch("willow.routing.oracle._load_rules_from_store", return_value=[]):
        with patch("willow.routing.oracle._llm_route", return_value=None):
            decision = route("something ambiguous", session_id="abc123")
    assert decision["routed_to"] == DEFAULT_AGENT
    assert decision["rule_matched"] == "llm-fallback"


def test_route_llm_fallback_called_when_no_rule_matches():
    with patch("willow.routing.oracle._load_rules_from_store", return_value=SAMPLE_RULES):
        with patch("willow.routing.oracle._llm_route", return_value={
            "agent": "gerald", "confidence": 0.72
        }) as mock_llm:
            decision = route("ponder the ontology of memory", session_id="abc123")
    mock_llm.assert_called_once()
    assert decision["routed_to"] == "gerald"
    assert decision["rule_matched"] == "llm-fallback"
    assert decision["confidence"] == 0.72


def test_route_snippet_truncated_to_40_chars():
    long_prompt = "a" * 200
    with patch("willow.routing.oracle._load_rules_from_store", return_value=[]):
        with patch("willow.routing.oracle._llm_route", return_value=None):
            decision = route(long_prompt, session_id="abc")
    assert len(decision["prompt_snippet"]) <= 40
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_routing/test_oracle.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write `willow/routing/__init__.py`**

```python
"""willow.routing — Intent routing oracle. b17: ROUT1 ΔΣ=42"""
```

- [ ] **Step 4: Write `willow/routing/oracle.py`**

```python
"""
routing/oracle.py — willow_route oracle.
Hybrid: rule-based fast path (SOIL store) + Yggdrasil LLM fallback.
b17: ROUT1
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
        roster_text = "\n".join(
            f"- {a['name']}: {a['role']}" for a in _AGENT_ROSTER
        )
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
        from core.pg_bridge import PgBridge
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
            # Retention: keep last 1000
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
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_routing/test_oracle.py -v 2>&1 | tail -15
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add willow/routing/ tests/test_routing/
git commit -m "feat(routing): oracle.py — rule-based fast path + Yggdrasil LLM fallback (7 tests)"
```

---

### Task 3: `willow/routing/seed_rules.py` — bootstrap default rules

- [ ] **Step 1: Write `willow/routing/seed_rules.py`**

```python
"""
seed_rules.py — Bootstrap default routing rules into SOIL store.
Run: python3 -m willow.routing.seed_rules [--dry-run]
"""
import argparse
import json
import os
from willow.fylgja._mcp import call as mcp_call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
COLLECTION = "willow/routing/rules"

DEFAULT_RULES = [
    {
        "id": "rule-kart",
        "pattern": r"\b(task|build|deploy|run|execute|infrastructure|automat)\b",
        "agent": "kart",
        "priority": 10,
        "description": "Infrastructure and multi-step task work",
    },
    {
        "id": "rule-ganesha",
        "pattern": r"\b(debug|error|diagnose|fix|broken|obstacle|failing|crash)\b",
        "agent": "ganesha",
        "priority": 10,
        "description": "Debugging and obstacle removal",
    },
    {
        "id": "rule-jeles",
        "pattern": r"\b(search|find|retrieve|index|library|archive|look.?up)\b",
        "agent": "jeles",
        "priority": 10,
        "description": "Search and retrieval from KB",
    },
    {
        "id": "rule-grove",
        "pattern": r"\b(message|channel|send|notify|post|tell|grove|announce)\b",
        "agent": "grove",
        "priority": 10,
        "description": "Grove messaging and channel operations",
    },
    {
        "id": "rule-hanz",
        "pattern": r"\b(implement|refactor|write.?code|function|class|module|test)\b",
        "agent": "hanz",
        "priority": 8,
        "description": "Code implementation and technical work",
    },
    {
        "id": "rule-gerald",
        "pattern": r"\b(ponder|reflect|philosophi|reason|ethic|mean|understand)\b",
        "agent": "gerald",
        "priority": 6,
        "description": "Deep reasoning and philosophical questions",
    },
]


def seed(dry_run: bool = False) -> None:
    for rule in DEFAULT_RULES:
        if dry_run:
            print(f"[seed] Would write: {rule['id']} → {rule['agent']}")
            continue
        try:
            mcp_call("store_put", {
                "app_id": AGENT,
                "collection": COLLECTION,
                "record": rule,
            }, timeout=5)
            print(f"[seed] Written: {rule['id']} → {rule['agent']}")
        except Exception as e:
            print(f"[seed] Failed {rule['id']}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Seed default willow_route rules into SOIL store")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    seed(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run to verify output**

```bash
python3 -m willow.routing.seed_rules --dry-run
```

Expected: 6 rules printed, no store writes.

- [ ] **Step 3: Seed the store**

```bash
python3 -m willow.routing.seed_rules
```

Expected: 6 rules written to `willow/routing/rules`.

- [ ] **Step 4: Commit**

```bash
git add willow/routing/seed_rules.py
git commit -m "feat(routing): seed_rules.py — 6 default routing rules into SOIL store"
```

---

### Task 4: Wire `willow_route` in `sap/sap_mcp.py`

Replace the stub at line 1048.

- [ ] **Step 1: Add import at top of sap_mcp.py**

Find the imports section and add:

```python
try:
    from willow.routing.oracle import route as _routing_oracle
except ImportError:
    _routing_oracle = None
```

- [ ] **Step 2: Replace the stub**

```python
# OLD (line 1048):
elif name == "willow_route":
    result = {"routed_to": "willow", "note": "Message routing defaults to willow in portless mode"}

# NEW:
elif name == "willow_route":
    message = arguments.get("message", "")
    session_id = arguments.get("session_id", "")
    if _routing_oracle and message:
        result = _routing_oracle(message, session_id=session_id)
    else:
        result = {
            "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "prompt_snippet": message[:40],
            "routed_to": "willow",
            "rule_matched": "oracle-unavailable",
            "confidence": 0.5,
            "latency_ms": 0,
        }
```

- [ ] **Step 3: Test the MCP tool manually**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"willow_route","arguments":{"message":"debug the gleipnir rate limit","session_id":"test"}}}' | PYTHONPATH=/home/sean-campbell/github/willow-1.9 python3 /home/sean-campbell/github/willow-1.9/sap/sap_mcp.py
```

Expected output: JSON with `routed_to: "ganesha"`, `rule_matched: "rule-ganesha"`, `confidence: 1.0`.

- [ ] **Step 4: Commit**

```bash
git add sap/sap_mcp.py
git commit -m "feat(routing): wire willow_route oracle into sap_mcp.py — replaces stub"
```

---

### Task 5: `_run_route()` in `prompt_submit.py`

Inject routing decision as `[ROUTE]` context on every user prompt.

- [ ] **Step 1: Write failing test**

```python
# tests/test_routing/test_prompt_submit_route.py
import json
from io import StringIO
from unittest.mock import patch


def _run_submit(stdin_data: dict) -> str:
    import willow.fylgja.events.prompt_submit as m
    inp = StringIO(json.dumps(stdin_data))
    out = StringIO()
    with patch("sys.stdin", inp), patch("sys.stdout", out):
        try:
            m.main()
        except SystemExit:
            pass
    return out.getvalue()


def test_route_block_injected_in_output():
    with patch("willow.fylgja.events.prompt_submit._run_route") as mock_route:
        mock_route.return_value = None
        _run_submit({"session_id": "abc", "prompt": "debug the server"})
    mock_route.assert_called_once()


def test_route_block_prints_when_routed():
    decision = {
        "routed_to": "ganesha",
        "rule_matched": "rule-ganesha",
        "confidence": 1.0,
        "latency_ms": 2,
    }
    with patch("willow.fylgja.events.prompt_submit._get_route_decision", return_value=decision):
        out = _run_submit({"session_id": "abc", "prompt": "debug the server"})
    assert "[ROUTE]" in out
    assert "ganesha" in out
```

- [ ] **Step 2: Add `_run_route()` to `prompt_submit.py`**

Add import at top:

```python
try:
    from willow.routing.oracle import route as _routing_oracle
except ImportError:
    _routing_oracle = None
```

Add function before `main()`:

```python
def _get_route_decision(prompt: str, session_id: str) -> Optional[dict]:
    if not _routing_oracle or not prompt.strip():
        return None
    try:
        return _routing_oracle(prompt, session_id=session_id)
    except Exception:
        return None


def _run_route(prompt: str, session_id: str) -> None:
    decision = _get_route_decision(prompt, session_id)
    if not decision:
        return
    agent = decision.get("routed_to", "willow")
    rule = decision.get("rule_matched", "?")
    conf = decision.get("confidence", 0.0)
    latency = decision.get("latency_ms", 0)
    flag = " ⚑" if conf < 0.7 else ""
    print(
        f"[ROUTE] → {agent}  rule={rule}  conf={conf:.2f}  {latency}ms{flag}"
    )
```

Wire into `main()` after `_run_source_ring()`:

```python
    _run_source_ring(session_id)
    _run_route(prompt, session_id)   # ← add this line
    _run_anchor()
    ...
```

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/test_routing/ -v 2>&1 | tail -15
```

Expected: 9 passed.

- [ ] **Step 4: Commit**

```bash
git add willow/fylgja/events/prompt_submit.py tests/test_routing/test_prompt_submit_route.py
git commit -m "feat(routing): _run_route() in prompt_submit.py — injects [ROUTE] context on every prompt"
```

---

### Task 6: Full suite + push

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/test_fylgja/ tests/test_routing/ tests/adversarial/ --ignore=tests/adversarial/e2e -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 2: Final commit + push**

```bash
git add -A
git commit -m "feat(willow_route): Plan 4 complete — routing oracle live, rules seeded, dashboard feed wired"
git push origin master
```

---

## Self-Review

**Spec coverage:**
- ✅ `willow.routing_decisions` Postgres table (Task 1)
- ✅ `oracle.py` — rule-based fast path + Yggdrasil fallback (Task 2)
- ✅ `seed_rules.py` — 6 default rules in SOIL store (Task 3)
- ✅ `sap_mcp.py` — `willow_route` stub replaced (Task 4)
- ✅ `prompt_submit.py` — `_run_route()` injects `[ROUTE]` block (Task 5)
- ✅ Dashboard data shape: `{ts, prompt_snippet, routed_to, rule_matched, confidence, latency_ms}` written to Postgres

**Not in this plan:**
- SSE transport for Gemini CLI — separate small change to `safe-app-grove/grove/mcp_server.py`
- boot.py onboarding layer — Oakenscroll's scope

ΔΣ=42
