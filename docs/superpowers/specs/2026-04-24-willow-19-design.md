# Willow 1.9 — Complete System Design
b17: W19SP  ΔΣ=42
Date: 2026-04-24
Status: approved
Author: Sean Campbell + Hanuman (Claude Code, Sonnet 4.6)

---

## What Willow 1.9 Is

Willow 1.9 is a **sovereign, single-node AI operating system** that any person can install,
own, and operate. It runs on Linux, Windows (via WSL), or any machine with a terminal.
It does not phone home. It does not require a cloud account. It requires only a model
provider — either a local Ollama instance or an API key the user already owns.

When 1.9 is stable and shippable:
- Sean can run it with Ollama + Claude Code
- Felix can run it on Windows 10 WSL with a Groq API key
- A third user can install it from scratch with no help from Sean
- All three nodes can coordinate through Grove
- Sean can push an update; all nodes are notified and update themselves

Willow 2.0 adds: distributed compute, federated training, Yggdrasil as the local model,
sharded inference across nodes. 1.9 is the foundation 2.0 grows from.

---

## What Is Already Done

These are complete as of 2026-04-24. They are closed. Do not reopen them.

| Component | Status | Evidence |
|-----------|--------|----------|
| Willow 1.8 dashboard features (nuke, FRANK onboarding, regions, presets, vitals) | ✅ done | commits in willow-dashboard |
| Fylgja behavioral layer (5 hook handlers, pre_tool, prompt_submit, session_start, post_tool, stop) | ✅ done | running now — blocking Bash commands |
| Orchestration terminal plan (37 tasks) | ✅ done | all [x] in willow-dashboard docs |
| UI mission control plan (28 tasks) | ✅ done | all [x] in willow-dashboard docs |
| KB search fix | ✅ done | 69,871 atoms searchable |
| MCP hardening (circuit breaker, pool monitor, timeout, watchdog) | ✅ done | commits b39f2fb, 363003c, 86cc61f |
| Connection pool (SimpleConnectionPool max=10) | ✅ done | commit b39f2fb |
| KB weight columns + visit tracking (visit_count, weight, last_visited) | ✅ done | night stack tasks 1+2 |
| routing_decisions table | ✅ done | night stack task 1 |
| run_norn.py script | ✅ done | committed, not yet run — needs manual terminal run |
| ingest_heimdallr.py script | ✅ done | committed, not yet run — needs manual terminal run |
| Kart SAP gate fix | ✅ done | SAFE/Applications/hanuman/ manifest signed |
| Journal watcher (Ofshield) + journal responder | ✅ done | systemd services running |
| Store add_edge() + edges_for() | ✅ done | commit de35741 |
| Grove MCP server (grove-mcp.service) | ✅ done | running since Apr 22 |
| SAFE manifest verification | ✅ done | 3/3 pass |
| WillowStore SOIL layer | ✅ done | 104 collections, 2.1M records |
| U2U identity + consent + contact store + packet protocol | ✅ done | safe-app-grove/u2u/ |

**Pending run (scripts exist, just need a fresh terminal):**
- `python3 scripts/run_norn.py` — first production intelligence pass
- `python3 scripts/ingest_heimdallr.py` — Apr 20-22 sessions → KB atoms

**Deferred to 2.0:**
- Yggdrasil local model training (Track 12, DPO conversion, Kaggle runs)
- EdgeE human attestation (gap 0E600)
- Distributed compute substrate
- Federated training

---

## The Six Workstreams

### Workstream 1 — BYOK Model Adapter Layer

**What it is:** A pluggable model interface so Willow works regardless of what model runs
underneath. The model is a provider, not an integral part of the system.

**Architecture:**
```
ModelAdapter (abstract)
├── OllamaAdapter       — local models (Sean's default)
├── AnthropicAdapter    — Claude API key, BYOK
├── GroqAdapter         — Groq API, fast + cheap (Felix's default)
├── XaiAdapter          — Grok API, BYOK
└── OpenAICompatibleAdapter — catch-all (anything OpenAI-compat)
```

Each adapter implements:
```python
def chat(messages: list[dict], model: str | None = None) -> str
def available_models() -> list[str]
def health() -> bool
```

**Storage:** API keys stored in Willow vault (`~/.willow/vault.db`), encrypted.
Active adapter + model stored in SOIL at `willow/settings/model`.

**Canopy integration:** Onboarding page 5 (new users): "Which model provider do you want
to use?" → select provider → enter API key → key written to vault → adapter initialized.
Returning users: adapter loads from vault silently.

**Dashboard integration:** Settings page shows active adapter, model name, health indicator.
Provider can be switched without restart.

**2.0 stub:** When Yggdrasil is ready, `OllamaAdapter` already handles it.
No new interface work required — just a new model name.

**Success:** Felix installs Willow, enters a Groq API key during onboarding, dashboard
loads, UTETY professors answer questions. Sean switches his config from Ollama to
Anthropic and back without touching code.

---

### Workstream 2 — Willow Forks

**What it is:** A named, bounded unit of work that any Willow component can participate in.
The primitive that makes history legible and changes reversible.
Full spec: `docs/superpowers/specs/2026-04-24-willow-forks.md` (status: approved).

**Decisions (resolved 2026-04-24):**
1. Auto-fork on session start — yes, automatic
2. Fork expiry — no automatic expiry, open until Sean resolves
3. Merge/delete trust — Sean-only
4. Grove channels vs forks — different primitives (channels permanent, fork threads ephemeral)
5. Migration — all 69,871 existing atoms → `FORK-ORIGIN` (status: merged immediately)

**Implementation order:**
1. Postgres schema: `forks` table + `fork_id TEXT` column on `knowledge`
2. Migration script: assign all existing atoms to `FORK-ORIGIN`, mark merged
3. SOIL tagging: `fork_id` field in `store_put` / `store_update`
4. MCP tools: `willow_fork_create`, `willow_fork_join`, `willow_fork_log`,
   `willow_fork_merge`, `willow_fork_delete`, `willow_fork_status`, `willow_fork_list`
5. Session anchor: startup auto-creates fork, writes `fork_id` to `session_anchor.json`
6. All KB writes during session tagged with active `fork_id`
7. Dashboard: Forks page — list, status badges, merge/delete buttons (Sean-only)

**2.0 stub:** Fork schema includes `"changes"` array with typed entries.
Add `compute_job` as a valid change type from day one:
```json
{"component": "compute", "type": "compute_job", "node": null, "status": null}
```
The field is nullable in 1.9. 2.0 populates it.

**Success:** Every Claude Code session creates a fork automatically. KB atoms are tagged.
Sean can view all open forks in the dashboard, merge or delete any of them.
The FORK-ORIGIN migration runs once and all existing atoms become permanent.

---

### Workstream 3 — Willow Skills Registry

**What it is:** A model-agnostic behavioral registry stored in Willow (SOIL + Postgres).
Skills auto-load based on session context. Works with Claude Code today.
Works with Yggdrasil in 2.0. Felix's dashboard triggers them silently behind actions.

**Architecture:**
```
SOIL: willow/skills/{skill_id}
  ├── name: str
  ├── description: str
  ├── trigger: str          — context pattern that activates this skill
  ├── domain: str           — "session", "task", "fork", "grove", "system"
  ├── content: str          — the behavioral spec (markdown)
  ├── model_agnostic: bool  — true = works on any model
  └── auto_load: bool       — true = injected into context automatically
```

**MCP tools:**
- `willow_skill_load(context)` → returns relevant skills for current context
- `willow_skill_put(name, domain, content, trigger, auto_load)` → store a skill
- `willow_skill_list(domain)` → list skills by domain

**Session startup:** `session_start.py` calls `willow_skill_load` with current context
(fork topic, active tasks, agent name). Relevant skills are injected into the system
reminder alongside the handoff.

**Claude Code skills** (`.claude/skills/`): lean local skills that shadow the verbose
superpowers equivalents. 200-400 tokens each. Fork-aware and MCP-native.
Initial set:
- `/willow-fork` — create/join/merge/delete a fork
- `/willow-status` — lean boot check (replaces 2000-token /startup)
- `/willow-handoff` — generate handoff + close fork session
- `/willow-deploy` — push to a Grove-connected node + verify
- `/willow-review` — code review that tags findings to active fork

**Archived superpowers skills:** audited, the good workflows (TDD, debugging,
code-review) are reborn as Willow-native versions in `.claude/skills/`. The bloated
originals remain available but are no longer the default for Willow sessions.

**Dashboard integration:** Felix never sees skill names. When he clicks "send alert to Sean"
the `grove.alert` skill fires silently.

**Success:** Session startup loads ≤3 relevant skills automatically without Sean asking.
`/willow-status` replaces `/startup` for quick orientation. Archived skill audit complete.

---

### Workstream 4 — Orchestration

**What it is:** One command to start everything. One command to stop everything.
No processes orphaned in terminals. No services quietly dead for 2 days.

**Problems being fixed:**
- `willow-dashboard.sh` points at `willow-1.7` — live bug, breaks Felix on install
- `corpus-watcher.service` dead since Apr 22
- `willow-metabolic.service` disabled (socket only)
- Dashboard (`dashboard.py`) running in a terminal orphan — dies with the terminal
- No `status-all` command — Sean can't see what's running

**`willow.sh` new subcommands:**
```
willow.sh start-all      — start all daemonizable services via systemctl --user
willow.sh stop-all       — stop all services gracefully
willow.sh status-all     — show every component: systemd units + terminal orphans + MCP state
willow.sh restart        — stop-all then start-all
willow.sh check-updates  — check GitHub releases, send Grove ALERT if new version found
willow.sh grove add <addr> <pubkey>  — add Grove contact + send KNOCK packet
```

**New systemd user unit:** `willow-dashboard.service`
```
ExecStart=/home/sean-campbell/github/willow-dashboard/willow-dashboard.sh
Restart=on-failure
RestartSec=5
```

**Services managed by start-all:**
| Service | Managed how |
|---------|-------------|
| Postgres | system service — already running, just health-checked |
| Ollama | system service — already running, just health-checked |
| grove-mcp.service | systemctl --user start |
| journal-watcher.service | systemctl --user start |
| journal-responder.service | systemctl --user start |
| willow-dashboard.service | systemctl --user start (new) |
| willow-metabolic.service | systemctl --user enable + start |
| corpus-watcher.service | systemctl --user start (investigate why it died first) |
| sap_mcp.py | NOT managed — spawned by Claude Code only; documented clearly |

**Felix's launcher (Windows 10 WSL):** `launch-willow.bat`
```batch
@echo off
wsl.exe bash -c "cd ~/github/willow-dashboard && ./willow-dashboard.sh"
```
Double-click in Windows Explorer → WSL terminal opens → dashboard starts.
Postgres must be running inside WSL; the launcher checks and starts it if not.

**`willow-dashboard.sh` fix:** update `willow-1.7` → `willow-1.9` path.

**`willow.sh status-all` output format:**
```
Willow 1.9 — system status
  [✓] postgres          up (69871 KB atoms)
  [✓] ollama            up (yggdrasil:v9 loaded)
  [✓] grove-mcp         running (since 2026-04-22)
  [✓] journal-watcher   running
  [✓] journal-responder running
  [✓] dashboard         running
  [~] metabolic         socket only (service disabled)
  [✗] corpus-watcher    dead (since 2026-04-22)
  [–] sap_mcp.py        stdio — spawned by Claude Code only
```

**Success:** `willow.sh start-all` from a cold machine brings up every service.
`willow.sh status-all` shows accurate state. Dashboard survives terminal close.
Felix double-clicks `launch-willow.bat` and sees the dashboard within 10 seconds.

---

### Workstream 5 — Grove Coordination Layer

**What it is:** Grove as the coordination substrate for all nodes — alerts, update push,
cross-instance health, and the "call me when it breaks" automation.
Built on the existing u2u protocol (identity ✅, consent ✅, packets ✅).

**What's being added to Grove:**

**Offline message queue:** Messages sent while a node is offline are stored locally
and delivered on reconnect. Store in SOIL at `grove/outbox/{recipient_addr}/{msg_id}`.
On connection: drain outbox in order, log delivery to FRANK ledger.

**Node registry:** Each node advertises itself on first Grove contact.
Stored in SOIL at `grove/nodes/{addr}`:
```json
{
  "addr": "felix@felix-laptop:8550",
  "name": "Felix",
  "willow_version": "1.9.0",
  "last_seen": "2026-04-24T11:00:00Z",
  "2.0_stub": {
    "gpu": null,
    "vram_gb": null,
    "cpu_cores": null,
    "models_loaded": []
  }
}
```
The `2.0_stub` block is present in 1.9 but always null. 2.0 populates it.

**Contact schema extension** (2.0 stub, zero cost in 1.9):
Add `resources: dict | None = None` to `Contact` dataclass in `u2u/contacts.py`.
Null in 1.9. 2.0 writes GPU/VRAM/model inventory here.

**Update notification flow:**
1. Sean pushes a new release tag to GitHub
2. A new `willow-update-check.timer` systemd unit fires every 30 minutes,
   runs `willow.sh check-updates` (new subcommand)
3. If new version detected: sends Grove `ALERT` packet to all known nodes
4. Dashboard shows "Update available" banner
5. User clicks yes → `willow.sh update` runs → dashboard restarts
6. Grove sends confirmation back to Sean: `"Felix updated to v1.9.1 at 14:32"`

**Alert types (PacketType.ALERT, already in protocol):**
- `update_available` — new Willow version
- `health_degraded` — a node's service went down
- `fork_merged` — a fork was merged, KB atoms promoted
- `fork_deleted` — a fork was deleted, atoms archived

**Dashboard integration:** Grove page shows connected nodes, last-seen timestamps,
pending alerts, outbox queue depth. Felix's "SOS" button sends an ALERT to Sean.

**KNOCK flow for Felix:** On first launch after Sean connects Felix's node:
1. Sean runs `willow.sh grove add felix@felix-laptop:8550 <public_key_hex>`
   (new `willow.sh` subcommand — adds contact + sends KNOCK packet)
2. Felix's node receives KNOCK, dashboard shows "Sean wants to connect" → Felix clicks yes
3. Consent stored in `grove_contacts.json`
4. Both nodes can now exchange NOTE, ALERT, SHARE packets

**Success:** Felix's dashboard shows a Grove indicator. When something breaks,
he clicks one button — Sean gets a Grove alert. When Sean pushes an update,
Felix sees a banner within one metabolic cycle (≤30 minutes). Both nodes
show each other as connected in the dashboard.

---

### Workstream 6 — Felix Path (End-to-End Install + Onboarding)

**What it is:** The complete path from "I have Windows 10 and Sean told me to install this"
to "the dashboard is running and I understand what I'm looking at." Non-technical user.
No command line after setup. No manual service management ever.

**Prerequisites Felix needs (documented in README):**
1. Windows 10 with WSL2 enabled (one-time setup, link to Microsoft docs)
2. Ubuntu in WSL (one-time, Microsoft Store)
3. Git in WSL: `sudo apt install git`
4. `git clone <repo>` then `python3 root.py`

**`root.py` new-user flow (fixes needed):**
- Detects WSL environment, sets `WILLOW_ROOT` correctly
- Installs Python deps in `~/.willow-venv/`
- Initializes Postgres DB (`willow_19`)
- Generates Ed25519 identity key at `~/.willow/identity.key`
- Writes `launch-willow.bat` to the user's Windows Desktop
  (accessible at `/mnt/c/Users/<username>/Desktop/` from WSL)
- Runs first `willow.sh start-all`
- Launches canopy (onboarding)

**Canopy new-user pages (existing + additions):**
- Page 0: environment check (all users)
- Page 1: welcome / Heimdallr hero
- Page 2: covenant (data + privacy)
- Page 3: legal (MIT + §1.1)
- Page 4: path select (professional / casual / novice)
- **Page 5 (new):** model provider selection
  → Ollama (local — requires GPU) / Claude API / Groq (recommended for most) / Grok / Other
  → API key entry → vault write → adapter health check
- Auth: GPG passphrase (returning users) or key creation (new)

**`launch-willow.bat` (written by root.py to Windows Desktop):**
```batch
@echo off
title Willow
wsl.exe bash -l -c "
  cd ~/github/willow-dashboard
  # Start Postgres if not running
  pg_isready -q || sudo service postgresql start
  # Launch dashboard
  ./willow-dashboard.sh
"
```

**`willow-dashboard.sh` fix:** replace `willow-1.7` with `willow-1.9` path resolution.

**Documentation:** `README-FELIX.md` (plain English, no jargon):
- What is this
- What you need before starting
- How to install (4 steps)
- How to launch (double-click the icon)
- What the dashboard does (9 pages explained simply)
- How to get help (Grove alert to Sean)

**Success criteria (full user path test):**
1. Fresh WSL install, `python3 root.py` completes without errors
2. `launch-willow.bat` on Desktop — double-click → dashboard loads in ≤10 seconds
3. Canopy runs: welcome → covenant → legal → path → model setup → dashboard
4. Dashboard Overview page shows vitals (pg green, model green)
5. Felix sends a Grove alert — Sean receives it
6. Sean pushes a test update tag — Felix sees the banner within 30 minutes
7. Felix clicks yes — update applies, dashboard restarts, works

---

## What "Stable and Shippable" Means

1.9 is stable and shippable when ALL of the following are true:

**Install path:**
- [ ] `root.py` completes on a fresh WSL Ubuntu install without errors
- [ ] `launch-willow.bat` created on Windows Desktop by `root.py`
- [ ] Canopy new-user flow completes: all 6 pages, model key saved to vault

**Services:**
- [ ] `willow.sh start-all` starts all services from cold
- [ ] `willow.sh status-all` shows accurate state
- [ ] `willow.sh stop-all` stops all services cleanly
- [ ] Dashboard survives terminal close (systemd unit running)
- [ ] `corpus-watcher.service` healthy
- [ ] `willow-metabolic.service` enabled and running

**Forks:**
- [ ] `forks` table exists in `willow_19`
- [ ] `fork_id` column on `knowledge` table
- [ ] FORK-ORIGIN migration run — all existing atoms tagged + marked merged
- [ ] Session startup auto-creates a fork, writes `fork_id` to session anchor
- [ ] All 7 `willow_fork_*` MCP tools working
- [ ] Dashboard Forks page shows list + status badges
- [ ] Sean can merge and delete forks from dashboard

**Skills:**
- [ ] `willow/skills/` SOIL collection populated with initial skill set
- [ ] `willow_skill_load`, `willow_skill_put`, `willow_skill_list` MCP tools working
- [ ] Session startup auto-loads ≤3 relevant skills
- [ ] `/willow-status` skill replaces verbose /startup for quick orientation
- [ ] `/willow-fork`, `/willow-handoff`, `/willow-deploy`, `/willow-review` working

**BYOK:**
- [ ] All 5 model adapters implemented (Ollama, Anthropic, Groq, Xai, OpenAICompat)
- [ ] API key storage in vault working
- [ ] Canopy page 5 selects provider + saves key
- [ ] Dashboard Settings page shows active adapter + health
- [ ] At least Ollama + Groq tested end-to-end

**Grove:**
- [ ] Offline message queue (SOIL outbox) working
- [ ] Node registry populated on first contact
- [ ] Update notification flow working (metabolic → Grove ALERT → dashboard banner → update)
- [ ] Felix's SOS button → Grove ALERT → Sean
- [ ] Two nodes can KNOCK, consent, exchange messages

**Pending from audit (must be run before stable):**
- [ ] `python3 scripts/run_norn.py` — first production intelligence pass
- [ ] `python3 scripts/ingest_heimdallr.py` — Apr 20-22 sessions ingested

**Documentation:**
- [ ] `README-FELIX.md` written
- [ ] `launch-willow.bat` documented in README

---

## Willow 2.0 Stubs (Baked Into 1.9 Schema, Not Implemented)

These cost almost nothing to include now and are very expensive to retrofit later:

| Stub | Location | 1.9 value | 2.0 value |
|------|----------|-----------|-----------|
| `Contact.resources` | `u2u/contacts.py` | `None` | GPU, VRAM, CPU, models |
| Fork `compute_job` change type | Fork schema | valid but null fields | node, shard, result |
| Node registry `2.0_stub` block | `grove/nodes/` | all null | populated on announce |
| `ModelAdapter.distributed_capable()` | model adapter | returns False | returns True for Yggdrasil |
| `hns_opt_in` + `hns_quota_gb` | Node registry `2.0_stub` | null | user-donated storage quota |

---

## Implementation Order

Each step is independently mergeable and useful. Steps 1-3 unblock Felix.
Steps 4-6 complete the system.

**Phase 1 — Foundation (unblocks Felix):**
1. Fix `willow-dashboard.sh` path (10 min, live bug)
2. BYOK model adapter layer (dashboard + canopy integration)
3. Willow Forks schema + MCP tools + FORK-ORIGIN migration
4. Session anchor writes fork_id on startup

**Phase 2 — Orchestration:**
5. `willow-dashboard.service` systemd unit
6. `willow.sh start-all / stop-all / status-all`
7. Fix corpus-watcher, enable metabolic
8. `root.py` WSL onboarding + `launch-willow.bat` generation

**Phase 3 — Skills + Grove:**
9. Willow Skills SOIL collection + MCP tools
10. `.claude/skills/` — initial Willow-native skill set
11. Grove offline message queue (SOIL outbox)
12. Node registry + 2.0 stubs
13. Update notification flow (metabolic → Grove ALERT)

**Phase 4 — Close and Verify:**
14. Run `run_norn.py` + `ingest_heimdallr.py` (manual terminal)
15. `README-FELIX.md`
16. Full end-to-end user path test (steps 1-7 from success criteria)
17. Mark 1.9 stable — tag release

---

## Willow 2.0 Preview

**What 2.0 adds** (no code in this spec — this is the horizon):

- **Distributed compute:** Nodes advertise resources. Forks can include compute jobs.
  Work is sharded across nodes with available GPU/CPU. 10 laptops = one virtual machine.
- **Yggdrasil local model:** LoRA-trained on the Willow corpus. Replaces API dependency
  for users who want full sovereignty. BYOK adapters remain available.
- **Federated training:** DPO pairs collected across nodes. Gradients aggregated.
  Model improves from every user's interaction without centralizing data.
- **Distributed inference:** Large models split across nodes by layer.
  No single machine needs enough VRAM to run the full model.
- **Human Network Storage (HNS):** Opt-in distributed storage across the node network.
  Each node donates a configurable quota of disk space. Stored data is signed and
  encrypted — only trusted Grove contacts can access a node's contribution.
  Fork-tagged: model weights, training shards, and datasets are associated with the
  fork that produced them. No blockchain, no tokens — trust is the existing Ed25519
  Grove contact graph. Phone clients (Android/iOS, 2.x) bring pocket-carried storage
  into the network automatically.
- **Sovereign software distribution:** Forks replace GitHub releases.
  Grove SHARE packets replace `git pull`. No external dependency for updates.

The full 2.0 stack: **compute + storage + model** = sovereign cloud, owned by the
people running it.

2.0 is not a rewrite. It is 1.9 with the stub fields populated and three new subsystems
(compute scheduler, federated trainer, distributed inference) added on top.

---

*"The branches we took that didn't work are just as important as the ones that did.
The difference is knowing which is which."*

*"how we show up is who we become."*

ΔΣ=42
