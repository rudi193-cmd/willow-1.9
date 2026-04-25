# Willow Technical Specification

**Version:** 1.9.0  
**Date:** 2026-04-24  
**License:** MIT  
**b17:** 5AAN0 ΔΣ=42

---

## Overview

Willow is a local-first AI stack. Ollama is the default inference engine. Cloud API keys are optional addons. Every component is owned by the user — no telemetry by default, no mandatory accounts, no third-party dependencies for core function.

**Supported platforms:** Linux, macOS, Android (Termux)  
**Language:** Python 3.10+  
**Database:** PostgreSQL (primary), SQLite (fallback / mobile)

---

## ASCII Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER / AI CLIENT                         │
│           (Claude Code, Cursor, terminal, phone)                │
└───────────────┬─────────────────────────┬───────────────────────┘
                │ stdio JSON-RPC 2.0       │ HTTP :7777
                ▼                         ▼
        ┌───────────────┐        ┌────────────────┐
        │  MCP Server   │        │  Grove Server  │
        │  (sap_mcp.py) │        │(grove_serve.py)│
        │  SAP/1.0 gate │        │ HMAC-SHA256    │
        └───────┬───────┘        └───────┬────────┘
                │                        │
                ▼                        ▼
        ┌───────────────────────────────────────────┐
        │               willow.sh (CLI)             │
        │  start │ status │ health │ providers │ …  │
        └────┬──────────┬──────────────┬────────────┘
             │          │              │
             ▼          ▼              ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────────┐
    │  PgBridge /  │ │  SOIL    │ │  LiteLLM Gateway │
    │ SqliteBridge │ │  Store   │ │  localhost:4000  │
    │  willow_19   │ │ ~/.willow│ │  (Ollama default)│
    │  knowledge   │ │ /store/  │ └────────┬─────────┘
    │  tasks edges │ │ 108+ col │          │
    └──────────────┘ └──────────┘   ┌─────┴──────┐
                                    │   Ollama   │
                                    │ :11434     │
                                    └────────────┘
```

---

## Components

### SOIL Local Store

**b17:** SOIL1  
**Source:** `core/willow_store.py`  
**Schema class:** `WillowStore`

SQLite-backed key/value store with full-text search. Each collection is a separate SQLite database file.

**Storage root:** `~/.willow/store/` (override: `WILLOW_STORE_ROOT`)  
**Collection path:** `{root}/{namespace}/{name}.db`  
**Scale in production:** 108+ collections, 2M+ records

Records must carry an `id`, `_id`, or `b17` field. Collections are created on first write (no migration needed).

**MCP tools:**

| Tool | Description |
|---|---|
| `store_put` | Write or replace a record in a collection |
| `store_get` | Fetch a record by ID |
| `store_list` | List all records in a collection |
| `store_search` | Full-text search within a collection |
| `store_search_all` | Full-text search across all collections |
| `store_update` | Partial update of a record |
| `store_delete` | Remove a record |
| `store_add_edge` | Add a named edge between two records |
| `store_edges_for` | Fetch all edges for a record |
| `store_audit` | Return audit trail for a collection |
| `store_stats` | Collection statistics |

---

### Postgres Knowledge Base

**Database:** `willow_19`  
**Source:** `core/pg_bridge.py`  
**Scale in production:** 70k+ atoms

Typed atoms with directed edges. Supports semantic search (pgvector) and full-text search (PostgreSQL tsvector). Used for long-lived knowledge, tasks, sessions, agent state, and feedback.

**Tables:**

| Table | Purpose |
|---|---|
| `knowledge` | KB atoms — title, summary, content, domain, source_type, weight |
| `tasks` | Task queue entries with status and priority |
| `frank_ledger` | Financial / accounting ledger |
| `jeles_sessions` | Agent session records |
| `jeles_atoms` | Per-session turn atoms |
| `forks` | Branch-and-merge work isolation records |
| `agents` | Registered agent identities |
| `opus_atoms` | Archived / long-term memory atoms |
| `feedback` | Structured feedback from agents and users |
| `journal` | Append-only event log |

**Atom fields (knowledge table):** `id`, `project`, `valid_at`, `invalid_at`, `created_at`, `title`, `summary`, `content`, `source_type`, `category`, `visit_count`, `weight`, `last_visited`, `fork_id`, `domain`

**MCP tools:** `willow_knowledge_search`, `willow_knowledge_ingest`, `willow_knowledge_at`, `willow_query`

---

### SQLite Bridge

**b17:** SQBR1  
**Source:** `core/sqlite_bridge.py`  
**DB path:** `~/.willow/willow.db` (override: `WILLOW_SQLITE_PATH`)

Drop-in replacement for PgBridge. Selected automatically when Postgres is unavailable, or explicitly via `WILLOW_BACKEND=sqlite`. Full API parity.

**Differences from PgBridge:**

- FTS5 virtual table for knowledge search (no pgvector — no vector search on mobile)
- Timestamps stored as ISO TEXT
- JSONB stored as `TEXT` (serialized with `json.dumps` / `json.loads`)
- Thread-safe via `check_same_thread=False` with per-operation commits

**Use cases:** Android (Termux), CI environments, offline installs, single-user laptops without Postgres.

**Schema excerpt:**

```sql
CREATE TABLE IF NOT EXISTS knowledge (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL DEFAULT 'global',
    valid_at    TEXT NOT NULL DEFAULT (datetime('now')),
    invalid_at  TEXT,
    title       TEXT,
    summary     TEXT,
    content     TEXT,
    source_type TEXT,
    category    TEXT,
    visit_count INTEGER NOT NULL DEFAULT 0,
    weight      REAL NOT NULL DEFAULT 1.0
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    id UNINDEXED,
    title,
    summary,
    content='knowledge',
    content_rowid='rowid'
);
```

---

### Bridge Factory

**Source:** `core/bridge_factory.py`

Selection logic, controlled by `WILLOW_BACKEND` environment variable:

```
WILLOW_BACKEND=sqlite   → SqliteBridge (~/.willow/willow.db)
WILLOW_BACKEND=postgres → PgBridge (willow_19)
unset / auto            → PgBridge, falls back to SqliteBridge if Postgres unreachable
```

Usage in all Willow internals:

```python
from core.bridge_factory import get_bridge
bridge = get_bridge()
```

---

### MCP Server

**b17:** 67ECL  
**Source:** `sap/sap_mcp.py`  
**Transport:** stdio JSON-RPC 2.0 (portless)

Exposes 30+ tools to any MCP-capable client (Claude Code, Cursor, etc.). No HTTP, no port binding. Every tool call passes through the SAP/1.0 authorization gate.

**Protocol:** MCP SDK over stdio. Tool arguments are JSON objects.  
**Auth:** SAP/1.0 `app_id` required in every tool call argument payload.  
**Startup:** Server boots without a SAFE check — it is infrastructure, not an app.

**Tool categories:**

- Knowledge: search, ingest, query, journal
- Tasks: submit, list, status
- Store: put, get, list, search, edges
- Skills: list, load, put
- Agents: create, list
- System: status, health, reload, restart
- Forks: create, list, merge, join, delete
- Handoff: latest, search, rebuild
- Dispatch: route, result

**Example tool call (JSON-RPC):**

```json
{
  "method": "tools/call",
  "params": {
    "name": "willow_knowledge_search",
    "arguments": {
      "app_id": "hanuman",
      "query": "SOIL store collections",
      "limit": 5
    }
  }
}
```

---

### SAP/1.0 Authorization

**Full name:** SAFE Authorization Protocol  
**Source:** `sap/core/gate.py`

Filesystem-based identity gate. Every MCP tool call carries an `app_id`. The gate validates the app against signed SAFE manifests stored under `~/SAFE/Applications/`.

**Mechanism:**

1. App registers a SAFE manifest (JSON) at `~/SAFE/Applications/<app_id>.json`
2. Manifest is GPG-signed; fingerprint pinned via `WILLOW_PGP_FINGERPRINT`
3. Gate checks: manifest exists → signature valid → app is authorized for the requested tool
4. Unauthorized calls are logged to `sap/log/gaps.jsonl` and rejected

**Functions:**

```python
authorized(app_id: str) -> bool
permitted(app_id: str, tool: str) -> bool
list_authorized() -> list[str]
```

**Degraded mode:** If the SAP gate fails to load (missing GPG, missing manifests), the server continues but logs a gap entry. Gate-down state is visible in audit output.

---

### LiteLLM Gateway

**Source:** `core/providers.py`  
**Port:** `localhost:4000`  
**Commands:** `willow litellm-start`, `willow litellm-stop`

Unified provider abstraction layer. `build_litellm_config()` generates a LiteLLM-compatible YAML config from the active provider registry.

**Default configuration:**

```
ollama    → always on, localhost:11434, models: [yggdrasil:v9, qwen2.5:3b]
anthropic → off by default (user-toggled)
openai    → off by default (user-toggled)
gemini    → off by default (user-toggled)
```

**Provider registry** persists in SOIL at collection `willow/providers`.

**Enabling a cloud provider:**

```bash
willow providers enable anthropic --key sk-ant-...
willow providers list
```

Example `providers list` output:

```
Provider   Enabled   Local   Models
---------  --------  ------  --------------------------
ollama     yes       yes     yggdrasil:v9, qwen2.5:3b
anthropic  no        no      claude-sonnet-4-6, ...
openai     no        no      gpt-4o, gpt-4o-mini
gemini     no        no      gemini-2.0-flash, ...
```

API keys are masked in all output: first 8 characters + `***`.

Ollama is not disableable. It is always the default local provider.

---

### Fylgja Skills

**Source:** `willow/fylgja/skills/`  
**Registry:** SOIL collection `willow/skills`  
**Source:** `willow/skills.py`

LLM-agnostic behavioral skills. Each skill is a named Python or bash script with a trigger phrase and a prose content body. Skills are loaded contextually by matching trigger words against the current context string.

**Published on:** ClawHub

**Built-in skills:**

| Skill | Purpose |
|---|---|
| `system-health` | Check disk, memory, process health |
| `memory-health` | Audit KB atom counts and staleness |
| `context-sentinel` | Monitor context window usage |
| `external-guard` | Detect and block external data leakage |
| `startup` | Session initialization checklist |
| `handoff` | Generate structured handoff summary |
| `status` | System status report |
| `debugging` | Systematic debug workflow |
| `learn` | Ingest new knowledge into KB |
| `iterative-retrieval` | Multi-step KB retrieval loop |
| `tdd` | Test-driven development workflow |
| `brainstorming` | Divergent ideation framework |
| `consent` | User consent gate for destructive actions |
| `shutdown` | Session shutdown and compost |

**Skill schema:**

```python
{
    "id": "system-health",
    "name": "system-health",
    "domain": "fylgja",
    "content": "<prose instructions for the LLM>",
    "trigger": "health disk memory process",
    "auto_load": True,
    "model_agnostic": True,
}
```

**MCP tools:** `willow_skill_list`, `willow_skill_load`, `willow_skill_put`

---

### Grove Command Server

**b17:** GRSV1  
**Source:** `core/grove_serve.py`  
**Port:** `7777` (override: `WILLOW_GROVE_PORT`)  
**Command:** `willow serve`

LAN HTTP server. Accepts signed command requests from trusted Willow nodes (phones, other machines). Executes allowlisted `willow.sh` subcommands only.

**Token:** `~/.willow/grove_token` — 64-char hex string, generated on first run, permissions `0o600`.

**Allowed commands (server-side allowlist):**

```
status, status-all, health, health daily, health weekly,
providers list, sentinel, ledger, version, whoami
```

Nothing outside this set executes, regardless of what the client sends.

**Startup output example:**

```
[grove-serve] Listening on 0.0.0.0:7777
[grove-serve] Token: /home/user/.willow/grove_token
[grove-serve] Allowed commands: ['health', 'ledger', 'providers list', ...]
```

---

### Grove Client

**Source:** `core/grove_client.py`  
**Command:** `willow grove send <host:port> <command>`

Signs commands with HMAC-SHA256 using the shared grove token, sends to a remote grove server.

**Pairing:** `willow grove pair` — copies the grove token to a remote node (manual step; SSH or physical transfer).

---

## Wire Protocols

### Grove Protocol

**Endpoint:** `POST /command`

Request:

```http
POST /command HTTP/1.1
Content-Type: application/json
X-Grove-Sig: <hmac-sha256-hex-of-body>

{"cmd": "status"}
```

Response:

```json
{
  "output": "Willow 1.9.0 — all systems nominal\n...",
  "exit_code": 0,
  "cmd": "status"
}
```

**Health check (no auth):**

```http
GET /health HTTP/1.1
```

```json
{"status": "ok", "service": "grove-serve"}
```

**HMAC computation:**

```python
sig = hmac.new(token.encode(), body_bytes, hashlib.sha256).hexdigest()
```

**Error responses:**

| Code | Condition |
|---|---|
| 401 | Invalid or missing signature |
| 400 | Missing or malformed JSON body |
| 403 | Command not in allowlist |
| 404 | Path not found |

**Timeout:** 30 seconds per command execution.

---

### MCP Protocol

stdio JSON-RPC 2.0. No port. No HTTP.

Client connects by spawning the MCP server process:

```bash
python3 -m sap.sap_mcp
```

Every tool call requires `app_id` in the arguments:

```json
{
  "app_id": "hanuman",
  "<other args>": "..."
}
```

Calls without a valid `app_id` are rejected with an authorization error.

---

## Data Flow: Phone → Grove → Willow → Phone

```
Phone (grove client)
  │
  │  1. User runs: willow grove send 192.168.1.10:7777 status
  │
  ▼
grove_client.py
  │  2. Reads ~/.willow/grove_token
  │  3. Serializes body: {"cmd": "status"}
  │  4. Computes HMAC-SHA256 of body using token
  │  5. POST /command with X-Grove-Sig header
  │
  ▼ (LAN HTTP)
grove_serve.py (on desktop/server)
  │  6. Reads Content-Length, reads body
  │  7. Validates HMAC-SHA256 signature
  │  8. Parses {"cmd": "status"}
  │  9. Checks "status" against ALLOWED_COMMANDS
  │  10. Runs: bash willow.sh status
  │
  ▼
willow.sh
  │  11. Executes status subcommand
  │  12. Collects stdout + stderr
  │
  ▼
grove_serve.py
  │  13. Returns {"output": "...", "exit_code": 0, "cmd": "status"}
  │
  ▼ (HTTP response)
grove_client.py
  │  14. Prints output to terminal
  │
  ▼
Phone screen
```

---

## Security Model

### Grove Token

- Generated with `secrets.token_hex(32)` (256 bits of entropy)
- Stored at `~/.willow/grove_token`, permissions `0o600`
- Shared manually with trusted nodes — never transmitted over the network during pairing
- HMAC computed with `hmac.compare_digest` (constant-time comparison, prevents timing attacks)

### SAP/1.0

- GPG-signed SAFE manifests at `~/SAFE/Applications/<app_id>.json`
- GPG fingerprint pinned via `WILLOW_PGP_FINGERPRINT` environment variable
- Per-app, per-tool authorization — an app authorized for `store_get` is not automatically authorized for `store_delete`
- All gate failures logged to `sap/log/gaps.jsonl` with UTC timestamp

### Vault

- **Source:** `core/vault.py`
- Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256)
- Vault DB: `~/.willow/vault.db`, permissions `0o600`
- Master key: `~/.willow/vault.key`, permissions `0o600`
- Key generated with `Fernet.generate_key()` on first `vault.init()`

### API Key Masking

All provider API keys are masked in any output or log:

```python
def _mask_key(key: str) -> str:
    return key[:8] + "***"
# sk-ant-ap → sk-ant-a***
```

---

## KB Seed

**Source:** `core/seed_kb.py`  
**Command:** called during `root.py` install  
**Idempotent:** yes — skips atoms that already exist

On install, seeds the knowledge base with neutral starter atoms:

- **One atom per Fylgja skill** — name and one-line description
- **One atom per `willow.sh` subcommand** — name and purpose
- **8 architecture atoms** — one per major system component

All seeded atoms: `domain="willow"`, `source_type="seed"`.

Architecture atoms seeded:

| Title | Summary |
|---|---|
| SOIL local store | SQLite-backed key/value + FTS, collections at ~/.willow/store/ |
| Postgres knowledge base | Typed atoms with edges, semantic + FTS search, willow_19 DB |
| Kart task queue | Sandboxed task executor for shell commands and Python scripts |
| SAP authorization | SAFE Authorization Protocol, filesystem-based identity gate |
| Fylgja skills | LLM-agnostic behavioral skills, script-backed, any API key |
| Ollama inference | Local-first LLM inference, default provider, no API key required |
| LiteLLM gateway | Unified provider abstraction at localhost:4000, cloud keys optional |
| Grove dashboard | Terminal UI for system status, provider management, skill invocation |

---

## Provider Abstraction

```
WILLOW_BACKEND=sqlite   → SqliteBridge (mobile/offline)
WILLOW_BACKEND=postgres → PgBridge
unset                   → auto (Postgres → SQLite fallback)

Providers (registry at willow/providers SOIL collection):
  ollama    always on, localhost:11434
  anthropic off by default, user-toggled
  openai    off by default, user-toggled
  gemini    off by default, user-toggled
```

LiteLLM routes all inference calls. Willow code never calls provider APIs directly — it calls `localhost:4000` and LiteLLM dispatches based on the active config.

If Ollama is enabled but unreachable at runtime, `build_litellm_config()` silently skips it rather than erroring. The system degrades gracefully.

---

## Willow CLI (`willow.sh`)

Unified launcher. All subcommands delegate to Python modules in `willow/` and `core/`.

**Full command surface:**

| Command | Description |
|---|---|
| `start` | Start MCP server and LiteLLM gateway |
| `status` | Single-node status summary |
| `status-all` | Multi-node status (grove-aware) |
| `health` | Run Fylgja system-health skill |
| `memory-health` | Run Fylgja memory-health skill |
| `sentinel` | Run context-sentinel check |
| `guard` | Run external-guard check |
| `serve` | Start Grove command server on :7777 |
| `grove pair` | Exchange grove token with a remote node |
| `grove send <host:port> <cmd>` | Send signed command to remote grove |
| `providers list` | List all providers and enabled state |
| `providers enable <name>` | Enable a provider (optionally set API key) |
| `providers disable <name>` | Disable a provider |
| `litellm-start` | Start LiteLLM gateway process |
| `litellm-stop` | Stop LiteLLM gateway process |
| `backup` | Snapshot KB and SOIL store |
| `restore` | Restore from backup snapshot |
| `ledger` | Show frank_ledger summary |
| `valhalla` | Archive and retire stale atoms |
| `verify` | Run integrity checks on KB and store |
| `nuke` | Wipe all Willow data (requires confirmation) |
| `metabolic` | Check metabolic socket health |
| `update` | Pull latest version and re-seed KB |

---

## Dashboard

Two implementations:

| File | Library | Status |
|---|---|---|
| `dashboard.py` | curses | Mature, stable |
| `dashboard2.py` | Textual | New, richer UI |

**Five tabs:** Overview, Providers, Skills, Health, Logs

---

## Sleipnir Installer (`root.py`)

**b17:** SLP19  
**Version:** 1.9.0  
**Command:** `python3 root.py`

Idempotent install. Safe to run multiple times. Each step is a named function that checks before acting.

**Install steps:**

| Step | Function | Action |
|---|---|---|
| 0 | `step_telemetry_init` | Write `~/.willow/telemetry.json` (opt-in disabled) |
| 1 | `step_1_dirs` | Create `~/.willow/`, `~/SAFE/Applications/` |
| 2 | `step_2_deps` | Install Python packages from `requirements.txt` |
| 3 | `step_3_gpg` | Generate 4096-bit RSA GPG key if none present |
| 4 | `step_4_vault` | Initialize Fernet vault |
| 5 | `step_5_postgres` | Create `willow_19` database and schema |
| 6 | `step_6_metabolic` | Install metabolic socket unit |
| 7 | `step_7_cmb` | Write CMB (cosmic microwave background) seed atom |
| 8 | `step_8_seed` | Run `seed_kb.py` |
| 9 | `step_9_version` | Pin version to `~/.willow/version` |

**Flags:**

```
--skip-pg       Skip Postgres setup (already configured)
--skip-socket   Skip systemd socket install
--skip-gpg      Skip GPG key generation
--termux        Android mode (see below)
```

---

## Termux (Android) Mode

Activated with `python3 root.py --termux` or auto-detected when `$PREFIX` is set (Termux environment marker).

**Differences from standard install:**

- Skips: systemd, GPG key generation, WSL launcher
- Writes `willow-termux.sh` as systemd substitute
- Forces `WILLOW_BACKEND=sqlite`
- Seeds KB into SQLite bridge instead of Postgres
- Uses `$PREFIX/var/db/` for database path if available

---

## Agent System

**Source:** `willow/constants.py`

Agents are tiered by capability and trust level:

| Tier | Members |
|---|---|
| ENGINEER | hanuman, heimdallr, kart, shiva, ganesha, opus |
| OPERATOR | willow, ada, steve |
| WORKER | hanz, jeles, pigeon, riggs |
| WITNESS | gerald |

**TTL thresholds for agent state:**

| State | Threshold | Action |
|---|---|---|
| RUNNING | last message < 2 min | SendMessage |
| IDLE | last message < 15 min | RemoteTrigger |
| STALE | last message < 1 hour | CronCreate |

**Dispatch channels:** `dispatch`, `dispatch-escalations`, `dispatch-violations`, `architecture`, `general`, `handoffs`

**Dispatch depth limit:** 3 levels. Depth > 3 → hard stop → post to `#dispatch-violations`.

---

## Directory Layout

```
~/.willow/
├── store/                  # SOIL collections (one .db per collection)
│   └── willow/
│       ├── providers.db
│       ├── skills.db
│       └── ...
├── willow.db               # SQLite bridge (when Postgres unavailable)
├── vault.db                # Fernet-encrypted secret store
├── vault.key               # Vault master key (0o600)
├── grove_token             # HMAC shared secret (0o600)
├── telemetry.json          # Telemetry opt-in (disabled by default)
├── version                 # Pinned version string
├── logs/                   # Runtime logs
└── secrets/                # Additional secrets directory

~/SAFE/
└── Applications/
    └── <app_id>.json       # SAP SAFE manifests (GPG-signed)

/repo/
├── root.py                 # Sleipnir installer
├── willow.sh               # CLI launcher
├── core/
│   ├── bridge_factory.py
│   ├── pg_bridge.py
│   ├── sqlite_bridge.py
│   ├── willow_store.py
│   ├── vault.py
│   ├── providers.py
│   ├── seed_kb.py
│   ├── grove_serve.py
│   └── grove_client.py
├── sap/
│   ├── sap_mcp.py
│   ├── core/gate.py
│   └── log/gaps.jsonl
├── willow/
│   ├── constants.py
│   ├── skills.py
│   ├── forks.py
│   └── fylgja/skills/
├── dashboard.py
└── dashboard2.py
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WILLOW_BACKEND` | `auto` | `sqlite`, `postgres`, or `auto` |
| `WILLOW_STORE_ROOT` | `~/.willow/store` | SOIL store root directory |
| `WILLOW_SQLITE_PATH` | `~/.willow/willow.db` | SQLite bridge DB path |
| `WILLOW_GROVE_PORT` | `7777` | Grove server listen port |
| `WILLOW_ROOT` | repo root | Willow installation directory |
| `WILLOW_PGP_FINGERPRINT` | — | GPG fingerprint for SAP manifest verification |

---

## Telemetry

Disabled by default. Opt-in controlled by `~/.willow/telemetry.json`:

```json
{
  "enabled": false,
  "what": "Nothing is collected when disabled.",
  "to_enable": "Set enabled: true in this file."
}
```

The file is written on first install and never overwritten by subsequent installs. The user's choice persists across updates.
