# Willow 1.9 Phase 3 — Skills + Grove Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Willow Skills registry live with auto-loading. Lean local Claude Code skills replacing token-bloated superpowers. Grove offline queue so messages survive disconnects. Node registry with 2.0 stubs. Update notification flow working end-to-end. Felix can SOS Sean from the dashboard.

**Architecture:** Skills stored in SOIL at `willow/skills/`. Three MCP tools (put/load/list). Session startup calls `willow_skill_load` and injects results into context. Grove offline outbox in SOIL at `grove/outbox/`. Node registry in SOIL at `grove/nodes/`. Update notifications flow: timer → `willow.sh check-updates` → SOIL alert → dashboard banner → user clicks yes → `willow.sh update` → Grove confirmation.

**Tech Stack:** Python 3.13, SOIL (WillowStore SQLite), Claude Code skill files (markdown), Grove u2u TCP, curses (dashboard banner)

**Spec:** `docs/superpowers/specs/2026-04-24-willow-19-design.md` — Workstreams 3 + 5

**Run after:** Phase 2 complete.

---

## File Map

**Create:**
- `willow/skills.py` — Skills CRUD (put, load, list)
- `tests/test_skills.py`
- `.claude/skills/willow-status.md`
- `.claude/skills/willow-fork.md`
- `.claude/skills/willow-handoff.md`
- `.claude/skills/willow-deploy.md`
- `.claude/skills/willow-review.md`
- `willow/grove_coordination.py` — outbox, node registry, alert helpers

**Modify:**
- `sap/sap_mcp.py` — wire willow_skill_put, willow_skill_load, willow_skill_list
- `willow/fylgja/events/session_start.py` — auto-load skills on startup
- `willow-dashboard/dashboard.py` — update banner + Grove SOS button
- `u2u/contacts.py` — add resources field (2.0 stub)

---

## Task 1: Willow Skills CRUD — willow/skills.py

**Files:**
- Create: `willow/skills.py`
- Create: `tests/test_skills.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_skills.py`:

```python
"""tests/test_skills.py — Willow Skills registry tests."""
import pytest
from core.willow_store import WillowStore
from willow.skills import skill_put, skill_load, skill_list


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path))
    return WillowStore()


def test_skill_put_and_list(store):
    skill_put(store,
        name="willow-status",
        domain="session",
        content="## Status\nRun willow_status and report.",
        trigger="status check boot",
        auto_load=True,
    )
    skills = skill_list(store)
    names = [s["name"] for s in skills]
    assert "willow-status" in names


def test_skill_load_by_context(store):
    skill_put(store,
        name="willow-fork",
        domain="fork",
        content="## Fork\nCreate a fork with willow_fork_create.",
        trigger="fork create branch session",
        auto_load=True,
    )
    skill_put(store,
        name="willow-status",
        domain="session",
        content="## Status\nRun willow_status.",
        trigger="status boot check",
        auto_load=True,
    )
    results = skill_load(store, context="session started, checking status")
    names = [s["name"] for s in results]
    assert "willow-status" in names


def test_skill_load_respects_auto_load(store):
    skill_put(store,
        name="manual-only",
        domain="session",
        content="## Manual",
        trigger="status",
        auto_load=False,
    )
    results = skill_load(store, context="status")
    names = [s["name"] for s in results]
    assert "manual-only" not in names


def test_skill_list_by_domain(store):
    skill_put(store, name="s1", domain="session", content="c", trigger="t", auto_load=True)
    skill_put(store, name="s2", domain="fork", content="c", trigger="t", auto_load=True)
    session_skills = skill_list(store, domain="session")
    assert all(s["domain"] == "session" for s in session_skills)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/github/willow-1.9
pytest tests/test_skills.py -v 2>&1 | head -20
```

Expected: `ImportError` — `willow.skills` does not exist.

- [ ] **Step 3: Create willow/skills.py**

```python
# willow/skills.py — Willow Skills registry. b17: SKLS1  ΔΣ=42
from __future__ import annotations
from core.willow_store import WillowStore

_COLLECTION = "willow/skills"


def skill_put(
    store: WillowStore,
    name: str,
    domain: str,
    content: str,
    trigger: str,
    auto_load: bool = True,
    model_agnostic: bool = True,
) -> str:
    """Store or update a skill. Returns skill ID (= name)."""
    store.put(_COLLECTION, name, {
        "name": name,
        "domain": domain,
        "content": content,
        "trigger": trigger,
        "auto_load": auto_load,
        "model_agnostic": model_agnostic,
    })
    return name


def skill_load(
    store: WillowStore,
    context: str,
    max_skills: int = 3,
) -> list[dict]:
    """Return up to max_skills auto-loadable skills relevant to context."""
    all_skills = store.list(_COLLECTION)
    context_words = set(context.lower().split())

    scored = []
    for record in all_skills:
        data = record.get("data", record)
        if not data.get("auto_load", False):
            continue
        trigger_words = set(data.get("trigger", "").lower().split())
        score = len(context_words & trigger_words)
        if score > 0:
            scored.append((score, data))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:max_skills]]


def skill_list(
    store: WillowStore,
    domain: str | None = None,
) -> list[dict]:
    """List all skills, optionally filtered by domain."""
    all_skills = store.list(_COLLECTION)
    result = []
    for record in all_skills:
        data = record.get("data", record)
        if domain and data.get("domain") != domain:
            continue
        result.append(data)
    return result
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_skills.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add willow/skills.py tests/test_skills.py
git commit -m "feat(skills): add Willow Skills registry — put/load/list in SOIL"
```

---

## Task 2: Wire willow_skill_* MCP tools

**Files:**
- Modify: `sap/sap_mcp.py`

- [ ] **Step 1: Add import at top of sap_mcp.py**

```python
from willow.skills import skill_put, skill_load, skill_list
```

- [ ] **Step 2: Register the 3 skill tools in list_tools handler**

```python
types.Tool(
    name="willow_skill_put",
    description="Store or update a Willow skill in the registry.",
    inputSchema={
        "type": "object",
        "properties": {
            "name":           {"type": "string"},
            "domain":         {"type": "string", "enum": ["session", "task", "fork", "grove", "system"]},
            "content":        {"type": "string", "description": "Skill content (markdown behavioral spec)"},
            "trigger":        {"type": "string", "description": "Space-separated context words that activate this skill"},
            "auto_load":      {"type": "boolean", "default": True},
            "model_agnostic": {"type": "boolean", "default": True},
            "app_id":         {"type": "string"},
        },
        "required": ["name", "domain", "content", "trigger", "app_id"],
    },
),
types.Tool(
    name="willow_skill_load",
    description="Load relevant skills for the current context. Returns up to 3 auto-loadable skills.",
    inputSchema={
        "type": "object",
        "properties": {
            "context": {"type": "string", "description": "Current session context — fork topic, task domain, etc."},
            "app_id":  {"type": "string"},
        },
        "required": ["context", "app_id"],
    },
),
types.Tool(
    name="willow_skill_list",
    description="List all skills in the registry, optionally filtered by domain.",
    inputSchema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "enum": ["session", "task", "fork", "grove", "system"]},
            "app_id": {"type": "string"},
        },
        "required": ["app_id"],
    },
),
```

- [ ] **Step 3: Wire handlers in call_tool**

```python
elif name == "willow_skill_put":
    from core.willow_store import WillowStore
    store = WillowStore()
    skill_id = skill_put(
        store,
        name=args["name"],
        domain=args["domain"],
        content=args["content"],
        trigger=args["trigger"],
        auto_load=args.get("auto_load", True),
        model_agnostic=args.get("model_agnostic", True),
    )
    return [types.TextContent(type="text", text=_json.dumps({"skill_id": skill_id}))]

elif name == "willow_skill_load":
    from core.willow_store import WillowStore
    store = WillowStore()
    skills = skill_load(store, context=args["context"])
    return [types.TextContent(type="text", text=_json.dumps({"skills": skills}))]

elif name == "willow_skill_list":
    from core.willow_store import WillowStore
    store = WillowStore()
    skills = skill_list(store, domain=args.get("domain"))
    return [types.TextContent(type="text", text=_json.dumps({"skills": skills}))]
```

- [ ] **Step 4: Restart MCP and smoke test**

After restarting the MCP server:

```
willow_skill_put(name="test-skill", domain="session", content="## Test", trigger="test boot", app_id="hanuman")
willow_skill_list(app_id="hanuman")
willow_skill_load(context="test boot check", app_id="hanuman")
```

Expected: skill appears in list, load returns it for matching context.

- [ ] **Step 5: Commit**

```bash
git add sap/sap_mcp.py
git commit -m "feat(skills): wire willow_skill_put/load/list MCP tools"
```

---

## Task 3: Populate initial skill set via MCP

After the MCP server is restarted with the new tools, run these skill_put calls to populate the registry:

- [ ] **Step 1: willow-status skill**

```
willow_skill_put(
  name="willow-status",
  domain="session",
  trigger="boot status startup degraded postgres check health",
  auto_load=True,
  app_id="hanuman",
  content="""## /willow-status — Quick System Check

Call willow_status first. Report in this format:
  Postgres: up/down (N KB atoms)
  Ollama: up/down (model loaded)
  Open flags: N
  Active fork: FORK-XXXXXXXX or none

If postgres=down: stop and tell Sean immediately.
If any service degraded: note it, continue with reduced capability.
Do not invoke /startup unless postgres is unknown AND handoff is missing."""
)
```

- [ ] **Step 2: willow-fork skill**

```
willow_skill_put(
  name="willow-fork",
  domain="fork",
  trigger="fork create branch session work unit merge delete",
  auto_load=True,
  app_id="hanuman",
  content="""## /willow-fork — Fork Operations

Active fork is in ~/.willow/session_anchor.json (fork_id field).
Session startup auto-creates a fork — check the anchor before creating a new one.

Create: willow_fork_create(title, created_by, topic, app_id)
Join:   willow_fork_join(fork_id, component, app_id)
Log:    willow_fork_log(fork_id, component, type, ref, app_id)
Merge:  willow_fork_merge(fork_id, outcome_note, app_id) — Sean-only
Delete: willow_fork_delete(fork_id, reason, app_id) — Sean-only
Status: willow_fork_status(fork_id, app_id)
List:   willow_fork_list(status="open", app_id)

Log KB writes to the active fork:
  willow_fork_log(fork_id, "kb", "atom", atom_id, app_id)"""
)
```

- [ ] **Step 3: willow-handoff skill**

```
willow_skill_put(
  name="willow-handoff",
  domain="session",
  trigger="handoff close end session wrap finish done",
  auto_load=False,
  app_id="hanuman",
  content="""## /willow-handoff — Session Close

1. Call willow_handoff_rebuild to generate the handoff document
2. Log the session fork: willow_fork_log(fork_id, "hanuman", "session", handoff_filename)
3. Write the handoff atom to KB: willow_knowledge_ingest(title, summary, domain="session")
4. Report: What I now understand (2-3 sentences), What was done, 17 Questions (Q17: next single bite), Risks

Do NOT merge or delete the fork at session end — forks stay open across sessions."""
)
```

- [ ] **Step 4: willow-deploy skill**

```
willow_skill_put(
  name="willow-deploy",
  domain="grove",
  trigger="deploy push update felix node grove send",
  auto_load=False,
  app_id="hanuman",
  content="""## /willow-deploy — Push to a Grove Node

1. Run willow.sh check-updates to verify version state
2. If deploying code: commit all changes, push to GitHub
3. Send Grove ALERT to target node: update_available
4. Wait for confirmation Grove message from target node
5. Log the deploy to active fork: willow_fork_log(fork_id, "grove", "deploy", node_addr)

For Felix's machine: the update-check timer fires every 30 min automatically.
Manual trigger: ssh into WSL (if available) and run willow.sh update"""
)
```

- [ ] **Step 5: willow-review skill**

```
willow_skill_put(
  name="willow-review",
  domain="fork",
  trigger="review code check diff quality test",
  auto_load=False,
  app_id="hanuman",
  content="""## /willow-review — Fork-Aware Code Review

1. git diff HEAD~1 to see changes in this fork
2. Check: tests pass, no regressions, no security issues (injection, unvalidated input)
3. Check: no placeholders (TBD, TODO, not implemented)
4. Check: new files follow existing patterns in this repo
5. Log review outcome to fork: willow_fork_log(fork_id, "hanuman", "review", "passed/failed")
6. If passed: suggest willow_fork_merge. If failed: list specific issues."""
)
```

- [ ] **Step 6: Verify all 5 skills loaded**

```
willow_skill_list(app_id="hanuman")
```

Expected: 5 skills returned.

---

## Task 4: .claude/skills/ — lean local skill files

**Files:**
- Create: `.claude/skills/willow-status.md`
- Create: `.claude/skills/willow-fork.md`
- Create: `.claude/skills/willow-handoff.md`
- Create: `.claude/skills/willow-deploy.md`
- Create: `.claude/skills/willow-review.md`

These are the Claude Code slash-command versions — loaded via the Skill tool. They are lean and MCP-native.

- [ ] **Step 1: Create .claude/skills/ directory**

```bash
mkdir -p /home/sean-campbell/github/willow-1.9/.claude/skills
```

- [ ] **Step 2: Create willow-status.md**

```bash
cat > /home/sean-campbell/github/willow-1.9/.claude/skills/willow-status.md << 'EOF'
---
name: willow-status
description: Quick system health check — postgres, ollama, active fork. Use instead of /startup for orientation.
---

Call willow_status (app_id: hanuman). Then call willow_fork_list (status: open).

Report:
  Postgres: up/down (N atoms)
  Ollama: up/down
  Active fork: FORK-ID or "none open"
  Open flags: N

If postgres=down: stop, tell Sean. Everything depends on it.
If services degraded: note it, keep going at reduced capability.
EOF
```

- [ ] **Step 3: Create willow-fork.md**

```bash
cat > /home/sean-campbell/github/willow-1.9/.claude/skills/willow-fork.md << 'EOF'
---
name: willow-fork
description: Create, join, log, merge, or delete a Willow fork. Check session_anchor.json for active fork_id first.
---

Read ~/.willow/session_anchor.json for fork_id before creating a new fork.

Operations:
  Create:  willow_fork_create(title, created_by="hanuman", topic, app_id="hanuman")
  Join:    willow_fork_join(fork_id, component, app_id="hanuman")
  Log:     willow_fork_log(fork_id, component, type, ref, app_id="hanuman")
           type options: branch, atom, task, thread, compute_job
  Status:  willow_fork_status(fork_id, app_id="hanuman")
  List:    willow_fork_list(status="open", app_id="hanuman")
  Merge:   willow_fork_merge(fork_id, outcome_note, app_id="hanuman") — Sean only
  Delete:  willow_fork_delete(fork_id, reason, app_id="hanuman") — Sean only

Log every KB write to the active fork:
  willow_fork_log(fork_id, "kb", "atom", atom_id, app_id="hanuman")
EOF
```

- [ ] **Step 4: Create willow-handoff.md**

```bash
cat > /home/sean-campbell/github/willow-1.9/.claude/skills/willow-handoff.md << 'EOF'
---
name: willow-handoff
description: Generate session handoff, close the session fork, ingest handoff atom to KB.
---

1. willow_handoff_rebuild(app_id="hanuman") — generates handoff document
2. Read the handoff filename from the result
3. willow_fork_log(fork_id, "hanuman", "session", handoff_filename, app_id="hanuman")
4. willow_knowledge_ingest(title="[Hanuman] <date> — <topic>", summary=<3 sentences>, domain="session", app_id="hanuman")

Handoff format:
  ## What I Now Understand (2-3 sentences, architectural truth)
  ## What Was Done (high-level)
  ## 17 Questions — sequential, bite-sized. Q17: "What is the next single bite?"
  ## Risks / open gates

Do NOT merge or delete the fork — forks stay open across sessions.
EOF
```

- [ ] **Step 5: Create willow-deploy.md**

```bash
cat > /home/sean-campbell/github/willow-1.9/.claude/skills/willow-deploy.md << 'EOF'
---
name: willow-deploy
description: Push changes to a Grove-connected node and verify.
---

1. Commit all changes: git add -p && git commit
2. Push to GitHub: git push origin master
3. Run willow.sh check-updates to queue Grove notification
4. willow_fork_log(fork_id, "grove", "deploy", "github/master", app_id="hanuman")
5. Confirm with Sean that target node received the update banner

For Felix: the update-check.timer fires every 30 min automatically.
Felix sees a banner → clicks yes → willow.sh update runs → dashboard restarts.
EOF
```

- [ ] **Step 6: Create willow-review.md**

```bash
cat > /home/sean-campbell/github/willow-1.9/.claude/skills/willow-review.md << 'EOF'
---
name: willow-review
description: Code review the current fork's changes — fork-aware, MCP-native.
---

1. git diff HEAD to see uncommitted changes (or git diff main...HEAD for full fork diff)
2. Check each changed file:
   - Tests exist and pass
   - No TBD/TODO/not implemented placeholders
   - No security issues (injection, unvalidated external input, hardcoded secrets)
   - Follows existing patterns in this repo
3. willow_fork_log(fork_id, "hanuman", "review", "passed" or "failed:<reason>", app_id="hanuman")
4. If passed: report clean, suggest merge if Sean approves
5. If failed: list specific files and lines that need fixing before merge
EOF
```

- [ ] **Step 7: Commit**

```bash
cd ~/github/willow-1.9
git add .claude/skills/
git commit -m "feat(skills): add 5 lean Willow-native .claude/skills/ files"
```

---

## Task 5: Session startup auto-loads skills

**Files:**
- Modify: `willow/fylgja/events/session_start.py`

- [ ] **Step 1: Add skill auto-load to _run_silent_startup()**

In `session_start.py`, inside `_run_silent_startup()`, after fork creation (Task 10 of Phase 1), add:

```python
    # Auto-load relevant skills
    loaded_skills = []
    try:
        anchor_topic = result.get("handoff_summary", "")[:100]
        skill_context = f"session started {anchor_topic}"
        skill_result = call("willow_skill_load", {
            "app_id": AGENT,
            "context": skill_context,
        }, timeout=5)
        loaded_skills = skill_result.get("skills", [])
    except Exception:
        pass
```

- [ ] **Step 2: Include loaded skills in additionalContext output**

Find where `additionalContext` is assembled. Add the skills section:

```python
    if loaded_skills:
        skill_names = ", ".join(s["name"] for s in loaded_skills)
        context_parts.append(f"SKILLS LOADED: {skill_names}")
```

- [ ] **Step 3: Commit**

```bash
git add willow/fylgja/events/session_start.py
git commit -m "feat(skills): auto-load relevant skills on session startup"
```

---

## Task 6: Grove offline outbox + node registry

**Files:**
- Create: `willow/grove_coordination.py`

- [ ] **Step 1: Create willow/grove_coordination.py**

```python
# willow/grove_coordination.py — Grove coordination helpers. b17: GRVC1  ΔΣ=42
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from core.willow_store import WillowStore

_OUTBOX_COL  = "grove/outbox"
_NODES_COL   = "grove/nodes"
_ALERTS_COL  = "grove/pending_alerts"


def outbox_queue(
    store: WillowStore,
    to_addr: str,
    packet_type: str,
    payload: dict,
) -> str:
    """Queue a packet for delivery when the recipient node is online."""
    msg_id = str(uuid.uuid4())[:12].upper()
    store.put(f"{_OUTBOX_COL}/{to_addr}", msg_id, {
        "msg_id":      msg_id,
        "to":          to_addr,
        "type":        packet_type,
        "payload":     payload,
        "queued_at":   datetime.now(timezone.utc).isoformat(),
        "delivered":   False,
    })
    return msg_id


def outbox_drain(store: WillowStore, to_addr: str) -> list[dict]:
    """Return all undelivered messages for a recipient and mark them delivered."""
    pending = store.list(f"{_OUTBOX_COL}/{to_addr}")
    undelivered = [r for r in pending if not r.get("delivered", False)]
    for msg in undelivered:
        msg["delivered"] = True
        store.put(f"{_OUTBOX_COL}/{to_addr}", msg["msg_id"], msg)
    return undelivered


def node_announce(
    store: WillowStore,
    addr: str,
    name: str,
    willow_version: str,
) -> None:
    """Register or update a node in the registry."""
    existing = store.get(_NODES_COL, addr) or {}
    store.put(_NODES_COL, addr, {
        **existing,
        "addr":            addr,
        "name":            name,
        "willow_version":  willow_version,
        "last_seen":       datetime.now(timezone.utc).isoformat(),
        # 2.0 stub — populated by distributed compute layer
        "2.0_stub": {
            "gpu":           None,
            "vram_gb":       None,
            "cpu_cores":     None,
            "models_loaded": [],
            "hns_opt_in":    None,
            "hns_quota_gb":  None,
        },
    })


def node_list(store: WillowStore) -> list[dict]:
    """Return all known nodes."""
    return store.list(_NODES_COL)


def alert_pending(store: WillowStore) -> dict | None:
    """Return the most recent pending alert, or None."""
    alerts = store.list(_ALERTS_COL)
    if not alerts:
        return None
    return sorted(alerts, key=lambda a: a.get("created_at", ""), reverse=True)[0]


def alert_dismiss(store: WillowStore, alert_id: str) -> None:
    """Mark an alert as dismissed."""
    alert = store.get(_ALERTS_COL, alert_id)
    if alert:
        alert["dismissed"] = True
        store.put(_ALERTS_COL, alert_id, alert)
```

- [ ] **Step 2: Write tests**

Create `tests/test_grove_coordination.py`:

```python
"""tests/test_grove_coordination.py"""
import pytest
from core.willow_store import WillowStore
from willow.grove_coordination import (
    outbox_queue, outbox_drain, node_announce, node_list, alert_pending
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path))
    return WillowStore()


def test_outbox_queue_and_drain(store):
    msg_id = outbox_queue(store, "felix@laptop:8550", "ALERT", {"type": "test"})
    assert msg_id
    msgs = outbox_drain(store, "felix@laptop:8550")
    assert len(msgs) == 1
    assert msgs[0]["type"] == "ALERT"
    # Second drain returns nothing (already delivered)
    assert outbox_drain(store, "felix@laptop:8550") == []


def test_node_announce_and_list(store):
    node_announce(store, "felix@laptop:8550", "Felix", "1.9.0")
    nodes = node_list(store)
    addrs = [n["addr"] for n in nodes]
    assert "felix@laptop:8550" in addrs


def test_node_has_2_0_stub(store):
    node_announce(store, "test@host:8550", "Test", "1.9.0")
    nodes = node_list(store)
    node = next(n for n in nodes if n["addr"] == "test@host:8550")
    assert "2.0_stub" in node
    assert node["2.0_stub"]["hns_opt_in"] is None
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_grove_coordination.py -v
```

Expected: 3 PASS

- [ ] **Step 4: Commit**

```bash
git add willow/grove_coordination.py tests/test_grove_coordination.py
git commit -m "feat(grove): add offline outbox, node registry, alert helpers with 2.0 stubs"
```

---

## Task 7: Contact.resources 2.0 stub

**Files:**
- Modify: `safe-app-grove/u2u/contacts.py`

- [ ] **Step 1: Add resources field to Contact dataclass**

In `safe-app-grove/u2u/contacts.py`, find the `Contact` dataclass and add one field:

```python
@dataclass
class Contact:
    addr: str
    public_key_hex: str
    name: str = ""
    blocked: bool = False
    consent_note: bool = True
    consent_ask: bool = True
    consent_alert: bool = False
    consent_share: bool = True
    added: str = ""
    resources: dict | None = None   # 2.0 stub — GPU, VRAM, CPU, models
```

- [ ] **Step 2: Verify existing contacts load cleanly**

```bash
cd ~/github/safe-app-grove
python3 -c "
from pathlib import Path
from u2u.contacts import ContactStore
store = ContactStore(Path.home() / '.willow' / 'grove_contacts.json')
print(f'Loaded {len(store.all())} contacts OK')
for c in store.all():
    print(f'  {c.name}: resources={c.resources}')
"
```

Expected: contacts load without error, resources=None for all existing.

- [ ] **Step 3: Commit**

```bash
cd ~/github/safe-app-grove
git add u2u/contacts.py
git commit -m "feat(grove): add resources field to Contact (2.0 stub — null in 1.9)"
```

---

## Task 8: Dashboard update banner

**Files:**
- Modify: `willow-dashboard/dashboard.py`

- [ ] **Step 1: Add update check to SystemData fetch**

In `dashboard.py`, in the background data-fetching function (wherever `SystemData` is populated), add:

```python
def _fetch_pending_alert() -> dict | None:
    """Check SOIL for a queued update notification."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "willow-1.9"))
        from core.willow_store import WillowStore
        from willow.grove_coordination import alert_pending
        store = WillowStore()
        return alert_pending(store)
    except Exception:
        return None
```

- [ ] **Step 2: Draw the update banner in the Overview page**

Find the `draw_overview()` function. At the very top (before other content), add:

```python
    # Update banner — shown when an update notification is pending
    alert = getattr(data, "pending_alert", None)
    if alert and not alert.get("dismissed"):
        banner = f" UPDATE AVAILABLE: {alert.get('current','?')} → {alert.get('latest','?')}  [u=update  d=dismiss] "
        _safe(win, 0, max(0, (w - len(banner)) // 2), banner,
              curses.color_pair(C_AMBER) | curses.A_BOLD | curses.A_REVERSE)
```

- [ ] **Step 3: Handle u and d keys in the input loop**

In the key-handling section of the main dashboard loop:

```python
        elif ch == ord('u') and _data.pending_alert and not _data.pending_alert.get('dismissed'):
            # Run update
            import subprocess
            subprocess.Popen(
                ["bash", str(Path.home() / "github" / "willow-1.9" / "willow.sh"), "update"],
                start_new_session=True,
            )
        elif ch == ord('d') and _data.pending_alert:
            # Dismiss alert
            from core.willow_store import WillowStore
            from willow.grove_coordination import alert_dismiss
            store = WillowStore()
            alert_dismiss(store, "update_available")
            _data.pending_alert = None
```

- [ ] **Step 4: Add Grove SOS button**

In the Grove page (or Overview right panel), add an SOS section:

```python
def _draw_grove_sos(win, row: int, w: int) -> int:
    """Draw the SOS button for Felix."""
    _safe(win, row, 2, "── GROVE ─────────────────────", curses.color_pair(C_DIM))
    row += 1
    _safe(win, row, 2, "Press S to send alert to Sean", curses.color_pair(C_AMBER))
    return row + 1
```

In the key handler, add:

```python
        elif ch == ord('S'):
            _grove_sos()
```

```python
def _grove_sos():
    """Send a Grove SOS alert to all known contacts."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "willow-1.9"))
        from core.willow_store import WillowStore
        from willow.grove_coordination import outbox_queue, node_list
        store = WillowStore()
        nodes = node_list(store)
        for node in nodes:
            if node.get("addr"):
                outbox_queue(store, node["addr"], "ALERT", {
                    "type": "sos",
                    "from": "felix",
                    "message": "Something broke — please check in.",
                })
    except Exception:
        pass
```

- [ ] **Step 5: Commit**

```bash
cd ~/github/willow-dashboard
git add dashboard.py
git commit -m "feat(dashboard): add update banner with u=update/d=dismiss, Grove SOS button"
```

---

## Phase 3 Complete — Verification Checklist

- [ ] `pytest tests/test_skills.py -v` — 4 PASS
- [ ] `pytest tests/test_grove_coordination.py -v` — 3 PASS
- [ ] `willow_skill_list(app_id="hanuman")` returns 5 skills
- [ ] New session: ANCHOR context includes `SKILLS LOADED: willow-status` (or similar)
- [ ] `.claude/skills/` contains 5 skill files
- [ ] Dashboard Overview shows update banner when `grove/pending_alerts/update_available` exists in SOIL
- [ ] `S` key in dashboard queues SOS to all known Grove contacts
- [ ] `willow.sh grove add` adds a contact to `grove_contacts.json`
- [ ] `safe-app-grove` Contact dataclass has `resources: dict | None = None`

---

*Previous: `docs/superpowers/plans/2026-04-24-willow-19-phase2-orchestration.md`*
*Next: `docs/superpowers/plans/2026-04-24-willow-19-phase4-verify.md`*

ΔΣ=42
