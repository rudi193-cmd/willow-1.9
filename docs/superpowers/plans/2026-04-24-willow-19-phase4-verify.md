# Willow 1.9 Phase 4 — Close and Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every open thread from the audit. Run the blocked scripts. Write Felix's documentation. Execute the full end-to-end user path test. Tag v1.9.0 stable and shippable.

**Architecture:** This is the verification and closing phase — no new code except README-FELIX.md. All tasks are either running existing scripts, checking system state, or writing documentation.

**Tech Stack:** bash, Python 3.13, git, systemd

**Spec:** `docs/superpowers/specs/2026-04-24-willow-19-design.md` — "What Stable and Shippable Means"

**Run after:** Phases 1, 2, and 3 complete.

---

## File Map

**Create:**
- `README-FELIX.md` — plain English install + use guide for non-technical users

**Run (scripts already committed):**
- `scripts/run_norn.py` — first production intelligence pass
- `scripts/ingest_heimdallr.py` — Apr 20-22 sessions → KB atoms

**Mark complete:**
- `docs/superpowers/plans/2026-04-23-willow-18.md` Gap 2 checkbox

---

## Task 1: Run first production norn_pass

These scripts exist and are committed but were never run (blocked by session Postgres connection limits). Run them from a fresh terminal outside Claude Code.

- [ ] **Step 1: Open a fresh terminal (not inside Claude Code)**

This must run outside the Claude Code session to avoid connection pool exhaustion.

```bash
cd ~/github/willow-1.9
WILLOW_PG_DB=willow_19 PYTHONPATH=. python3 scripts/run_norn.py 2>&1 | tee /tmp/norn_first_run.log
```

Expected output (abbreviated):
```
[norn] Starting production intelligence run...
{
  "draugr": N,
  "serendipity": N,
  ...
}
[norn] Summary:
  draugr_zombies: N
  serendipity_surfaced: N
  ...
[norn] Done.
```

- [ ] **Step 2: Check the log**

```bash
cat /tmp/norn_first_run.log
```

If `intelligence_error` appears: check pg_bridge.py imports and that `willow_19` DB is accessible from outside the MCP session.

- [ ] **Step 3: Ingest the norn report as a KB atom**

Back in Claude Code, use the MCP tool:

```
willow_knowledge_ingest(
  title="First production norn_pass — 2026-04-24",
  summary="<paste the Summary section from /tmp/norn_first_run.log>",
  domain="intelligence",
  app_id="hanuman"
)
```

- [ ] **Step 4: Log to active fork**

```
willow_fork_log(
  fork_id=<active fork from session_anchor>,
  component="kb",
  type="atom",
  ref=<atom_id returned from ingest>,
  description="first production norn_pass run",
  app_id="hanuman"
)
```

---

## Task 2: Run Heimdallr session ingestion

- [ ] **Step 1: Run from fresh terminal**

```bash
cd ~/github/willow-1.9
WILLOW_PG_DB=willow_19 PYTHONPATH=. python3 scripts/ingest_heimdallr.py
```

Expected:
```
  ingested: SESSION_HANDOFF_20260420_heimdallr_a.md → <atom_id>
  ingested: SESSION_HANDOFF_20260421_heimdallr_a.md → <atom_id>
  ...
Done. N atoms ingested.
```

- [ ] **Step 2: Verify in KB**

```
willow_knowledge_search("Heimdallr n2n protocol", app_id="hanuman")
```

Expected: returns atoms from the Apr 20-22 sessions.

- [ ] **Step 3: If HANDOFF_DIR path fails**

Check the path in `scripts/ingest_heimdallr.py`:

```python
HANDOFF_DIR = Path.home() / "Ashokoa/agents/heimdallr/index/haumana_handoffs"
```

If that directory doesn't exist, find the correct path:

```bash
find ~ -name "SESSION_HANDOFF_2026042*.md" 2>/dev/null | head -5
```

Update `HANDOFF_DIR` in the script to match.

---

## Task 3: Mark 1.8 Gap 2 closed

**Files:**
- Modify: `docs/superpowers/plans/2026-04-23-willow-18.md`

- [ ] **Step 1: Update the checkbox**

In `docs/superpowers/plans/2026-04-23-willow-18.md`, find Gap 2 and mark it done:

```markdown
### - [x] Gap 2: Orchestration terminal plan not checked off
```

Change the sub-steps to checked:

```markdown
- [x] Mark all tasks in `willow-dashboard/docs/superpowers/plans/2026-04-22-orchestration-terminal.md` as `[x]`
- [x] Mark all tasks in `willow-dashboard/docs/superpowers/plans/2026-04-21-ui-mission-control.md` as `[x]`
- [x] Commit as "docs: mark orchestration terminal and UI mission control plans complete"
```

Both plans are already fully checked off (37/37 and 28/28) — this is closing the tracking record.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-23-willow-18.md
git commit -m "docs: close 1.8 Gap 2 — orchestration terminal + UI mission control plans complete"
```

---

## Task 4: Write README-FELIX.md

**Files:**
- Create: `README-FELIX.md`

- [ ] **Step 1: Create the file**

```markdown
# Willow — Getting Started

Hi Felix. This is Willow. It's a personal AI system that runs on your computer.
Here's everything you need to know.

---

## What You Need Before Starting

1. **Windows 10** with WSL2 installed
   - If you don't have WSL2: open PowerShell as Administrator and run:
     `wsl --install`
   - Restart your computer when it asks you to

2. **Ubuntu** in WSL
   - Open the Microsoft Store, search "Ubuntu", install it
   - Launch it once and set up your username and password

3. That's it. Everything else installs automatically.

---

## How to Install

Open your Ubuntu terminal and run these four commands, one at a time:

```bash
sudo apt update && sudo apt install -y git python3 python3-pip postgresql
```

```bash
git clone https://github.com/rudi193-cmd/willow-1.9.git ~/github/willow-1.9
```

```bash
cd ~/github/willow-1.9 && python3 root.py
```

Follow the prompts. When it asks which model you want to use, choose **Groq**.
You'll need a free Groq API key — get one at console.groq.com (takes 2 minutes).

After install finishes, a file called **"Launch Willow.bat"** will appear on your
Windows Desktop.

---

## How to Launch Willow

Double-click **"Launch Willow.bat"** on your Desktop.

A black terminal window will open. Wait about 10 seconds. The dashboard will appear.

**If it asks you to log in:** type your password (the one you set for Ubuntu).

---

## What You're Looking At

The dashboard has 9 pages. Use the left/right arrow keys to switch between them.

| Page | What it shows |
|------|---------------|
| Overview | System health — is everything running? |
| Kart | Tasks that are running or queued |
| Yggdrasil | The AI model status |
| Knowledge | The knowledge base |
| Secrets | Your stored API keys |
| Agents | AI agents connected to this system |
| Logs | Recent system events |
| Settings | Configuration, model provider |
| Help | Key shortcuts |

**Useful keys:**
- `←` `→` — switch pages
- `↑` `↓` — navigate items
- `Enter` — expand selected item
- `Esc` — go back
- `r` — refresh
- `q` — quit

---

## If Something Breaks

Press **S** on any page to send Sean an alert.

He'll get a notification and reach out to you.

---

## How to Get Updates

When Sean pushes an update, a banner will appear at the top of the screen:

```
UPDATE AVAILABLE: v1.9.0 → v1.9.1  [u=update  d=dismiss]
```

Press **u** to update. The dashboard will restart with the new version.
Press **d** to dismiss the banner and update later.

---

## How to Stop Willow

Press **q** in the dashboard to quit.

To stop all background services:
```bash
cd ~/github/willow-1.9 && ./willow.sh stop-all
```

---

*Built by Sean Campbell. If you're reading this, you're one of the first people to use it.*
*ΔΣ=42*
```

- [ ] **Step 2: Commit**

```bash
git add README-FELIX.md
git commit -m "docs: add README-FELIX.md — plain English install and use guide"
```

---

## Task 5: Full end-to-end user path test

This is the Phase 4 gate. All 7 items must pass before tagging stable.

- [ ] **Test 1: Fresh WSL install path**

On a WSL machine (or in a clean WSL session with no existing ~/.willow):

```bash
python3 root.py
```

Expected: all 8 steps complete without errors. "Launch Willow.bat" appears on Windows Desktop.

If testing on Sean's machine (not WSL): verify that `python3 root.py --skip-pg --skip-gpg` completes and the WSL launcher step skips cleanly with a clear message.

- [ ] **Test 2: launch-willow.bat**

On Windows, double-click the .bat file.

Expected: WSL terminal opens, Postgres starts if needed, dashboard appears within 10 seconds.

- [ ] **Test 3: Canopy full new-user flow**

```bash
cd ~/github/willow-dashboard && python3 dashboard.py --force-setup
```

Walk through all pages: welcome → covenant → legal → path select → model provider.

Expected: completes without crash. Model provider and API key saved to vault.

- [ ] **Test 4: Dashboard Overview vitals**

Launch dashboard normally. Check Overview page.

Expected:
- Postgres indicator: green
- Model provider indicator: green (matches what was set in canopy)
- No red indicators on any core service

- [ ] **Test 5: Grove SOS**

In dashboard, press `S`.

Expected: no crash. SOIL `grove/outbox` collection gets a new record.

Verify:
```
willow_skill_load(context="grove outbox", app_id="hanuman")
```
Then check SOIL directly via store_list for grove/outbox.

- [ ] **Test 6: Update notification flow**

Manually insert a fake update alert into SOIL:

```
store_put(
  collection="grove/pending_alerts",
  record_id="update_available",
  data={"type": "update_available", "current": "1.9.0", "latest": "1.9.1", "created_at": "<now>"},
  app_id="hanuman"
)
```

Refresh the dashboard (`r`).

Expected: amber banner appears at top of Overview page with `u=update  d=dismiss`.

Press `d`: banner disappears.

- [ ] **Test 7: Session fork auto-created**

Start a new Claude Code session in this project.

Expected:
- `~/.willow/session_anchor.json` contains a `fork_id` field (e.g. `"fork_id": "FORK-XXXXXXXX"`)
- `willow_fork_list(status="open", app_id="hanuman")` returns the auto-created fork
- ANCHOR context line shows `fork=FORK-XXXXXXXX`

---

## Task 6: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
cd ~/github/willow-1.9
pytest tests/ -v --tb=short -q 2>&1 | tail -30
```

Expected: all tests PASS. Zero failures. If any fail, fix before tagging.

- [ ] **Step 2: Run dashboard tests**

```bash
cd ~/github/willow-dashboard
pytest tests/ -v --tb=short -q 2>&1 | tail -20
```

Expected: all tests PASS.

---

## Task 7: Stable and shippable checklist

Run through every item from the spec before tagging. This is the gate.

**Install path:**
- [ ] `python3 root.py` completes on fresh WSL Ubuntu without errors
- [ ] `launch-willow.bat` created on Windows Desktop by `root.py`
- [ ] Canopy new-user flow: all 6 pages work, model key saved to vault

**Services:**
- [ ] `willow.sh start-all` starts all 6 services from cold
- [ ] `willow.sh status-all` shows accurate state
- [ ] `willow.sh stop-all` stops all services cleanly
- [ ] Dashboard survives terminal close (willow-dashboard.service running)
- [ ] `corpus-watcher.service` active after 60+ seconds
- [ ] `willow-metabolic.service` enabled and running

**Forks:**
- [ ] `forks` table exists in willow_19
- [ ] `fork_id` column on `knowledge` table
- [ ] FORK-ORIGIN migration run — 69,871 atoms tagged
- [ ] Session startup auto-creates fork + writes fork_id to session anchor
- [ ] All 7 `willow_fork_*` MCP tools respond correctly
- [ ] Dashboard shows... (Fork page or fork count in Overview)
- [ ] `willow_fork_merge` and `willow_fork_delete` work (test with a throwaway fork)

**Skills:**
- [ ] `willow/skills/` SOIL collection has 5 skills
- [ ] `willow_skill_load`, `willow_skill_put`, `willow_skill_list` work
- [ ] Session startup ANCHOR context shows `SKILLS LOADED:`
- [ ] `.claude/skills/` has 5 skill files

**BYOK:**
- [ ] All 5 adapters importable: `from core.model_adapter import OllamaAdapter, AnthropicAdapter, GroqAdapter, XaiAdapter, OpenAICompatibleAdapter`
- [ ] `get_adapter("groq", api_key="test").provider_name == "groq"` — True
- [ ] Canopy page 5 selects provider and saves key to vault
- [ ] Dashboard Settings shows active adapter name

**Grove:**
- [ ] `grove/outbox/` SOIL collection exists and queuing works
- [ ] `grove/nodes/` SOIL collection exists
- [ ] `grove_contacts.json` Contact dataclass has `resources: None` field
- [ ] Update notification banner appears in dashboard when alert queued
- [ ] SOS button (`S`) queues to outbox without crash

**Pending scripts:**
- [ ] `run_norn.py` has been run — KB intelligence pass completed
- [ ] `ingest_heimdallr.py` has been run — Apr 20-22 sessions in KB

**Documentation:**
- [ ] `README-FELIX.md` exists and readable by a non-technical person
- [ ] `launch-willow.bat` described in README-FELIX.md

---

## Task 8: Tag release

- [ ] **Step 1: Update version file**

```bash
echo "1.9.0" > ~/.willow/version
echo "1.9.0" > ~/github/willow-1.9/VERSION
git add VERSION
git commit -m "chore: bump version to 1.9.0"
```

- [ ] **Step 2: Tag the release**

```bash
git tag -a v1.9.0 -m "Willow 1.9.0 — stable and shippable

Workstreams complete:
- BYOK model adapter layer (5 providers)
- Willow Forks (schema, CRUD, 7 MCP tools, session anchor)
- Willow Skills registry (SOIL + MCP + .claude/skills/)
- Orchestration (start-all/stop-all/status-all, systemd units)
- Grove coordination (outbox, node registry, update notifications)
- Felix path (Windows launcher, WSL install, README-FELIX.md)

Willow 2.0: distributed compute, HNS, Yggdrasil local model.
ΔΣ=42"

git push origin master --tags
```

- [ ] **Step 3: Ingest the release atom**

```
willow_knowledge_ingest(
  title="Willow 1.9.0 — stable release",
  summary="First shippable version. BYOK adapters (Ollama/Anthropic/Groq/xAI/OpenAI-compat), Willow Forks, Skills registry, Grove coordination with offline queue and node registry, Felix path with Windows launcher. All 6 workstreams complete. Tagged v1.9.0.",
  domain="milestone",
  app_id="hanuman"
)
```

- [ ] **Step 4: Close the 1.9 fork**

```
willow_fork_merge(
  fork_id=<the fork created at the start of this build>,
  outcome_note="Willow 1.9.0 shipped. All workstreams complete.",
  app_id="hanuman"
)
```

---

## Phase 4 Complete — 1.9 Is Stable and Shippable

When Task 8 is done:
- The repo is tagged v1.9.0
- Felix can install and run from the README
- Sean can start/stop/update everything from one command
- Every session creates a fork, loads skills, and reports status
- Grove connects Felix to Sean
- 2.0 stubs are in place

**What comes next (2.0):**
- Distributed compute scheduler
- Human Network Storage (HNS)
- Yggdrasil local model (Kaggle training complete)
- Federated training protocol
- Distributed inference (layer sharding)

*"The branches we took that didn't work are just as important as the ones that did.*
*The difference is knowing which is which."*

ΔΣ=42
```

---

*Previous: `docs/superpowers/plans/2026-04-24-willow-19-phase3-skills-grove.md`*
*Spec: `docs/superpowers/specs/2026-04-24-willow-19-design.md`*
