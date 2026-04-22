# Fylgja Skills Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `willow/fylgja/skills/` — a local Claude Code plugin registered as `fylgja@local` that ships Willow-native skills and 1.9-improved forks of the five most-used superpowers skills.

**Architecture:** A `plugin.json` manifest points Claude Code at the skills directory. Five Willow-native skills use `willow_status`, `willow_handoff_latest`, `willow_handoff_rebuild`, and `store_put` directly. Five forked skills are superpowers skills rewritten to reference Willow MCP tools and 1.9 patterns. `install.py` is extended to register the plugin in `enabledPlugins`.

**Tech Stack:** Markdown skill files, JSON manifest, Python (install.py extension), pytest

---

## File Map

**Create:**
- `willow/fylgja/skills/plugin.json`
- `willow/fylgja/skills/startup.md`
- `willow/fylgja/skills/handoff.md`
- `willow/fylgja/skills/status.md`
- `willow/fylgja/skills/shutdown.md`
- `willow/fylgja/skills/consent.md`
- `willow/fylgja/skills/brainstorming.md`
- `willow/fylgja/skills/debugging.md`
- `willow/fylgja/skills/tdd.md`
- `willow/fylgja/skills/iterative-retrieval.md`
- `willow/fylgja/skills/learn.md`

**Modify:**
- `willow/fylgja/install.py` — add `apply_plugin()` + extend `main()` with `--plugin` flag
- `tests/test_fylgja/test_install.py` — add plugin registration tests

---

### Task 1: `skills/plugin.json` manifest

- [ ] **Step 1: Create `willow/fylgja/skills/plugin.json`**

```json
{
  "name": "fylgja",
  "version": "1.9.0",
  "description": "Willow 1.9 behavioral skills — guardian + guide",
  "skills": "."
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python3 -c "import json; print(json.load(open('willow/fylgja/skills/plugin.json')))"
```

Expected: dict printed, no error.

- [ ] **Step 3: Commit**

```bash
git add willow/fylgja/skills/plugin.json
git commit -m "feat(fylgja): skills/plugin.json — fylgja@local Claude Code plugin manifest"
```

---

### Task 2: Willow-native skills

**Five skills. Each is a standalone markdown file with a frontmatter block followed by the skill body.**

- [ ] **Step 1: Write `willow/fylgja/skills/startup.md`**

```markdown
---
name: startup
description: Willow 1.9 session boot — health check, handoff load, flag scan, anchor write
---

# /startup — Willow 1.9 Boot

## Tool Pre-load

```
ToolSearch query: "select:mcp__willow__willow_status,mcp__willow__willow_handoff_latest,mcp__willow__store_list"
```

## Sequence

1+2. **Health + handoff in parallel** — call `mcp__willow__willow_status` AND `mcp__willow__willow_handoff_latest` simultaneously. If Postgres fails, surface and stop.
3. **Read prior handoff** — if content is a file pointer, use Read tool.
4. **Check open flags** — call `mcp__willow__store_list` with collection `hanuman/flags`. Filter `flag_state: open`. Note count and top 3 by severity.
5. **Write anchor cache** — Write tool to `~/.willow/session_anchor.json`:
   ```json
   {
     "written_at": "<ISO timestamp>",
     "agent": "hanuman",
     "postgres": "up|down",
     "handoff_title": "<filename>",
     "handoff_summary": "<one sentence>",
     "open_flags": <count>,
     "top_flags": ["<title1>", "<title2>", "<title3>"]
   }
   ```
   Also reset `~/.willow/anchor_state.json` to `{"prompt_count": 0}`.
6. **Report** — open flag count first, then subsystems, then last handoff summary (3 sentences max).
```

- [ ] **Step 2: Write `willow/fylgja/skills/handoff.md`**

```markdown
---
name: handoff
description: Write a Willow 1.9 session handoff — 17 questions, rebuild DB, write to Ashokoa index
---

# /handoff — Willow 1.9 Session Handoff

## Sequence

1. **Load current state** — call `mcp__willow__willow_handoff_latest` to see prior open threads.
2. **Draft handoff** using this format:
   ```
   # HANDOFF: <title>
   From: hanuman (Claude Code, Sonnet 4.6)

   ## What I Now Understand
   <2-3 sentences of architectural truth, not task summary>

   ## What Was Done
   <bullet list — high level, no code details>

   ## 17 Questions
   Q1–Q16: sequential, specific, bite-sized
   Q17: "What is the next single bite?"

   ## Risks / Open Gates
   <anything that could break the next session>
   ```
3. **Write the file** to `~/Ashokoa/agents/hanuman/index/haumana_handoffs/SESSION_HANDOFF_<YYYYMMDD>_hanuman_<letter>.md`.
4. **Rebuild DB** — call `mcp__willow__willow_handoff_rebuild`.
5. **Confirm** — report filename and Q17.
```

- [ ] **Step 3: Write `willow/fylgja/skills/status.md`**

```markdown
---
name: status
description: Willow 1.9 system status — Postgres, Ollama, local store, open flags
---

# /status — Willow 1.9 System Status

## Sequence

1. **Pre-load tools**:
   ```
   ToolSearch query: "select:mcp__willow__willow_status,mcp__willow__willow_system_status,mcp__willow__store_list"
   ```
2. **Run in parallel**: `mcp__willow__willow_status` AND `mcp__willow__willow_system_status` AND `mcp__willow__store_list` (collection `hanuman/flags`).
3. **Report** in this format:
   ```
   SUBSYSTEMS
     Postgres:    up / down / degraded
     Ollama:      up (N models) / down
     LocalStore:  N collections · M records
     Manifests:   N/N pass

   OPEN FLAGS: N
     • <top flag 1>
     • <top flag 2>
     • <top flag 3>
   ```
4. If Postgres is down: surface immediately, stop. Everything downstream is degraded.
```

- [ ] **Step 4: Write `willow/fylgja/skills/shutdown.md`**

```markdown
---
name: shutdown
description: Graceful Willow 1.9 session close — compost, feedback pipeline, handoff rebuild
---

# /shutdown — Willow 1.9 Graceful Close

## Sequence

1. **Write final handoff** — invoke `/handoff` skill. This produces the session summary and Q17.
2. **Trigger stop pipeline** — the Stop hook fires automatically when Claude Code exits. Confirm it will run: check `~/.claude/settings.json` Stop hook is present.
3. **Report what will happen at stop**:
   - Session turns composted to KB (`willow_knowledge_ingest`)
   - Pending feedback records processed (`opus_feedback_write`)
   - Handoff DB rebuilt (`willow_handoff_rebuild`)
   - Ingot reaction written
4. **Confirm safe to exit** — state the next bite from Q17.
```

- [ ] **Step 5: Write `willow/fylgja/skills/consent.md`**

```markdown
---
name: consent
description: Guardian sign-off for CHILD/TEEN users — SAFE protocol session authorization
---

# /consent — Guardian Sign-Off

Use when Sean says "approve [name] for today" or "sign off on [name]'s session".

## Sequence

1. **Identify user** — extract name from Sean's message. Look up in `willow/users/` via `mcp__willow__store_search`.
2. **Check role** — load user profile. If role is `adult`, no guardian authorization needed — inform Sean.
3. **For CHILD/TEEN users — present authorization checklist**:
   ```
   Guardian sign-off for: <name> (<role>)
   Session date: <today>

   Authorize (yes/no):
   [ ] Relationships stream
   [ ] Images stream
   [ ] Bookmarks stream

   Training data consent: no (default)

   Type "approved" to confirm, or specify which streams.
   ```
4. **On confirmation** — write to store:
   ```
   collection: willow/guardian_approvals
   record: {
     id: "approval-<name>-<YYYYMMDD>",
     user_id: "<id>",
     guardian_id: "sean",
     date: "<today>",
     streams_authorized: [...],
     training_consent: false,
     expires: "session"
   }
   ```
   via `mcp__willow__store_put`.
5. **Confirm** — "Session authorized for <name>. Expires at session close."
```

- [ ] **Step 6: Commit**

```bash
git add willow/fylgja/skills/startup.md willow/fylgja/skills/handoff.md \
        willow/fylgja/skills/status.md willow/fylgja/skills/shutdown.md \
        willow/fylgja/skills/consent.md
git commit -m "feat(fylgja): skills — 5 Willow-native skills (startup, handoff, status, shutdown, consent)"
```

---

### Task 3: Forked skills

**Five skills forked from superpowers, rewritten to use Willow MCP tools and 1.9 patterns.**

- [ ] **Step 1: Write `willow/fylgja/skills/brainstorming.md`**

```markdown
---
name: brainstorming
description: Structured brainstorm before any plan or implementation — Willow 1.9 fork
---

# Brainstorming

Use BEFORE entering plan mode or starting any implementation.

## Pre-load

```
ToolSearch query: "select:mcp__willow__willow_knowledge_search,mcp__willow__store_search"
```

## Steps

1. **Search existing KB** — call `mcp__willow__willow_knowledge_search` with the feature/problem as the query. Read any relevant atoms before forming opinions.
2. **Search prior session context** — call `mcp__willow__store_search` on `hanuman/atoms` with relevant keywords. Check if this problem was approached before.
3. **State the problem** — one sentence. What are we actually solving?
4. **Generate 3 approaches** — for each: name it, state the core tradeoff in one sentence.
5. **Recommend one** — say which and why in 2 sentences.
6. **Flag Fylgja constraints** — does this touch: MCP tools (use subprocess client), session state (use `_state.py`), hooks (wrap in try/except), settings.json (use `install.py`)?
7. **Stop** — do not implement until Sean confirms the approach.
```

- [ ] **Step 2: Write `willow/fylgja/skills/debugging.md`**

```markdown
---
name: debugging
description: Systematic bug hunt — check KB and prior sessions before reproducing
---

# Debugging

## Steps

1. **Pre-load tools**:
   ```
   ToolSearch query: "select:mcp__willow__willow_knowledge_search,mcp__willow__store_search"
   ```
2. **Search for prior context** — call `mcp__willow__store_search` on `hanuman/atoms` for the error message or module name. Check if this bug has been seen before.
3. **State the bug** — exact error, file:line if known, what was expected vs what happened.
4. **Identify the smallest reproduction** — what is the minimum input that triggers this?
5. **Hypothesize** — list 2-3 candidate causes. Ranked by likelihood.
6. **Test the top hypothesis first** — read the relevant file, check the relevant line. Confirm or eliminate.
7. **Fix only what is broken** — no surrounding cleanup, no refactoring. One surgical change.
8. **Run the relevant test** — confirm the fix holds. If no test exists, write one.
9. **Commit** — message format: `fix(<module>): <what was wrong> — <why it was wrong>`
```

- [ ] **Step 3: Write `willow/fylgja/skills/tdd.md`**

```markdown
---
name: tdd
description: Test-driven development for Willow 1.9 — willow_19_test schema, migration awareness
---

# TDD — Willow 1.9

## Rules

- Tests run against `willow_19_test` (set via `WILLOW_PG_DB=willow_19_test` in conftest).
- Never mock the database. Tests that need Postgres get a real `PgBridge` via the `bridge` fixture.
- Each behavior function is a standalone function — test it in isolation with mocked MCP calls.
- Hook handlers are tested by passing mock stdin, capturing stdout.

## Cycle

1. **Write the failing test first.** Run it. Confirm it fails with the expected error (ImportError, AssertionError — not a crash).
2. **Write the minimum code to pass.** No extra logic.
3. **Run the test.** Green? Move on. Red? Fix only what the test says is broken.
4. **Commit each green state.** Do not batch test + implementation into one commit.

## MCP Mocking Pattern

```python
from unittest.mock import patch
from willow.fylgja._mcp import call

def test_behavior_calls_mcp(tmp_path):
    with patch("willow.fylgja.events.mymodule.call") as mock_call:
        mock_call.return_value = {"status": "ok"}
        # run the behavior
        result = my_behavior("arg")
    mock_call.assert_called_once_with("tool_name", {"app_id": "hanuman", ...})
```

## Schema Note

`willow_19_test` is isolated from production. Migrations that add columns/tables must be applied to both `willow_19` and `willow_19_test`. The conftest `init_pg_schema` fixture handles this automatically for the test database.
```

- [ ] **Step 4: Write `willow/fylgja/skills/iterative-retrieval.md`**

```markdown
---
name: iterative-retrieval
description: Progressively refine a search across Willow KB, store, and JELES before reading files
---

# Iterative Retrieval

Use when looking for context about a topic before reading files or writing code.

## Retrieval Ladder (run in order, stop when you have enough)

**Rung 1 — KB search** (broadest, fastest):
```
ToolSearch: "select:mcp__willow__willow_knowledge_search"
```
Call `mcp__willow__willow_knowledge_search` with your topic. Read titles and summaries. If you find 2+ relevant atoms, go to Rung 3.

**Rung 2 — Store search** (collection-scoped):
```
ToolSearch: "select:mcp__willow__store_search"
```
Call `mcp__willow__store_search` on `hanuman/atoms` or `hanuman/file-index`. Useful when KB search returns nothing.

**Rung 3 — Temporal query** (if currency matters):
```
ToolSearch: "select:mcp__willow__willow_knowledge_at"
```
Call `mcp__willow__willow_knowledge_at` with `at_time` to get the state of the KB at a specific point.

**Rung 4 — JELES retrieval** (session history):
```
ToolSearch: "select:mcp__willow__willow_jeles_extract"
```
Call `mcp__willow__willow_jeles_extract` to pull from indexed session JSOLs.

**Rung 5 — File read** (last resort):
Only use Read tool if Rungs 1-4 returned nothing useful. Read the specific section, not the whole file.

## Rule

Never skip to Rung 5. The KB is the map. Files are the territory. Read the map first.
```

- [ ] **Step 5: Write `willow/fylgja/skills/learn.md`**

```markdown
---
name: learn
description: Extract a reusable pattern from this session and ingest it into Willow KB
---

# /learn — Extract and Ingest

Use when something non-obvious was discovered: a workaround, a subtle invariant, a constraint not in the code.

## What NOT to learn

- Code patterns derivable by reading the repo
- Git history (use `git log`)
- Task state from this session
- Anything already in CLAUDE.md

## Steps

1. **Name the pattern** — one short title. Examples: "Gleipnir rate window is per app_id not global", "knowledge_put ON CONFLICT does not preserve invalid_at"
2. **Write the atom to a file** — this is the F5 canon rule. Content goes in a file; the KB stores the path.
   ```
   Write to: ~/agents/hanuman/learned/<slug>.md
   Content: the full explanation, constraint, or workaround
   ```
3. **Ingest the file path** — call `mcp__willow__willow_knowledge_ingest`:
   ```
   title: <pattern name>
   summary: <file path from step 2>
   source_type: "learned"
   category: "pattern"
   domain: "hanuman"
   ```
4. **Confirm** — report the atom title and the file path stored.

## Rule

The KB stores the path. Never pass prose directly as `summary` or `content`. The file IS the content.
```

- [ ] **Step 6: Commit**

```bash
git add willow/fylgja/skills/brainstorming.md willow/fylgja/skills/debugging.md \
        willow/fylgja/skills/tdd.md willow/fylgja/skills/iterative-retrieval.md \
        willow/fylgja/skills/learn.md
git commit -m "feat(fylgja): skills — 5 forked skills (brainstorming, debugging, tdd, iterative-retrieval, learn)"
```

---

### Task 4: Extend `install.py` — plugin registration

**Modify `willow/fylgja/install.py` to also register `fylgja@local` in `enabledPlugins`.**

- [ ] **Step 1: Add failing tests to `tests/test_fylgja/test_install.py`**

```python
# Add to existing test_install.py

def test_apply_plugin_writes_enabled_plugins(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "sonnet", "enabledPlugins": {}}))
    from willow.fylgja.install import apply_plugin
    skills_path = PACKAGE_ROOT / "willow" / "fylgja" / "skills"
    apply_plugin(settings_path=settings, skills_path=skills_path, dry_run=False)
    content = json.loads(settings.read_text())
    assert any("fylgja" in k for k in content["enabledPlugins"])
    assert content["model"] == "sonnet"  # other keys preserved


def test_apply_plugin_dry_run_does_not_write(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"enabledPlugins": {}}))
    from willow.fylgja.install import apply_plugin
    skills_path = PACKAGE_ROOT / "willow" / "fylgja" / "skills"
    apply_plugin(settings_path=settings, skills_path=skills_path, dry_run=True)
    content = json.loads(settings.read_text())
    assert content == {"enabledPlugins": {}}
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_fylgja/test_install.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'apply_plugin'`

- [ ] **Step 3: Add `apply_plugin()` to `willow/fylgja/install.py`**

Add after `apply_hooks()`:

```python
def apply_plugin(settings_path: Path = _DEFAULT_SETTINGS,
                 skills_path: Path = None,
                 dry_run: bool = False) -> None:
    if skills_path is None:
        skills_path = _PACKAGE_ROOT / "willow" / "fylgja" / "skills"
    plugin_key = f"fylgja@{skills_path}"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}

    if dry_run:
        print(f"[install] Dry run — would add to enabledPlugins: {plugin_key!r}")
        return

    plugins = settings.get("enabledPlugins", {})
    plugins[plugin_key] = True
    settings["enabledPlugins"] = plugins
    tmp = settings_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2))
    tmp.replace(settings_path)
    print(f"[install] Plugin registered: {plugin_key}")
```

Also extend `main()` to call `apply_plugin()` when `--plugin` flag is passed:

```python
parser.add_argument("--plugin", action="store_true", help="Also register fylgja@local plugin")
# in main body:
if args.plugin:
    apply_plugin(settings_path=args.settings, dry_run=args.dry_run)
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_fylgja/test_install.py -v 2>&1 | tail -10
```

Expected: 6 passed (4 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/install.py tests/test_fylgja/test_install.py
git commit -m "feat(fylgja): install.py — apply_plugin() registers fylgja@local in enabledPlugins"
```

---

### Task 5: Wire and verify

- [ ] **Step 1: Full test run**

```bash
python3 -m pytest tests/test_fylgja/ -v 2>&1 | tail -15
```

Expected: all tests pass.

- [ ] **Step 2: Run install dry-run with --plugin flag**

```bash
python3 -m willow.fylgja.install --dry-run --plugin --settings /home/sean-campbell/.claude/settings.json
```

Review output. Confirm the plugin key points at the skills directory.

- [ ] **Step 3: Apply plugin to real settings.json**

```bash
python3 -m willow.fylgja.install --plugin --settings /home/sean-campbell/.claude/settings.json
```

- [ ] **Step 4: Verify settings.json**

Read `~/.claude/settings.json`. Confirm `enabledPlugins` has a `fylgja@<path>` key.

- [ ] **Step 5: Final commit + push**

```bash
git add -A
git commit -m "feat(fylgja): Plan 2 complete — skills plugin wired, fylgja@local registered"
git push origin master
```

---

## Self-Review

**Spec coverage:**
- ✅ `skills/plugin.json` — manifest (Task 1)
- ✅ Willow-native skills: startup, handoff, status, shutdown, consent (Task 2)
- ✅ Forked skills: brainstorming, debugging, tdd, iterative-retrieval, learn (Task 3)
- ✅ `install.py` extended with `apply_plugin()` (Task 4)
- ✅ Registered in settings.json (Task 5)

**Not in this plan (Plan 3):**
- Safety subsystem (`willow/fylgja/safety/`) — separate plan

ΔΣ=42
