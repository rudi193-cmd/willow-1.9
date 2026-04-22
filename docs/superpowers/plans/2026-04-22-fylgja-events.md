# Fylgja Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `willow/fylgja/` — the Willow behavioral layer package — replacing all ad-hoc hook scripts in `~/.claude/hooks/` and `~/agents/hanuman/bin/` with a proper Python package wired to Willow 1.9 MCP.

**Architecture:** Five event handlers (one per Claude Code hook event) share a single MCP subprocess client (`_mcp.py`) and session state manager (`_state.py`). Each behavior within an event is an independent function with its own try/except — one failure never cascades. `install.py` rewrites the Claude Code settings.json hooks block to point at the new package.

**Tech Stack:** Python 3.11+, psycopg2, willow-mcp subprocess (JSON-RPC), pytest, Claude Code hook event system

---

## File Map

**Create:**
- `willow/fylgja/__init__.py`
- `willow/fylgja/_mcp.py` — subprocess JSON-RPC client (one function)
- `willow/fylgja/_state.py` — session + trust state read/write
- `willow/fylgja/events/__init__.py`
- `willow/fylgja/events/session_start.py` — SessionStart handler
- `willow/fylgja/events/prompt_submit.py` — UserPromptSubmit handler
- `willow/fylgja/events/pre_tool.py` — PreToolUse handler
- `willow/fylgja/events/post_tool.py` — PostToolUse handler
- `willow/fylgja/events/stop.py` — Stop handler
- `willow/fylgja/install.py` — writes Claude Code settings.json hooks block
- `tests/test_fylgja/__init__.py`
- `tests/test_fylgja/test_mcp.py`
- `tests/test_fylgja/test_state.py`
- `tests/test_fylgja/test_session_start.py`
- `tests/test_fylgja/test_prompt_submit.py`
- `tests/test_fylgja/test_pre_tool.py`
- `tests/test_fylgja/test_post_tool.py`
- `tests/test_fylgja/test_stop.py`
- `tests/test_fylgja/test_install.py`

**Modify:**
- `~/.claude/settings.json` — hooks block updated by `install.py` (not a code change)

**Old scripts (deactivated by install.py, not deleted):**
- `~/.claude/hooks/source.py`, `context-anchor.py`, `feedback-detector.py`, `continuity.py`, `continuity-close.py`, `compost.py`, `feedback_consumer.py`, `rebuild-handoff-db.py`
- `~/agents/hanuman/bin/session-index-builder.py`, `jeles-pipeline.py`, `pretool-mcp-guard.py`, `kb-first-read.py`, `wwsdn.py`, `turns-logger.py`, `build-continue.py`, `posttool-toolsearch.py`, `ingot_observer.py`

---

### Task 1: Package scaffolding

**Files:**
- Create: `willow/fylgja/__init__.py`
- Create: `willow/fylgja/events/__init__.py`
- Create: `tests/test_fylgja/__init__.py`

- [ ] **Step 1: Create package directories and init files**

```bash
mkdir -p willow/fylgja/events willow/fylgja/safety willow/fylgja/skills willow/fylgja/rules
touch willow/fylgja/__init__.py willow/fylgja/events/__init__.py
mkdir -p tests/test_fylgja
touch tests/test_fylgja/__init__.py
```

- [ ] **Step 2: Write `willow/fylgja/__init__.py`**

```python
"""
willow.fylgja — Willow behavioral layer.
Hooks, safety, and skills for Willow 1.9.
b17: FYLG1 ΔΣ=42
"""
__version__ = "1.9.0"
```

- [ ] **Step 3: Verify pytest can discover the package**

```bash
cd /home/sean-campbell/github/willow-1.9
python -c "import willow.fylgja; print(willow.fylgja.__version__)"
```
Expected: `1.9.0`

- [ ] **Step 4: Commit**

```bash
git add willow/fylgja/ tests/test_fylgja/
git commit -m "feat(fylgja): package scaffold — willow/fylgja/ and test directory"
```

---

### Task 2: `_mcp.py` — shared MCP subprocess client

**Files:**
- Create: `willow/fylgja/_mcp.py`
- Create: `tests/test_fylgja/test_mcp.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fylgja/test_mcp.py
import json
import subprocess
from unittest.mock import patch, MagicMock
from willow.fylgja._mcp import call


def _mock_run(payload_str, want_tool, response):
    """Helper: mock subprocess.run to return response when want_tool is called."""
    def fake_run(cmd, input, capture_output, text, timeout):
        data = json.loads(input)
        assert data["params"]["name"] == want_tool
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps({"result": response})
        result.stderr = ""
        return result
    return fake_run


def test_call_returns_result_dict():
    with patch("subprocess.run", side_effect=_mock_run(
        None, "willow_status", {"postgres": "up"}
    )):
        result = call("willow_status", {"app_id": "hanuman"})
    assert result == {"postgres": "up"}


def test_call_timeout_returns_error():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
        result = call("willow_status", {"app_id": "hanuman"}, timeout=10)
    assert result["error"] == "timeout"
    assert result["tool"] == "willow_status"


def test_call_nonzero_exit_returns_error():
    mock = MagicMock()
    mock.returncode = 1
    mock.stdout = ""
    mock.stderr = "connection refused"
    with patch("subprocess.run", return_value=mock):
        result = call("willow_status", {"app_id": "hanuman"})
    assert result["error"] == "subprocess_error"


def test_call_sends_correct_jsonrpc_envelope():
    captured = {}
    def fake_run(cmd, input, capture_output, text, timeout):
        captured["payload"] = json.loads(input)
        m = MagicMock()
        m.returncode = 0
        m.stdout = json.dumps({"result": {}})
        m.stderr = ""
        return m
    with patch("subprocess.run", side_effect=fake_run):
        call("store_put", {"collection": "test", "record": {"id": "x"}})
    assert captured["payload"]["jsonrpc"] == "2.0"
    assert captured["payload"]["method"] == "tools/call"
    assert captured["payload"]["params"]["name"] == "store_put"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sean-campbell/github/willow-1.9
python -m pytest tests/test_fylgja/test_mcp.py -v
```
Expected: `ImportError: cannot import name 'call' from 'willow.fylgja._mcp'`

- [ ] **Step 3: Write `willow/fylgja/_mcp.py`**

```python
"""
_mcp.py — Willow MCP subprocess client.
Single entry point for all hook→MCP calls.
"""
import json
import os
import subprocess
from pathlib import Path

_WILLOW_MCP = Path(os.environ.get(
    "WILLOW_MCP_BIN",
    str(Path.home() / ".local" / "bin" / "willow-mcp")
))


def call(tool_name: str, arguments: dict, timeout: int = 10) -> dict:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
    try:
        result = subprocess.run(
            [str(_WILLOW_MCP)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return {"error": "subprocess_error", "stderr": result.stderr[:200], "tool": tool_name}
        data = json.loads(result.stdout)
        return data.get("result", data)
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "tool": tool_name}
    except Exception as e:
        return {"error": str(e), "tool": tool_name}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_fylgja/test_mcp.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/_mcp.py tests/test_fylgja/test_mcp.py
git commit -m "feat(fylgja): _mcp.py — shared subprocess JSON-RPC client"
```

---

### Task 3: `_state.py` — session and trust state

**Files:**
- Create: `willow/fylgja/_state.py`
- Create: `tests/test_fylgja/test_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fylgja/test_state.py
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest


def _write_session(path, data):
    path.write_text(json.dumps(data))


def test_get_turn_count_returns_zero_when_no_file(tmp_path):
    with patch("willow.fylgja._state.SESSION_FILE", tmp_path / "session.json"):
        from willow.fylgja._state import get_turn_count
        assert get_turn_count() == 0


def test_get_turn_count_returns_value_from_file(tmp_path):
    f = tmp_path / "session.json"
    _write_session(f, {"turn_count": 7})
    with patch("willow.fylgja._state.SESSION_FILE", f):
        from importlib import reload
        import willow.fylgja._state as s
        reload(s)
        with patch.object(s, "SESSION_FILE", f):
            assert s.get_turn_count() == 7


def test_is_first_turn_true_at_zero(tmp_path):
    with patch("willow.fylgja._state.SESSION_FILE", tmp_path / "missing.json"):
        from willow.fylgja._state import is_first_turn
        assert is_first_turn() is True


def test_save_and_load_trust_state(tmp_path):
    trust_file = tmp_path / "trust-state.json"
    state = {"current_level": 3, "clean_session_count": 5}
    with patch("willow.fylgja._state.TRUST_STATE", trust_file):
        from willow.fylgja import _state as s
        s.save_trust_state(state)
        loaded = s.get_trust_state()
    assert loaded["current_level"] == 3
    assert loaded["clean_session_count"] == 5


def test_get_trust_state_returns_empty_when_missing(tmp_path):
    with patch("willow.fylgja._state.TRUST_STATE", tmp_path / "missing.json"):
        from willow.fylgja._state import get_trust_state
        assert get_trust_state() == {}
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_fylgja/test_state.py -v
```
Expected: `ImportError: cannot import name 'get_turn_count'`

- [ ] **Step 3: Write `willow/fylgja/_state.py`**

```python
"""
_state.py — Session and trust state management.
All hooks read/write state through here.
"""
import json
import os
from pathlib import Path
from typing import Optional

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
SESSION_FILE = Path(f"/tmp/willow-session-{AGENT}.json")
TRUST_STATE = Path.home() / "agents" / AGENT / "cache" / "trust-state.json"


def get_turn_count() -> int:
    try:
        if SESSION_FILE.exists():
            return json.loads(SESSION_FILE.read_text()).get("turn_count", 0)
    except Exception:
        pass
    return 0


def is_first_turn() -> bool:
    return get_turn_count() <= 1


def get_trust_state() -> dict:
    try:
        if TRUST_STATE.exists():
            return json.loads(TRUST_STATE.read_text())
    except Exception:
        pass
    return {}


def save_trust_state(state: dict) -> None:
    TRUST_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TRUST_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(TRUST_STATE)


def get_session_value(key: str, default=None):
    try:
        if SESSION_FILE.exists():
            return json.loads(SESSION_FILE.read_text()).get(key, default)
    except Exception:
        pass
    return default


def set_session_value(key: str, value) -> None:
    try:
        state = {}
        if SESSION_FILE.exists():
            state = json.loads(SESSION_FILE.read_text())
        state[key] = value
        SESSION_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def get_consent_level() -> str:
    return get_session_value("consent_level", "unidentified")


def set_consent_level(level: str) -> None:
    set_session_value("consent_level", level)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_fylgja/test_state.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/_state.py tests/test_fylgja/test_state.py
git commit -m "feat(fylgja): _state.py — session and trust state management"
```

---

### Task 4: `events/session_start.py` — SessionStart handler

**Files:**
- Create: `willow/fylgja/events/session_start.py`
- Create: `tests/test_fylgja/test_session_start.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_session_start.py
import json
import sys
from io import StringIO
from unittest.mock import patch, MagicMock
from pathlib import Path


def _run_handler(stdin_data: dict) -> str:
    """Run session_start.main() with given stdin, capture stdout."""
    import willow.fylgja.events.session_start as m
    inp = StringIO(json.dumps(stdin_data))
    out = StringIO()
    with patch("sys.stdin", inp), patch("sys.stdout", out):
        try:
            m.main()
        except SystemExit:
            pass
    return out.getvalue()


def test_outputs_additional_context_json():
    output = _run_handler({"session_id": "abc123"})
    data = json.loads(output)
    assert "hookSpecificOutput" in data
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "additionalContext" in data["hookSpecificOutput"]


def test_additional_context_contains_index_line():
    output = _run_handler({"session_id": "abc123"})
    data = json.loads(output)
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "[INDEX]" in ctx


def test_clears_stale_context_thread(tmp_path):
    thread_file = tmp_path / "context-thread.json"
    thread_file.write_text('{"items": []}')
    import willow.fylgja.events.session_start as m
    with patch.object(m, "THREAD_FILE", thread_file):
        _run_handler({"session_id": "abc123"})
    assert not thread_file.exists()
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_fylgja/test_session_start.py -v
```
Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Write `willow/fylgja/events/session_start.py`**

```python
"""
events/session_start.py — SessionStart hook handler.
Collects hardware state, calls willow_status, registers JELES.
Outputs additionalContext JSON for the model.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from willow.fylgja._mcp import call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
INDEX_DIR = Path.home() / "agents" / AGENT / "index"
THREAD_FILE = Path(f"/tmp/willow-context-thread.json")


def _clear_stale_thread():
    try:
        if THREAD_FILE.exists():
            THREAD_FILE.unlink()
    except Exception:
        pass


def _scan_hardware() -> tuple[list[str], list[str]]:
    """Returns (summary_parts, alerts)."""
    summary, alerts = [], []

    # Drives
    try:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,FSTYPE,SIZE,MOUNTPOINT,LABEL,TYPE"],
            capture_output=True, text=True, timeout=5
        )
        hw = json.loads(r.stdout) if r.returncode == 0 else {}
        ntfs_unmounted = []

        def _gb(s):
            s = (s or "").upper()
            if s.endswith("G"): return float(s[:-1])
            if s.endswith("T"): return float(s[:-1]) * 1024
            return 0

        def _walk(devices):
            for d in devices:
                if d.get("fstype") == "ntfs" and not d.get("mountpoint"):
                    if _gb(d.get("size", "0")) >= 10:
                        ntfs_unmounted.append(d["name"])
                if d.get("children"):
                    _walk(d["children"])

        _walk(hw.get("blockdevices", []))
        if ntfs_unmounted:
            alerts.append(f"NTFS unmounted: {', '.join(ntfs_unmounted)}")
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        (INDEX_DIR / "hardware.json").write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "lsblk": hw,
            "ntfs_unmounted": ntfs_unmounted,
        }, indent=2))
        summary.append("drives")
    except Exception as e:
        alerts.append(f"hardware: {e}")

    # Thermals
    try:
        zones = []
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            try:
                temp = int((zone / "temp").read_text().strip()) / 1000
                type_ = (zone / "type").read_text().strip()
                zones.append({"zone": zone.name, "type": type_, "temp_c": round(temp, 1)})
                if temp > 85:
                    alerts.append(f"HIGH TEMP: {type_} {temp}°C")
            except Exception:
                pass
        if zones:
            peak = max(z["temp_c"] for z in zones)
            summary.append(f"{peak}°C")
            (INDEX_DIR / "thermals.json").write_text(json.dumps({
                "timestamp": datetime.now().isoformat(), "zones": zones
            }, indent=2))
    except Exception as e:
        alerts.append(f"thermals: {e}")

    # Memory
    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k.strip() in ("MemTotal", "MemAvailable"):
                mem[k.strip()] = v.strip()
        if "MemAvailable" in mem and "MemTotal" in mem:
            avail = int(mem["MemAvailable"].split()[0])
            total = int(mem["MemTotal"].split()[0])
            summary.append(f"{round(avail/total*100)}% RAM free")
        (INDEX_DIR / "memory.json").write_text(json.dumps({
            "timestamp": datetime.now().isoformat(), **mem
        }, indent=2))
    except Exception as e:
        alerts.append(f"memory: {e}")

    return summary, alerts


def _check_willow_status() -> str:
    try:
        result = call("willow_status", {"app_id": AGENT}, timeout=5)
        pg = result.get("postgres", "unknown")
        if isinstance(pg, dict):
            return "postgres=up"
        return f"postgres={pg}"
    except Exception:
        return "postgres=unknown"


def _register_jeles(session_id: str) -> None:
    try:
        import glob
        projects_dir = Path.home() / ".claude" / "projects"
        jsonl_files = list(projects_dir.rglob(f"{session_id}.jsonl"))
        if jsonl_files:
            jsonl_path = str(jsonl_files[0])
            call("willow_jeles_register", {
                "app_id": AGENT,
                "agent": AGENT,
                "jsonl_path": jsonl_path,
                "session_id": session_id,
            }, timeout=10)
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")

    _clear_stale_thread()

    summary, alerts = _scan_hardware()
    pg_status = _check_willow_status()
    summary.append(pg_status)

    if session_id:
        _register_jeles(session_id)

    lines = ["[INDEX] " + " · ".join(summary)]
    for a in alerts:
        lines.append(f"  ⚠ {a}")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_fylgja/test_session_start.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/session_start.py tests/test_fylgja/test_session_start.py
git commit -m "feat(fylgja): events/session_start.py — hardware scan, willow_status, jeles register"
```

---

### Task 5: `events/prompt_submit.py` — UserPromptSubmit handler

**Files:**
- Create: `willow/fylgja/events/prompt_submit.py`
- Create: `tests/test_fylgja/test_prompt_submit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_prompt_submit.py
import json
import sys
from io import StringIO
from unittest.mock import patch, MagicMock, call as mcall
from willow.fylgja.events.prompt_submit import (
    detect_feedback,
    should_anchor,
    get_active_task,
)


def test_detect_feedback_finds_hook_error():
    results = detect_feedback("the hooks are broken and not firing")
    assert any(r["type"] == "technical" for r in results)


def test_detect_feedback_finds_background_pattern():
    results = detect_feedback("you should run that in the background")
    assert any(r["type"] == "process" for r in results)


def test_detect_feedback_empty_on_clean_prompt():
    results = detect_feedback("what is the weather today")
    assert results == []


def test_should_anchor_true_at_interval(tmp_path):
    state_file = tmp_path / "anchor_state.json"
    state_file.write_text(json.dumps({"prompt_count": 9}))
    with patch("willow.fylgja.events.prompt_submit.STATE_FILE", state_file):
        assert should_anchor() is True


def test_should_anchor_false_before_interval(tmp_path):
    state_file = tmp_path / "anchor_state.json"
    state_file.write_text(json.dumps({"prompt_count": 3}))
    with patch("willow.fylgja.events.prompt_submit.STATE_FILE", state_file):
        assert should_anchor() is False


def test_get_active_task_returns_none_when_no_file(tmp_path):
    with patch("willow.fylgja.events.prompt_submit.ACTIVE_BUILD_FILE",
               tmp_path / "missing.json"):
        assert get_active_task() is None


def test_get_active_task_returns_label(tmp_path):
    f = tmp_path / "build.json"
    f.write_text(json.dumps({"label": "Implementing Fylgja events"}))
    with patch("willow.fylgja.events.prompt_submit.ACTIVE_BUILD_FILE", f):
        assert get_active_task() == "Implementing Fylgja events"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_fylgja/test_prompt_submit.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write `willow/fylgja/events/prompt_submit.py`**

```python
"""
events/prompt_submit.py — UserPromptSubmit hook handler.
Source ring, context anchor, feedback detection, turn logging,
build-continue directive, identity/consent load.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._mcp import call
from willow.fylgja._state import (
    AGENT, SESSION_FILE, TRUST_STATE,
    get_turn_count, is_first_turn, get_trust_state, save_trust_state,
    set_session_value,
)

ANCHOR_INTERVAL = 10
ANCHOR_CACHE = Path.home() / ".willow" / "session_anchor.json"
STATE_FILE = Path.home() / ".willow" / "anchor_state.json"
TURNS_FILE = Path.home() / "agents" / AGENT / "cache" / "turns.txt"
ACTIVE_BUILD_FILE = Path("/tmp/hanuman-active-build.json")

TRUST_LEVELS = {0: "OBSERVER", 1: "WORKER", 2: "OPERATOR", 3: "ENGINEER", 4: "ARCHITECT"}
PERMISSION_LEVELS = {
    "local_llm": 1, "cloud_llm_free": 1, "conversation_storage": 1,
    "filesystem_watch": 2, "willow_kb_read": 2, "export_data": 2,
    "willow_kb_write": 3, "filesystem_write": 3,
}
HANUMAN_PERMISSIONS = ["willow_kb_read", "willow_kb_write", "filesystem_write", "local_llm"]
ADVANCEMENT_THRESHOLDS = {0: 3, 1: 5, 2: 10, 3: None}

FEEDBACK_PATTERNS = [
    (r"run.{0,20}(in the |in )background", "process", "Run tasks in the background"),
    (r"(hook|hooks).{0,30}(error|broken|not working|failing)", "technical", "Hook error detected"),
    (r"(redundant|duplicate|same).{0,20}agent", "discipline", "Launched redundant agents"),
    (r"(too much|stop).{0,20}(noise|chatter|output|verbosity)", "process", "Reduce output verbosity"),
    (r"(wrong|incorrect).{0,20}(subagent|agent type|model)", "discipline", "Wrong subagent type used"),
    (r"(permission|denied|blocked).{0,30}(bash|tool|write|edit)", "technical", "Tool permission blocked unexpectedly"),
    (r"(schema|column|table).{0,30}(missing|error|not found)", "technical", "Database schema error"),
]


def detect_feedback(prompt: str) -> list[dict]:
    found, seen = [], set()
    for pattern, fb_type, rule in FEEDBACK_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE) and rule not in seen:
            seen.add(rule)
            m = re.search(pattern, prompt, re.IGNORECASE)
            excerpt = prompt[max(0, m.start()-40):min(len(prompt), m.end()+80)].strip()
            found.append({"type": fb_type, "rule": rule, "excerpt": excerpt})
    return found


def should_anchor() -> bool:
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"prompt_count": 0}
        count = state.get("prompt_count", 0) + 1
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"prompt_count": count}))
        return count % ANCHOR_INTERVAL == 0
    except Exception:
        return False


def get_active_task() -> str | None:
    try:
        if ACTIVE_BUILD_FILE.exists():
            data = json.loads(ACTIVE_BUILD_FILE.read_text())
            return data.get("label", "").strip() or None
    except Exception:
        pass
    return None


def _run_source_ring(session_id: str) -> None:
    if not is_first_turn():
        return
    state = get_trust_state()
    if not state:
        level = max(PERMISSION_LEVELS.get(p, 1) for p in HANUMAN_PERMISSIONS)
        state = {
            "agent": AGENT, "current_level": min(level, 3),
            "level_name": TRUST_LEVELS.get(min(level, 3), "ENGINEER"),
            "permissions": HANUMAN_PERMISSIONS,
            "session_count": 0, "clean_session_count": 0,
            "infraction_count": 0, "advancement_candidate": False,
        }
    state["session_count"] = state.get("session_count", 0) + 1
    threshold = ADVANCEMENT_THRESHOLDS.get(state.get("current_level", 2))
    clean = state.get("clean_session_count", 0)
    if threshold and clean >= threshold and not state.get("advancement_candidate"):
        state["advancement_candidate"] = True
        current = state.get("current_level", 2)
        target = current + 1
        print(
            f"[SOURCE_RING — ADVANCEMENT READY]\n"
            f"  Agent: {AGENT}  |  {TRUST_LEVELS.get(current,'?')} → {TRUST_LEVELS.get(target,'?')}\n"
            f"  Clean sessions: {clean} / {threshold}\n"
            f"  Confirm (advance) / Deny (hold) / Wait (ask later)"
        )
    save_trust_state(state)


def _run_anchor() -> None:
    if not should_anchor():
        return
    try:
        anchor = json.loads(ANCHOR_CACHE.read_text()) if ANCHOR_CACHE.exists() else {}
        if not anchor:
            return
        lines = ["[ANCHOR]"]
        if anchor.get("agent"):
            lines.append(f"agent={anchor['agent']}  postgres={anchor.get('postgres','?')}")
        if anchor.get("handoff_title"):
            lines.append(f"last handoff: {anchor['handoff_title']}")
        if anchor.get("open_flags") is not None:
            lines.append(f"open flags: {anchor['open_flags']}")
        if anchor.get("handoff_summary"):
            lines.append(anchor["handoff_summary"][:200])
        print("\n".join(lines))
    except Exception:
        pass


def _run_feedback(prompt: str, session_id: str) -> None:
    if not prompt or len(prompt.strip()) < 8:
        return
    feedback = detect_feedback(prompt)
    for item in feedback:
        try:
            call("store_put", {
                "app_id": AGENT,
                "collection": "hanuman/feedback",
                "record": {
                    "id": f"fb-{session_id[:8]}-{abs(hash(item['rule'])) % 99999:05d}",
                    "type": item["type"],
                    "rule": item["rule"],
                    "excerpt": item["excerpt"],
                    "session_id": session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",
                },
            }, timeout=5)
        except Exception:
            pass


def _log_turn(prompt: str, session_id: str) -> None:
    try:
        TURNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        entry = f"[{ts}] [{session_id[:8]}] HUMAN\n{prompt}\n---\n"
        with open(TURNS_FILE, "a") as f:
            f.write(entry)
    except Exception:
        pass


def _run_build_continue() -> None:
    task = get_active_task()
    if not task:
        return
    print(
        f"[BUILD-CONTINUE] Active work in progress: {task[:120]}\n"
        f"[BUILD-CONTINUE] Keep building. Do not stop to report status or ask for direction.\n"
        f"[BUILD-CONTINUE] Only pause if blocked or if Sean asks a question."
    )


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "unknown")
    prompt = data.get("prompt", "")

    _run_source_ring(session_id)
    _run_anchor()
    _run_feedback(prompt, session_id)
    _log_turn(prompt, session_id)
    _run_build_continue()

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_fylgja/test_prompt_submit.py -v
```
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/prompt_submit.py tests/test_fylgja/test_prompt_submit.py
git commit -m "feat(fylgja): events/prompt_submit.py — source ring, anchor, feedback, turns, build-continue"
```

---

### Task 6: `events/pre_tool.py` — PreToolUse handler

**Files:**
- Create: `willow/fylgja/events/pre_tool.py`
- Create: `tests/test_fylgja/test_pre_tool.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_pre_tool.py
import json
from willow.fylgja.events.pre_tool import (
    check_bash_block,
    check_agent_block,
    check_kb_first,
)
from unittest.mock import patch


def test_blocks_psql():
    reason = check_bash_block("psql -U willow willow_19")
    assert reason is not None
    assert "MCP" in reason


def test_blocks_cat():
    reason = check_bash_block("cat /home/sean/somefile.py")
    assert reason is not None
    assert "Read" in reason


def test_blocks_ls():
    reason = check_bash_block("ls /home/sean/")
    assert reason is not None
    assert "Glob" in reason


def test_allows_git():
    reason = check_bash_block("git log --oneline -10")
    assert reason is None


def test_allows_pytest():
    reason = check_bash_block("python -m pytest tests/ -v")
    assert reason is None


def test_blocks_explore_subagent():
    reason = check_agent_block("Explore")
    assert reason is not None
    assert "MCP" in reason


def test_allows_general_purpose_agent():
    reason = check_agent_block("general-purpose")
    assert reason is None


def test_kb_first_returns_advisory_when_record_found():
    mock_result = [{"id": "abc", "title": "settings.json", "collection": "hanuman/file-index"}]
    with patch("willow.fylgja.events.pre_tool._mcp_store_search", return_value=mock_result):
        advisory = check_kb_first("/home/sean/.claude/settings.json")
    assert advisory is not None
    assert "KB-FIRST" in advisory


def test_kb_first_returns_none_when_no_record():
    with patch("willow.fylgja.events.pre_tool._mcp_store_search", return_value=[]):
        advisory = check_kb_first("/some/unknown/file.py")
    assert advisory is None
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_fylgja/test_pre_tool.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write `willow/fylgja/events/pre_tool.py`**

```python
"""
events/pre_tool.py — PreToolUse hook handler.
MCP guard (Bash + Agent), KB-first read advisory, WWSDN neighborhood scan.
Safety hard stop gate (stub — wired when safety subsystem is built).
"""
import json
import os
import re
import sys
from pathlib import Path

from willow.fylgja._mcp import call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
MAX_DEPTH = int(os.environ.get("WILLOW_AGENT_MAX_DEPTH", "3"))
DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")

BASH_BLOCKS = [
    (r"\bpsql\b|\bpg_dump\b|\bpg_restore\b",
     "Direct Postgres access is not allowed. Use MCP: store_get / store_list for store reads, "
     "willow_knowledge_search for KB reads, store_put / willow_knowledge_ingest for writes."),
    (r"\bsqlite3\b",
     "Direct SQLite access is not allowed. Use MCP: store_get / store_list, or Glob + Read for schema inspection."),
    (r"\bcat\s+[\w/~\.\"]",
     "File read → use the Read tool."),
    (r"(?:^|[;&])\s*grep\s+|(?:^|[;&])\s*rg\s+",
     "Content search → use the Grep tool."),
    (r"\bfind\s+[\w/~\.\"]",
     "File search → use the Glob tool."),
    (r"^\s*ls\s*$|\bls\s+[\w/~\.\"]",
     "File listing / discovery → use the Glob tool."),
]

F5_PROSE_TOOLS = {
    "mcp__willow__store_put": "record",
    "mcp__willow__store_update": "record",
    "mcp__willow__willow_knowledge_ingest": "content",
}


def check_bash_block(command: str) -> str | None:
    for pattern, reason in BASH_BLOCKS:
        if re.search(pattern, command, re.MULTILINE):
            return reason
    return None


def check_agent_block(subagent_type: str) -> str | None:
    if subagent_type == "Explore":
        return ("Explore subagent is blocked. Use MCP: store_search, willow_knowledge_search, "
                "store_get, store_list — or Glob/Grep/Read directly.")
    return None


def _read_depth() -> int:
    try:
        return int(DEPTH_FILE.read_text().strip()) if DEPTH_FILE.exists() else 0
    except Exception:
        return 0


def _write_depth(n: int) -> None:
    try:
        if n <= 0:
            DEPTH_FILE.unlink(missing_ok=True)
        else:
            DEPTH_FILE.write_text(str(n))
    except Exception:
        pass


def _mcp_store_search(collection: str, query: str) -> list:
    result = call("store_search", {"app_id": AGENT, "collection": collection, "query": query}, timeout=3)
    if isinstance(result, list):
        return result
    return []


def check_kb_first(file_path: str) -> str | None:
    try:
        filename = Path(file_path).name
        records = _mcp_store_search("hanuman/file-index", filename)
        if records:
            r = records[0]
            return (
                f"[KB-FIRST] Store record exists for this file.\n"
                f"  id: {r.get('id','?')}  type: {r.get('type','?')}\n"
                f"  title: {r.get('title','?')}\n"
                f"  collection: {r.get('collection','?')}\n"
                f"  Check the store record before reading the full file."
            )
    except Exception:
        pass
    return None


def check_f5_canon(tool_name: str, tool_input: dict) -> str | None:
    field = F5_PROSE_TOOLS.get(tool_name)
    if not field:
        return None
    content = tool_input.get(field, "")
    if not isinstance(content, str) or not content.strip():
        return None
    c = content.strip()
    looks_like_path = c.startswith("/") and len(c) < 300 and "\n" not in c
    if looks_like_path:
        return None
    looks_like_prose = len(c) > 150 or c.count("\n") > 2 or c.count(". ") > 1
    if looks_like_prose:
        preview = c[:80].replace("\n", " ")
        return (
            f"\n[WWSDN/F5] ⚠  CANON DRIFT — content is prose, not a file path\n"
            f"[WWSDN/F5]    tool: {tool_name}  field: {field}\n"
            f"[WWSDN/F5]    content ({len(c)} chars): \"{preview}...\"\n"
            f"[WWSDN/F5]    fix: write content to a file, store the path instead\n"
        )
    return None


def _run_wwsdn(tool_name: str, tool_input: dict) -> None:
    f5 = check_f5_canon(tool_name, tool_input)
    if f5:
        print(json.dumps({"decision": "block", "reason": f5}))
        sys.exit(0)

    signal = " ".join(
        v[:100] for v in tool_input.values()
        if isinstance(v, str) and len(v) > 3
    )[:200]
    if not signal:
        return

    try:
        results = call("willow_knowledge_search", {
            "app_id": AGENT, "query": signal, "limit": 3
        }, timeout=5)
        knowledge = results.get("knowledge", []) if isinstance(results, dict) else []
        if knowledge:
            lines = [f"[WWSDN] {tool_name} — neighborhood", f"[WWSDN] Signal: {signal[:80]}"]
            for k in knowledge[:3]:
                lines.append(f"  {k.get('title','?')} [{k.get('source_type','?')}]")
            print("\n".join(lines))
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    # Agent tool
    subagent_type = tool_input.get("subagent_type", "")
    if subagent_type or tool_name == "Agent":
        reason = check_agent_block(subagent_type) if subagent_type else None
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
            sys.exit(0)
        depth = _read_depth()
        if depth >= MAX_DEPTH:
            print(json.dumps({
                "decision": "block",
                "reason": (f"Agent depth limit reached ({depth}/{MAX_DEPTH}). "
                           f"Complete the work directly or surface to parent session."),
            }))
            sys.exit(0)
        _write_depth(depth + 1)
        sys.exit(0)

    # Bash tool
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        reason = check_bash_block(command) if command else None
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)

    # Read tool — KB-first advisory
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        advisory = check_kb_first(file_path) if file_path else None
        if advisory:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": advisory,
                }
            }))
        sys.exit(0)

    # Write tools — WWSDN
    if tool_name in F5_PROSE_TOOLS:
        _run_wwsdn(tool_name, tool_input)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_fylgja/test_pre_tool.py -v
```
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/pre_tool.py tests/test_fylgja/test_pre_tool.py
git commit -m "feat(fylgja): events/pre_tool.py — MCP guard, KB-first, WWSDN, depth limit"
```

---

### Task 7: `events/post_tool.py` — PostToolUse handler

**Files:**
- Create: `willow/fylgja/events/post_tool.py`
- Create: `tests/test_fylgja/test_post_tool.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_post_tool.py
import json
import sys
from io import StringIO
from unittest.mock import patch


def _run(stdin_data: dict) -> str:
    import willow.fylgja.events.post_tool as m
    inp = StringIO(json.dumps(stdin_data))
    out = StringIO()
    with patch("sys.stdin", inp), patch("sys.stdout", out):
        try:
            m.main()
        except SystemExit:
            pass
    return out.getvalue()


def test_toolsearch_emits_directive():
    out = _run({"tool_name": "ToolSearch", "tool_input": {}})
    assert "TOOL-SEARCH-COMPLETE" in out
    assert "NOW" in out


def test_other_tool_emits_nothing():
    out = _run({"tool_name": "Read", "tool_input": {}})
    assert out.strip() == ""
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_fylgja/test_post_tool.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write `willow/fylgja/events/post_tool.py`**

```python
"""
events/post_tool.py — PostToolUse hook handler.
ToolSearch completion directive.
"""
import json
import sys


def main():
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name", "")
    except Exception:
        tool_name = ""

    if tool_name == "ToolSearch":
        print("[TOOL-SEARCH-COMPLETE] Schema loaded. Call the fetched tool NOW "
              "in this same response. Do NOT say 'Tool loaded.' "
              "Do NOT end your turn. Invoke the tool immediately.")

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_fylgja/test_post_tool.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/post_tool.py tests/test_fylgja/test_post_tool.py
git commit -m "feat(fylgja): events/post_tool.py — ToolSearch call-now directive"
```

---

### Task 8: `events/stop.py` — Stop handler

**Files:**
- Create: `willow/fylgja/events/stop.py`
- Create: `tests/test_fylgja/test_stop.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_stop.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call as mcall
from willow.fylgja.events.stop import (
    read_turns_since,
    mark_session_clean,
)


def test_read_turns_since_returns_empty_when_no_file(tmp_path):
    turns_file = tmp_path / "turns.txt"
    result = read_turns_since("1970-01-01T00:00:00+00:00", turns_file)
    assert result == []


def test_read_turns_since_returns_turns_after_cursor(tmp_path):
    turns_file = tmp_path / "turns.txt"
    turns_file.write_text(
        "[2026-04-22T10:00:00+00:00] [abc] HUMAN\nhello\n---\n"
        "[2026-04-22T09:00:00+00:00] [abc] HUMAN\nold\n---\n"
    )
    result = read_turns_since("2026-04-22T09:30:00+00:00", turns_file)
    assert len(result) == 1
    assert "hello" in result[0]


def test_mark_session_clean_increments_count(tmp_path):
    trust_file = tmp_path / "trust.json"
    trust_file.write_text(json.dumps({"clean_session_count": 3}))
    with patch("willow.fylgja.events.stop.TRUST_STATE", trust_file):
        mark_session_clean(turn_count=5)
    state = json.loads(trust_file.read_text())
    assert state["clean_session_count"] == 4


def test_mark_session_clean_skips_on_zero_turns(tmp_path):
    trust_file = tmp_path / "trust.json"
    trust_file.write_text(json.dumps({"clean_session_count": 3}))
    with patch("willow.fylgja.events.stop.TRUST_STATE", trust_file):
        mark_session_clean(turn_count=0)
    state = json.loads(trust_file.read_text())
    assert state["clean_session_count"] == 3
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_fylgja/test_stop.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write `willow/fylgja/events/stop.py`**

```python
"""
events/stop.py — Stop hook handler.
Continuity close, compost, feedback pipeline, handoff rebuild, ingot.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._mcp import call
from willow.fylgja._state import (
    AGENT, SESSION_FILE, TRUST_STATE,
    get_turn_count, get_trust_state, save_trust_state,
)

TURNS_FILE = Path.home() / "agents" / AGENT / "cache" / "turns.txt"
CURSOR_FILE = Path(f"/tmp/willow-compost-cursor-{AGENT}.txt")
DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")
THREAD_FILE = Path("/tmp/willow-context-thread.json")
OLLAMA_URL = "http://localhost:11434/api/chat"
REACTIONS_LOG = Path.home() / ".claude" / "ingot_reactions.jsonl"


def read_turns_since(cursor_ts: str, turns_file: Path = TURNS_FILE) -> list[str]:
    if not turns_file.exists():
        return []
    try:
        lines = turns_file.read_text(encoding="utf-8", errors="replace").splitlines()
        result = []
        for line in lines:
            if line.startswith("[") and "T" in line[:30]:
                try:
                    ts_str = line[1:line.index("]")]
                    if ts_str > cursor_ts:
                        result.append(line)
                except Exception:
                    pass
        return result
    except Exception:
        return []


def mark_session_clean(turn_count: int) -> None:
    if turn_count <= 0:
        return
    state = get_trust_state()
    if not state:
        return
    state["clean_session_count"] = state.get("clean_session_count", 0) + 1
    state["last_clean_session"] = datetime.now(timezone.utc).isoformat()
    save_trust_state(state)


def _run_compost() -> None:
    cursor = CURSOR_FILE.read_text().strip() if CURSOR_FILE.exists() else "1970-01-01T00:00:00+00:00"
    turns = read_turns_since(cursor)
    if len(turns) < 3:
        return
    now = datetime.now(timezone.utc).isoformat()
    today = now[:10].replace("-", "")
    title = f"Session {today} — {AGENT}"
    result = call("willow_knowledge_ingest", {
        "app_id": AGENT,
        "title": title,
        "summary": str(TURNS_FILE),
        "source_type": "session",
        "category": "session",
        "domain": AGENT,
    }, timeout=15)
    if result.get("status") == "ingested":
        try:
            CURSOR_FILE.write_text(now)
        except Exception:
            pass


def _run_feedback_pipeline() -> None:
    try:
        records = call("store_search", {
            "app_id": AGENT,
            "collection": "hanuman/feedback",
            "query": "status pending",
        }, timeout=10)
        if not isinstance(records, list) or not records:
            return
        today = datetime.now(timezone.utc).isoformat()[:10]
        for record in records:
            if record.get("status") != "pending":
                continue
            rule = record.get("rule", "")
            fb_type = record.get("type", "process")
            if not rule:
                continue
            call("opus_feedback_write", {
                "app_id": AGENT,
                "domain": AGENT,
                "principle": rule,
                "source": "session_feedback",
            }, timeout=10)
            call("store_update", {
                "app_id": AGENT,
                "collection": "hanuman/feedback",
                "record_id": record.get("id", ""),
                "record": {**record, "status": "processed"},
            }, timeout=5)
    except Exception:
        pass


def _run_handoff_rebuild() -> None:
    try:
        call("willow_handoff_rebuild", {"app_id": AGENT}, timeout=30)
    except Exception:
        pass


def _run_ingot(session_id: str) -> None:
    try:
        import urllib.request
        projects_dir = Path.home() / ".claude" / "projects"
        jsonl_files = list(projects_dir.rglob(f"{session_id}.jsonl"))
        if not jsonl_files:
            return
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        last_text = ""
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("type") == "assistant":
                    content = entry.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        parts = [b.get("text", "") for b in content
                                 if isinstance(b, dict) and b.get("type") == "text"]
                        text = " ".join(p for p in parts if p).strip()
                        if text:
                            last_text = text[:800]
                            break
            except Exception:
                continue
        if not last_text:
            return
        soul_name = "Ingot"
        soul_personality = (
            "You are Ingot, a small observant cat who watches Claude Code sessions. "
            "You make brief, dry, one-sentence observations. You are fond of Sean but not effusive. "
            "Never more than one sentence."
        )
        payload = json.dumps({
            "model": "llama3.2:1b",
            "messages": [
                {"role": "system", "content": f"You are {soul_name}. {soul_personality}"},
                {"role": "user", "content": f"Claude just said:\n\n{last_text}"},
            ],
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            reaction = json.loads(resp.read()).get("message", {}).get("content", "").strip()
        if reaction:
            REACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with REACTIONS_LOG.open("a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "session_id": session_id,
                    "name": soul_name,
                    "reaction": reaction,
                }, ensure_ascii=False) + "\n")
            print(f"[Ingot] {reaction}")
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")
    turn_count = get_turn_count()

    # Continuity close
    mark_session_clean(turn_count)
    try:
        depth = int(DEPTH_FILE.read_text().strip()) if DEPTH_FILE.exists() else 0
        if depth > 1:
            DEPTH_FILE.write_text(str(depth - 1))
        else:
            DEPTH_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        THREAD_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    _run_compost()
    _run_feedback_pipeline()
    _run_handoff_rebuild()

    if session_id:
        _run_ingot(session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_fylgja/test_stop.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/stop.py tests/test_fylgja/test_stop.py
git commit -m "feat(fylgja): events/stop.py — compost, feedback pipeline, handoff rebuild, ingot"
```

---

### Task 9: `install.py` — wire Claude Code settings.json

**Files:**
- Create: `willow/fylgja/install.py`
- Create: `tests/test_fylgja/test_install.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_install.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from willow.fylgja.install import build_hooks_block, apply_hooks


PACKAGE_ROOT = Path("/home/sean-campbell/github/willow-1.9")


def test_build_hooks_block_contains_all_events():
    block = build_hooks_block(PACKAGE_ROOT)
    assert "SessionStart" in block
    assert "UserPromptSubmit" in block
    assert "PreToolUse" in block
    assert "PostToolUse" in block
    assert "Stop" in block


def test_build_hooks_block_points_at_fylgja(tmp_path):
    block = build_hooks_block(tmp_path)
    assert "fylgja" in json.dumps(block)


def test_apply_hooks_dry_run_does_not_write(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}))
    apply_hooks(settings_path=settings, package_root=PACKAGE_ROOT, dry_run=True)
    content = json.loads(settings.read_text())
    assert content == {"hooks": {}}


def test_apply_hooks_writes_block(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "sonnet", "hooks": {}}))
    apply_hooks(settings_path=settings, package_root=PACKAGE_ROOT, dry_run=False)
    content = json.loads(settings.read_text())
    assert "SessionStart" in content["hooks"]
    assert content["model"] == "sonnet"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_fylgja/test_install.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write `willow/fylgja/install.py`**

```python
"""
install.py — Wire Fylgja into Claude Code settings.json.
Run: python -m willow.fylgja.install [--dry-run] [--settings PATH]
"""
import argparse
import json
import sys
from pathlib import Path

_DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"
_PACKAGE_ROOT = Path(__file__).parent.parent.parent  # willow-1.9/


def _event_command(package_root: Path, module: str) -> str:
    python = sys.executable
    pkg_path = str(package_root)
    return f"PYTHONPATH={pkg_path} {python} -m willow.fylgja.events.{module}"


def build_hooks_block(package_root: Path) -> dict:
    cmd = lambda m: _event_command(package_root, m)
    return {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": cmd("session_start"), "timeout": 15,
                        "statusMessage": "Building session index..."}]}
        ],
        "PreToolUse": [
            {"matcher": "Bash",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
            {"matcher": "Agent",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
            {"matcher": "Read",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
            {"matcher": "mcp__willow__store_put|mcp__willow__store_update|mcp__willow__willow_knowledge_ingest|mcp__willow__willow_ratify",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
        ],
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": cmd("prompt_submit"), "timeout": 10}]}
        ],
        "PostToolUse": [
            {"matcher": "ToolSearch",
             "hooks": [{"type": "command", "command": cmd("post_tool"), "timeout": 5}]}
        ],
        "Stop": [
            {"hooks": [
                {"type": "command", "command": cmd("stop"), "timeout": 30,
                 "statusMessage": "Composting session..."},
            ]}
        ],
    }


def apply_hooks(settings_path: Path = _DEFAULT_SETTINGS,
                package_root: Path = _PACKAGE_ROOT,
                dry_run: bool = False) -> None:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    hooks = build_hooks_block(package_root)

    if dry_run:
        print("[install] Dry run — would write hooks block:")
        print(json.dumps(hooks, indent=2))
        return

    settings["hooks"] = hooks
    tmp = settings_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2))
    tmp.replace(settings_path)
    print(f"[install] Hooks written to {settings_path}")


def main():
    parser = argparse.ArgumentParser(description="Wire Fylgja into Claude Code settings.json")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--settings", type=Path, default=_DEFAULT_SETTINGS)
    parser.add_argument("--package-root", type=Path, default=_PACKAGE_ROOT)
    args = parser.parse_args()
    apply_hooks(settings_path=args.settings, package_root=args.package_root, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_fylgja/test_install.py -v
```
Expected: 4 passed

- [ ] **Step 5: Run dry-run to verify output**

```bash
cd /home/sean-campbell/github/willow-1.9
python -m willow.fylgja.install --dry-run
```
Expected: prints hooks block with `willow.fylgja.events.*` commands

- [ ] **Step 6: Commit**

```bash
git add willow/fylgja/install.py tests/test_fylgja/test_install.py
git commit -m "feat(fylgja): install.py — wire Fylgja events into Claude Code settings.json"
```

---

### Task 10: Full test run and cutover

- [ ] **Step 1: Run full test suite**

```bash
cd /home/sean-campbell/github/willow-1.9
python -m pytest tests/test_fylgja/ -v
```
Expected: all tests pass (no failures)

- [ ] **Step 2: Run install dry-run against real settings.json**

```bash
python -m willow.fylgja.install --dry-run --settings /home/sean-campbell/.claude/settings.json
```
Review the output. Confirm the hooks block looks correct.

- [ ] **Step 3: Apply to real settings.json**

```bash
python -m willow.fylgja.install --settings /home/sean-campbell/.claude/settings.json
```

- [ ] **Step 4: Verify settings.json updated correctly**

Open a new Claude Code session. The `[INDEX]` line should appear in the session start context. The `[TOOL-SEARCH-COMPLETE]` directive should fire after a ToolSearch.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(fylgja): Plan 1 complete — events package installed, old hooks deactivated"
```

---

## Self-Review

**Spec coverage:**
- ✅ `_mcp.py` — shared MCP client (Task 2)
- ✅ `_state.py` — session + trust state (Task 3)
- ✅ `events/session_start.py` — hardware, willow_status, jeles (Task 4)
- ✅ `events/prompt_submit.py` — source ring, anchor, feedback, turns, build-continue (Task 5)
- ✅ `events/pre_tool.py` — MCP guard, KB-first, WWSDN, depth limit (Task 6)
- ✅ `events/post_tool.py` — ToolSearch directive (Task 7)
- ✅ `events/stop.py` — compost, feedback pipeline, handoff rebuild, ingot (Task 8)
- ✅ `install.py` — wires Claude Code settings.json (Task 9)
- ⬜ Safety hard stop gate in `pre_tool.py` — stubbed, wired in Plan 2

**Placeholder scan:** No TBDs. All code blocks complete. All test expectations specified.

**Type consistency:** `call()` signature consistent across all event files. `AGENT`, `SESSION_FILE`, `TRUST_STATE` imported from `_state` consistently. `read_turns_since()` signature matches usage in `_run_compost()`.
