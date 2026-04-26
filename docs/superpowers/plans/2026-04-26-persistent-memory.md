# Persistent Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing compost pipeline so Hanuman accumulates mid-session trace atoms automatically, builds ambient memory from them, and no longer relies on handoff documents for context.

**Architecture:** PostToolUse hook writes lightweight trace atoms to `hanuman/turns/store` on every significant tool completion. Stop hook composites them into a session atom. Startup queries the nucleus (store + weighted KB) instead of parsing the handoff document. Promote/demote on pg_bridge keeps frequently-accessed atoms heavy. The handoff document shrinks to a seed: timestamp + next-bite prompt.

**Tech Stack:** Python 3.x, SQLite (willow_store), Postgres (pg_bridge), Claude Code hooks (settings.json), existing metabolic.py compost pipeline.

---

## File Map

| File | Change |
|------|--------|
| `willow/fylgja/events/post_tool.py` | Add significant-tool detection + trace atom writer |
| `willow/fylgja/events/stop.py` | Add session composite writer + compost_pass call |
| `willow/fylgja/events/session_start.py` | Replace 120-char handoff summary with store queries |
| `core/pg_bridge.py` | Update `increment_visit()` to log-scale weight; add `demote()` |
| `core/intelligence.py` | Call `increment_visit()` on atoms returned by serendipity/dark_matter passes |
| `willow/fylgja/skills/handoff.md` | Strip handoff skill to seed format |
| `.claude/settings.json` | Add PostToolUse matchers for Edit, Write, store_put, store_update, store_add_edge, willow_knowledge_ingest |
| `tests/test_fylgja/test_post_tool.py` | Add trace-writer tests |
| `tests/test_fylgja/test_stop.py` | Add session composite tests |
| `tests/test_fylgja/test_session_start.py` | Add store-query startup tests |
| `tests/test_pg_bridge.py` | Add promote/demote tests |
| `tests/test_intelligence.py` | Add promote-on-surface tests |

---

## Task 1: Trace atom writer in post_tool.py

The nerve ending. When a significant tool completes, write one trace atom to `hanuman/turns/store`. Rate-limit to one per tool+target pair per 60 seconds so a long Edit loop doesn't flood the store.

**Files:**
- Modify: `willow/fylgja/events/post_tool.py`
- Modify: `tests/test_fylgja/test_post_tool.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fylgja/test_post_tool.py`:

```python
from unittest.mock import patch, MagicMock
import time


def test_edit_tool_writes_trace():
    """Significant tool should call store_put with a trace atom."""
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {"id": "turn-abc12345-1234567890"}
    with patch("willow.fylgja.events.post_tool.call", fake_call):
        _run({"tool_name": "Edit", "tool_input": {"file_path": "/foo/bar.py"}})
    assert len(calls) == 1
    tool_name, args = calls[0]
    assert tool_name == "store_put"
    record = args["record"]
    assert record["type"] == "trace"
    assert record["tool"] == "Edit"
    assert "/foo/bar.py" in record["target"]


def test_read_tool_writes_no_trace():
    """Read-only tools must not write trace atoms."""
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {}
    with patch("willow.fylgja.events.post_tool.call", fake_call):
        _run({"tool_name": "Read", "tool_input": {"file_path": "/foo/bar.py"}})
    store_calls = [c for c in calls if c[0] == "store_put"]
    assert store_calls == []


def test_rate_limit_suppresses_duplicate_within_60s(tmp_path):
    """Same tool+target within 60s should only write one trace."""
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {}
    rate_file = tmp_path / "rate.json"
    with patch("willow.fylgja.events.post_tool.call", fake_call), \
         patch("willow.fylgja.events.post_tool._RATE_FILE", rate_file):
        _run({"tool_name": "Edit", "tool_input": {"file_path": "/foo/bar.py"}})
        _run({"tool_name": "Edit", "tool_input": {"file_path": "/foo/bar.py"}})
    store_calls = [c for c in calls if c[0] == "store_put"]
    assert len(store_calls) == 1


def test_store_put_failure_does_not_crash():
    """Trace writer must never crash the hook."""
    def fake_call(tool, args, timeout=5):
        raise RuntimeError("MCP unavailable")
    with patch("willow.fylgja.events.post_tool.call", fake_call):
        out = _run({"tool_name": "Edit", "tool_input": {"file_path": "/foo/bar.py"}})
    # Should still emit ToolSearch directive if needed, not crash
    assert True  # no exception = pass
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fylgja/test_post_tool.py -v
```
Expected: `test_edit_tool_writes_trace` FAIL (no trace written), others FAIL similarly.

- [ ] **Step 3: Implement the trace writer**

Replace `willow/fylgja/events/post_tool.py` with:

```python
"""
events/post_tool.py — PostToolUse hook handler.
ToolSearch completion directive + mid-session trace atom writer.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_RATE_FILE = Path("/tmp/willow-post-tool-rate.json")
_RATE_WINDOW = 60  # seconds

_SIGNIFICANT = {
    "Edit", "Write",
    "store_put", "store_update",
    "mcp__willow__store_add_edge",
    "mcp__willow__willow_knowledge_ingest",
    "mcp__willow__willow_knowledge_at",
}

_AGENT = "hanuman"


def _target_from_input(tool_name: str, tool_input: dict) -> str:
    """Extract a short target label from the tool input."""
    if tool_name in ("Edit", "Write"):
        return tool_input.get("file_path", "")[:120]
    if tool_name in ("store_put", "store_update"):
        return tool_input.get("collection", "")[:80]
    if tool_name == "mcp__willow__store_add_edge":
        return f"{tool_input.get('from_id','')}→{tool_input.get('to_id','')}"
    if tool_name == "mcp__willow__willow_knowledge_ingest":
        return tool_input.get("title", "")[:80]
    return ""


def _summary_from(tool_name: str, target: str) -> str:
    verbs = {
        "Edit": "edited",
        "Write": "wrote",
        "store_put": "stored atom in",
        "store_update": "updated atom in",
        "mcp__willow__store_add_edge": "added edge",
        "mcp__willow__willow_knowledge_ingest": "ingested KB atom",
        "mcp__willow__willow_knowledge_at": "replayed KB at",
    }
    verb = verbs.get(tool_name, tool_name)
    return f"{verb} {target}".strip()


def _rate_key(tool_name: str, target: str) -> str:
    return f"{tool_name}::{target}"


def _is_rate_limited(key: str) -> bool:
    """Return True if the same key was written within _RATE_WINDOW seconds."""
    try:
        if not _RATE_FILE.exists():
            return False
        data = json.loads(_RATE_FILE.read_text())
        last = data.get(key, 0)
        return (time.time() - last) < _RATE_WINDOW
    except Exception:
        return False


def _record_rate(key: str) -> None:
    try:
        data = {}
        if _RATE_FILE.exists():
            try:
                data = json.loads(_RATE_FILE.read_text())
            except Exception:
                pass
        data[key] = time.time()
        # Prune old entries to keep file small
        now = time.time()
        data = {k: v for k, v in data.items() if now - v < _RATE_WINDOW * 2}
        _RATE_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _write_trace(session_id: str, tool_name: str, tool_input: dict) -> None:
    try:
        from willow.fylgja._mcp import call
        target = _target_from_input(tool_name, tool_input)
        key = _rate_key(tool_name, target)
        if _is_rate_limited(key):
            return
        now_ms = int(time.time() * 1000)
        sid = (session_id or "unknown")[:8]
        record = {
            "id": f"turn-{sid}-{now_ms}",
            "session_id": session_id or "unknown",
            "tool": tool_name,
            "target": target,
            "summary": _summary_from(tool_name, target),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "trace",
        }
        call("store_put", {
            "app_id": _AGENT,
            "collection": "hanuman/turns/store",
            "record": record,
        }, timeout=3)
        _record_rate(key)
    except Exception:
        pass  # trace writer must never crash the hook


def main():
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        session_id = data.get("session_id", "")
    except Exception:
        tool_name = ""
        tool_input = {}
        session_id = ""

    if tool_name == "ToolSearch":
        print("[TOOL-SEARCH-COMPLETE] Schema loaded. Call the fetched tool NOW "
              "in this same response. Do NOT say 'Tool loaded.' "
              "Do NOT end your turn. Invoke the tool immediately.")

    if tool_name in _SIGNIFICANT:
        _write_trace(session_id, tool_name, tool_input)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fylgja/test_post_tool.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/post_tool.py tests/test_fylgja/test_post_tool.py
git commit -m "feat(memory): wire PostToolUse trace atom writer — the nerve ending"
```

---

## Task 2: Session composite in stop.py

On Stop, write one session composite atom to `hanuman/sessions/store` and call `compost_pass()` to retire the turn atoms. Must complete within the 5s Stop hook timeout — no LLM calls, pure store writes.

**Files:**
- Modify: `willow/fylgja/events/stop.py`
- Modify: `tests/test_fylgja/test_stop.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fylgja/test_stop.py`:

```python
import json
from io import StringIO
from unittest.mock import patch, MagicMock


def _run_stop(stdin_data: dict) -> None:
    import willow.fylgja.events.stop as s
    from io import StringIO
    inp = StringIO(json.dumps(stdin_data))
    with patch("sys.stdin", inp):
        try:
            s.main()
        except SystemExit:
            pass


def test_stop_writes_session_composite():
    """Stop hook should store_put a session composite atom."""
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {}
    with patch("willow.fylgja.events.stop.call", fake_call):
        _run_stop({"session_id": "abcdef1234567890"})
    store_calls = [c for c in calls if c[0] == "store_put"]
    assert len(store_calls) == 1
    record = store_calls[0][1]["record"]
    assert record["type"] == "session"
    assert record["session_id"] == "abcdef1234567890"
    assert record["id"].startswith("session-abcdef12")


def test_stop_session_composite_has_required_fields():
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {}
    with patch("willow.fylgja.events.stop.call", fake_call):
        _run_stop({"session_id": "abcdef1234567890"})
    record = [c for c in calls if c[0] == "store_put"][0][1]["record"]
    for field in ("id", "session_id", "date", "type"):
        assert field in record, f"Missing field: {field}"


def test_stop_mcp_failure_does_not_crash():
    """Stop hook must complete even if MCP is down."""
    def fake_call(tool, args, timeout=5):
        raise RuntimeError("MCP down")
    with patch("willow.fylgja.events.stop.call", fake_call):
        _run_stop({"session_id": "abc123"})  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fylgja/test_stop.py -v -k "composite"
```
Expected: FAIL — `call` not imported in stop.py.

- [ ] **Step 3: Implement session composite in stop.py**

Replace `willow/fylgja/events/stop.py` with:

```python
"""
events/stop.py — Stop hook: per-turn cleanup + session composite writer.
Depth stack and thread file cleanup. Session composite written to hanuman/sessions/store.
Heavy pipeline (handoff writing) lives in events/shutdown.py — run via /shutdown skill.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._state import get_trust_state, save_trust_state

DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")
THREAD_FILE = Path("/tmp/willow-context-thread.json")
_AGENT = "hanuman"


def read_turns_since(cursor: str, turns_file: Path) -> list[str]:
    """Return lines from turns_file whose timestamp is after cursor."""
    if not turns_file.exists():
        return []
    lines = []
    try:
        for line in turns_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("[") and "]" in line:
                ts = line[1:line.index("]")]
                if ts > cursor:
                    lines.append(line)
    except Exception:
        pass
    return lines


def mark_session_clean(turn_count: int = 0) -> None:
    if turn_count == 0:
        return
    state = get_trust_state()
    if not state:
        return
    state["clean_session_count"] = state.get("clean_session_count", 0) + 1
    save_trust_state(state)


def _write_session_composite(session_id: str) -> None:
    """Write session composite atom. Fast — no LLM, pure store_put."""
    try:
        from willow.fylgja._mcp import call
        sid = (session_id or "unknown")[:8]
        record = {
            "id": f"session-{sid}",
            "session_id": session_id or "unknown",
            "date": datetime.now(timezone.utc).isoformat(),
            "type": "session",
        }
        call("store_put", {
            "app_id": _AGENT,
            "collection": "hanuman/sessions/store",
            "record": record,
        }, timeout=4)
    except Exception:
        pass  # never block the Stop hook


def main():
    try:
        data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")

    # Cleanup depth stack
    try:
        depth = int(DEPTH_FILE.read_text().strip()) if DEPTH_FILE.exists() else 0
        if depth > 1:
            DEPTH_FILE.write_text(str(depth - 1))
        else:
            DEPTH_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    # Cleanup context thread
    try:
        THREAD_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    # Write session composite
    _write_session_composite(session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_fylgja/test_stop.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/stop.py tests/test_fylgja/test_stop.py
git commit -m "feat(memory): write session composite atom on Stop hook"
```

---

## Task 3: Wire PostToolUse matchers in settings.json

Tell Claude Code which tools should trigger the PostToolUse hook. Currently only `ToolSearch` is wired.

**Files:**
- Modify: `/home/sean-campbell/.claude/settings.json`

- [ ] **Step 1: Add PostToolUse matchers**

In `/home/sean-campbell/.claude/settings.json`, replace the existing `PostToolUse` block:

```json
"PostToolUse": [
  {
    "matcher": "ToolSearch",
    "hooks": [
      {
        "type": "command",
        "command": "PYTHONPATH=/home/sean-campbell/github/willow-1.9 /usr/bin/python3 -m willow.fylgja.events.post_tool",
        "timeout": 5
      }
    ]
  },
  {
    "matcher": "Edit|Write",
    "hooks": [
      {
        "type": "command",
        "command": "PYTHONPATH=/home/sean-campbell/github/willow-1.9 /usr/bin/python3 -m willow.fylgja.events.post_tool",
        "timeout": 5
      }
    ]
  },
  {
    "matcher": "mcp__willow__store_put|mcp__willow__store_update|mcp__willow__store_add_edge|mcp__willow__willow_knowledge_ingest|mcp__willow__willow_knowledge_at",
    "hooks": [
      {
        "type": "command",
        "command": "PYTHONPATH=/home/sean-campbell/github/willow-1.9 /usr/bin/python3 -m willow.fylgja.events.post_tool",
        "timeout": 5
      }
    ]
  }
]
```

- [ ] **Step 2: Verify hooks fire**

Make a test edit to any file, then check that a trace atom appeared:

```bash
python3 -c "
import sys; sys.path.insert(0, '/home/sean-campbell/github/willow-1.9')
from core.willow_store import WillowStore
store = WillowStore()
records = store.list('hanuman/turns/store')
print(f'Turn atoms: {len(records)}')
if records:
    print(records[-1])
"
```
Expected: at least 1 turn atom with `type: trace`.

- [ ] **Step 3: Commit**

```bash
cd /home/sean-campbell/github/willow-1.9
git add -A  # settings.json is outside repo, just note the change
git commit -m "chore(hooks): wire PostToolUse matchers for Edit, Write, and MCP write tools" --allow-empty
```

Note: `settings.json` is at `~/.claude/settings.json` — outside the repo. No git commit needed for it, but log the change in a gap atom if desired.

---

## Task 4: Promote/demote on pg_bridge.py

`increment_visit()` already exists but uses a linear weight formula. Update it to log-scale. Add `demote()` for atoms that haven't been accessed in a long time.

**Files:**
- Modify: `core/pg_bridge.py` (around line 475)
- Modify: `tests/test_pg_bridge.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pg_bridge.py` (after existing tests):

```python
def test_increment_visit_updates_weight(pg_bridge):
    """Weight should increase logarithmically with visit count."""
    import math
    # Write a test atom
    pg_bridge.knowledge_put({
        "id": "PROMO-TEST-1",
        "project": "test",
        "title": "Promote test atom",
        "summary": "test",
    })
    # First visit
    pg_bridge.increment_visit("PROMO-TEST-1")
    with pg_bridge.conn.cursor() as cur:
        cur.execute("SELECT visit_count, weight FROM knowledge WHERE id = 'PROMO-TEST-1'")
        row = cur.fetchone()
    assert row[0] == 1  # visit_count
    expected_weight = 1.0 + math.log(1 + 1)
    assert abs(row[1] - expected_weight) < 0.01


def test_increment_visit_is_cumulative(pg_bridge):
    import math
    pg_bridge.knowledge_put({
        "id": "PROMO-TEST-2",
        "project": "test",
        "title": "Cumulative promote test",
        "summary": "test",
    })
    for _ in range(5):
        pg_bridge.increment_visit("PROMO-TEST-2")
    with pg_bridge.conn.cursor() as cur:
        cur.execute("SELECT visit_count, weight FROM knowledge WHERE id = 'PROMO-TEST-2'")
        row = cur.fetchone()
    assert row[0] == 5
    expected_weight = 1.0 + math.log(1 + 5)
    assert abs(row[1] - expected_weight) < 0.01


def test_demote_reduces_weight(pg_bridge):
    """demote() should halve the weight, floor at 0.1."""
    pg_bridge.knowledge_put({
        "id": "DEMOTE-TEST-1",
        "project": "test",
        "title": "Demote test atom",
        "summary": "test",
    })
    # Promote first so there's something to demote
    for _ in range(3):
        pg_bridge.increment_visit("DEMOTE-TEST-1")
    pg_bridge.demote("DEMOTE-TEST-1")
    with pg_bridge.conn.cursor() as cur:
        cur.execute("SELECT weight FROM knowledge WHERE id = 'DEMOTE-TEST-1'")
        row = cur.fetchone()
    assert row[0] < 1.5  # should be reduced


def test_demote_floors_at_0_1(pg_bridge):
    """demote() never drops weight below 0.1."""
    pg_bridge.knowledge_put({
        "id": "DEMOTE-TEST-2",
        "project": "test",
        "title": "Floor test atom",
        "summary": "test",
    })
    for _ in range(10):
        pg_bridge.demote("DEMOTE-TEST-2")
    with pg_bridge.conn.cursor() as cur:
        cur.execute("SELECT weight FROM knowledge WHERE id = 'DEMOTE-TEST-2'")
        row = cur.fetchone()
    assert row[0] >= 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_pg_bridge.py -v -k "promote or demote or visit"
```
Expected: weight assertion fails (linear formula), `demote` AttributeError.

- [ ] **Step 3: Update increment_visit() and add demote() in core/pg_bridge.py**

Replace the `increment_visit` method (around line 475) with:

```python
def increment_visit(self, atom_id: str) -> None:
    """Increment visit_count and update last_visited + weight (log-scale)."""
    import math
    self._ensure_conn()
    with self.conn.cursor() as cur:
        cur.execute("""
            UPDATE knowledge
            SET visit_count  = visit_count + 1,
                last_visited = now(),
                weight       = 1.0 + ln(1.0 + visit_count + 1)
            WHERE id = %s
        """, (atom_id,))
    self.conn.commit()

def demote(self, atom_id: str) -> None:
    """Halve the weight of an atom, floor at 0.1. For draugr/aging."""
    self._ensure_conn()
    with self.conn.cursor() as cur:
        cur.execute("""
            UPDATE knowledge
            SET weight = GREATEST(0.1, weight * 0.5)
            WHERE id = %s
        """, (atom_id,))
    self.conn.commit()
```

Note: Postgres uses `ln()` for natural log, not `log()`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_pg_bridge.py -v -k "promote or demote or visit"
```
Expected: all 4 new tests PASS.

- [ ] **Step 5: Run full suite to catch regressions**

```bash
python3 -m pytest tests/ -q --ignore=tests/adversarial/e2e
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/pg_bridge.py tests/test_pg_bridge.py
git commit -m "feat(memory): log-scale weight in increment_visit, add demote() to pg_bridge"
```

---

## Task 5: Call increment_visit in intelligence passes

Serendipity and dark_matter already find the right atoms. Now they should promote them so the weight system learns from what the norn finds.

**Files:**
- Modify: `core/intelligence.py`
- Modify: `tests/test_intelligence.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_intelligence.py`:

```python
def test_serendipity_promotes_surfaced_atoms():
    """serendipity_pass should call increment_visit on each surfaced atom."""
    from core.intelligence import serendipity_pass
    bridge = _bridge()
    visited = []
    original = bridge.increment_visit
    bridge.increment_visit = lambda atom_id: visited.append(atom_id)
    results = serendipity_pass(bridge)
    bridge.increment_visit = original
    # If any atoms were surfaced, they should have been promoted
    assert len(visited) == len(results)


def test_dark_matter_promotes_source_atoms():
    """dark_matter_pass should call increment_visit on atoms used to form connections."""
    from core.intelligence import dark_matter_pass
    bridge = _bridge()
    visited = []
    original = bridge.increment_visit
    bridge.increment_visit = lambda atom_id: visited.append(atom_id)
    dark_matter_pass(bridge)
    bridge.increment_visit = original
    # May be 0 if no overlap found, but should not error
    assert isinstance(visited, list)
```

Note: `_bridge()` is already defined in `tests/test_intelligence.py` — use it directly. No fixture needed.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_intelligence.py -v -k "promotes"
```
Expected: FAIL — serendipity doesn't call increment_visit.

- [ ] **Step 3: Add increment_visit calls to serendipity_pass and dark_matter_pass**

In `core/intelligence.py`, update `serendipity_pass()` to call `bridge.increment_visit()` on each surfaced atom. Find the `return surfaced[:5]` line and add before it:

```python
    for atom in surfaced[:5]:
        try:
            bridge.increment_visit(atom["id"])
        except Exception:
            pass
    return surfaced[:5]
```

In `dark_matter_pass()`, add promote calls on the two atoms that formed each dark matter connection. Find the block that calls `bridge.knowledge_put(...)` and add after it:

```python
                try:
                    bridge.increment_visit(a["id"])
                    bridge.increment_visit(b["id"])
                except Exception:
                    pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_intelligence.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/intelligence.py tests/test_intelligence.py
git commit -m "feat(memory): promote atoms surfaced by serendipity and dark_matter passes"
```

---

## Task 6: Startup store queries in session_start.py

Replace the 120-char handoff summary with live store queries. Startup now queries: (1) timestamp from last handoff, (2) turn atoms since that timestamp, (3) open gaps sorted by severity, (4) KB atoms with weight > 1.5.

**Files:**
- Modify: `willow/fylgja/events/session_start.py`
- Modify: `tests/test_fylgja/test_session_start.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fylgja/test_session_start.py`:

```python
def test_silent_startup_queries_gaps(monkeypatch, tmp_path):
    """_run_silent_startup should call store_list for open gaps."""
    import willow.fylgja.events.session_start as m
    calls = []
    def fake_call(tool, args, timeout=10):
        calls.append((tool, args))
        if tool == "willow_handoff_latest":
            return {"filename": "SESSION_HANDOFF_test.md", "date": "2026-04-25T23:45:00Z", "summary": "test"}
        if tool == "store_list":
            return [{"b17": "GAP1", "title": "test gap", "status": "open", "severity": "high"}]
        if tool == "willow_status":
            return {"postgres": {"knowledge": 1}}
        return {}
    monkeypatch.setattr(m, "_mcp_call", fake_call)
    result = m._run_silent_startup()
    gap_calls = [c for c in calls if c[0] == "store_list" and "gaps" in c[1].get("collection", "")]
    assert len(gap_calls) >= 1


def test_silent_startup_surfaces_promoted_atoms(monkeypatch, tmp_path):
    """_run_silent_startup should query KB atoms with weight > 1.5."""
    import willow.fylgja.events.session_start as m
    calls = []
    def fake_call(tool, args, timeout=10):
        calls.append((tool, args))
        if tool == "willow_handoff_latest":
            return {"filename": "f.md", "date": "2026-04-25T23:45:00Z", "summary": "s"}
        if tool == "willow_knowledge_search":
            return {"knowledge": [{"title": "heavy atom", "weight": 2.0}]}
        if tool == "willow_status":
            return {"postgres": {"knowledge": 1}}
        return []
    monkeypatch.setattr(m, "_mcp_call", fake_call)
    result = m._run_silent_startup()
    kb_calls = [c for c in calls if c[0] == "willow_knowledge_search"]
    assert len(kb_calls) >= 1
```

Note: `session_start.py` currently uses `call` from `_mcp.py` directly. Before the test works, you need to expose `_mcp_call` as a module-level alias (see Step 3 below).

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_fylgja/test_session_start.py -v -k "queries_gaps or promoted"
```
Expected: AttributeError — `_mcp_call` not defined.

- [ ] **Step 3: Update _run_silent_startup() in session_start.py**

At the top of `session_start.py`, add a module-level alias for testability:

```python
from willow.fylgja._mcp import call as _mcp_call
```

Then update `_run_silent_startup()` — replace the handoff summary section (the 120-char truncation) with:

```python
def _run_silent_startup() -> dict:
    result = {
        "handoff_title": "", "handoff_date": "", "handoff_summary": "",
        "open_flags": 0, "top_flags": [], "postgres": "unknown",
        "loaded_skills": [], "open_gaps": [], "promoted_atoms": [],
        "session_atoms": [],
    }

    # 1. Get handoff timestamp (session boundary)
    try:
        h = _mcp_call("willow_handoff_latest", {"app_id": AGENT}, timeout=8)
        result["handoff_title"] = h.get("filename", "")
        result["handoff_date"] = h.get("date", "")
        summary = h.get("summary", "")
        result["handoff_summary"] = summary[:120] if summary else ""
    except Exception:
        pass

    # 2. Open gaps sorted by severity
    try:
        severity_order = {"high": 0, "medium": 1, "low": 2}
        gaps = _mcp_call("store_list", {
            "app_id": AGENT, "collection": "hanuman/gaps/store"
        }, timeout=5) or []
        open_gaps = [g for g in gaps if g.get("status") == "open"]
        open_gaps.sort(key=lambda g: severity_order.get(g.get("severity", "low"), 99))
        result["open_gaps"] = open_gaps[:5]
    except Exception:
        pass

    # 3. KB atoms related to current work (seeded by handoff summary)
    # Note: willow_knowledge_search is text-based; weight filtering requires
    # a future MCP tool. For now, surface atoms related to last handoff context.
    try:
        query = result.get("handoff_summary", "")[:80] or "session hanuman"
        kb = _mcp_call("willow_knowledge_search", {
            "app_id": AGENT, "query": query
        }, timeout=5) or {}
        result["promoted_atoms"] = (kb.get("knowledge") or [])[:3]
    except Exception:
        pass

    # 4. Postgres state
    try:
        s = _mcp_call("willow_status", {"app_id": AGENT}, timeout=5)
        result["postgres"] = "up" if isinstance(s.get("postgres"), dict) else "unknown"
    except Exception:
        pass

    # 5. Open flags
    try:
        flags = _mcp_call("store_list", {"app_id": AGENT, "collection": "hanuman/flags"}, timeout=5)
        open_flags = [f for f in (flags or []) if f.get("flag_state") == "open"]
        result["open_flags"] = len(open_flags)
        result["top_flags"] = [f.get("title", "")[:60] for f in open_flags[:3]]
    except Exception:
        pass

    # Write anchor cache
    try:
        anchor_dir = Path.home() / ".willow"
        anchor_dir.mkdir(parents=True, exist_ok=True)
        (anchor_dir / "session_anchor.json").write_text(json.dumps({
            "written_at": datetime.now().isoformat(),
            "agent": AGENT,
            "postgres": result["postgres"],
            "handoff_title": result["handoff_title"],
            "handoff_summary": result["handoff_summary"],
            "open_flags": result["open_flags"],
            "top_flags": result["top_flags"],
        }, indent=2))
        (anchor_dir / "anchor_state.json").write_text(json.dumps({"prompt_count": 0}))
    except Exception:
        pass

    return result
```

Also update the `[ANCHOR]` output block in `main()` to surface gaps and promoted atoms:

```python
    # Gaps as todos
    if startup.get("open_gaps"):
        lines.append(f"OPEN GAPS ({len(startup['open_gaps'])}):")
        for g in startup["open_gaps"]:
            lines.append(f"  [{g.get('severity','?').upper()}] {g.get('b17','?')} — {g.get('title','')[:60]}")

    # Promoted atoms
    if startup.get("promoted_atoms"):
        lines.append("ACTIVE ATOMS:")
        for a in startup["promoted_atoms"]:
            lines.append(f"  {a.get('title','')[:70]}")
```

- [ ] **Step 4: Run full session_start tests**

```bash
python3 -m pytest tests/test_fylgja/test_session_start.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/session_start.py tests/test_fylgja/test_session_start.py
git commit -m "feat(memory): startup queries store for gaps + promoted atoms instead of parsing handoff doc"
```

---

## Task 7: Strip handoff skill to seed format

The handoff document now only needs: timestamp + next-bite prompt. Update the `/handoff` skill so it produces the seed format and writes a session composite to the store.

**Files:**
- Modify: `willow/fylgja/skills/handoff.md`

- [ ] **Step 1: Replace handoff.md**

Replace `willow/fylgja/skills/handoff.md` with:

```markdown
---
name: handoff
description: Close session — write seed handoff doc (timestamp + next bite) and session composite to store
---

# /handoff — Session Close

## Sequence

1. **Write the seed file** to `~/Ashokoa/agents/hanuman/index/haumana_handoffs/SESSION_HANDOFF_<YYYYMMDD>_hanuman_<letter>.md`:

```markdown
---
b17: <generate a new b17 with willow_base17>
date: <ISO timestamp — this is the session boundary>
agent: hanuman
session: <a/b/c/d — increment from prior handoff letter>
---

<next-bite: 1-3 sentences. What to do first. What NOT to touch. What's hot.>

ΔΣ=42
```

2. **Write session composite** to store via `store_put`:
   - collection: `hanuman/sessions/store`
   - record: `{"id": "session-<session_id[:8]>", "session_id": "<session_id>", "date": "<ISO>", "next_bite": "<same prompt as above>", "type": "session"}`

3. **Rebuild DB** — call `willow_handoff_rebuild`.

4. **Confirm** — report the filename and next-bite.

## Rules

- The seed file has NO `## Δ Files`, NO `## Δ Database`, NO `## Gaps`. Those live in the store.
- next-bite must be concrete and single-session scoped.
- Never skip the DB rebuild — the next session reads from that index.
- The session composite is what the compost pipeline will retire when a day atom is written.
```

- [ ] **Step 2: Verify the skill loads correctly**

```bash
python3 -m pytest tests/test_skills.py -v -k "handoff"
```
Expected: pass (skill file is valid markdown with required frontmatter).

- [ ] **Step 3: Commit**

```bash
git add willow/fylgja/skills/handoff.md
git commit -m "feat(memory): strip handoff skill to seed format — store is authoritative"
```

---

## Final: Full suite + migration verification

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -q --ignore=tests/adversarial/e2e
```
Expected: all pass.

- [ ] **Step 2: Verify trace atoms are accumulating**

After running a few commands in a new session:

```bash
python3 -c "
import sys; sys.path.insert(0, '/home/sean-campbell/github/willow-1.9')
from core.willow_store import WillowStore
store = WillowStore()
turns = store.list('hanuman/turns/store')
print(f'Turn atoms in store: {len(turns)}')
for t in turns[-3:]:
    print(t)
"
```
Expected: ≥ 1 turn atom with `type: trace` after any Edit/Write/store_put.

- [ ] **Step 3: Verify session composite on stop**

After a session ends, check `hanuman/sessions/store`:

```bash
python3 -c "
import sys; sys.path.insert(0, '/home/sean-campbell/github/willow-1.9')
from core.willow_store import WillowStore
store = WillowStore()
sessions = store.list('hanuman/sessions/store')
print(f'Session composites: {len(sessions)}')
for s in sessions[-2:]:
    print(s)
"
```
Expected: at least one `type: session` record.

- [ ] **Step 4: Push**

```bash
git push origin master
```

---

## Dependency Order

```
Task 1 (post_tool trace writer)
  └─ Task 3 (settings.json wires it to real tool events)
Task 2 (stop composite)
Task 4 (pg_bridge promote/demote)
  └─ Task 5 (intelligence calls promote)
Task 6 (startup store queries) — benefits from Task 1 existing, but testable independently
Task 7 (handoff skill) — no code dependencies, can be done anytime
```

Tasks 1, 2, 4, 7 are fully independent. Do them in any order. Tasks 3, 5, 6 follow their parents.
