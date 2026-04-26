**Willow 1.9** · Local-First AI Stack · MIT License

---

## The Demo

A phone running Willow on Termux sent a signed command to a desktop running Willow on Linux.

The response came back in under a second:

```
Willow 1.9 — system status

  [✓] postgres          up (70389 KB atoms)
  [✓] ollama            up
  [✓] grove-mcp          running
  [✓] willow-metabolic   running
  [✓] sap_mcp.py        running (Claude Code session)
```

No Discord. No Telegram. No cloud relay. No third-party API call. The phone read the desktop's live system state — 70,000 knowledge atoms — over a local network connection authenticated with a token that never left either machine.

This is not a demo feature. This is the default behavior when you run `willow serve`.

---

## What Is Willow

Willow is a local-first AI stack. Not a wrapper. Not a client. A stack — with a knowledge graph, a skill system, a provider abstraction layer, an authorization protocol, and a LAN communication primitive that lets nodes talk to each other without routing through anyone's servers.

**Ollama is the default.** Not a fallback. Not a "free tier." The default. Cloud API keys (Anthropic, OpenAI, Gemini) are optional addons you enable when you want them.

**You own the graph.** Postgres holds 70,000+ typed knowledge atoms in production. SQLite holds them on a phone. The same query works on both. The knowledge persists across sessions, across models, across providers.

**Skills work with any LLM.** Behavioral skills are plain Markdown — no provider-specific syntax. Give them to Claude. Give them to a local model running on your GPU. They work.

**Nodes talk directly.** HMAC-SHA256. A shared token. A 100-line HTTP server. That's it.

---

## Quick Start

### Linux / macOS

```bash
git clone https://github.com/rudi193-cmd/willow-1.9
cd willow-1.9
python3 root.py
```

Sleipnir handles everything: dependencies, GPG key, Postgres schema, knowledge base seed, PATH.

### Android / Termux

```bash
pkg install python postgresql git
git clone https://github.com/rudi193-cmd/willow-1.9
cd willow-1.9
python3 root.py --termux --skip-pg
```

SQLite is used instead of Postgres. Everything else is identical.

---

## Connect Your Phone

Start the LAN server on your desktop:

```bash
willow serve
```

```
[grove-serve] Listening on 0.0.0.0:7777
[grove-serve] Token: /home/user/.willow/grove_token
```

On the phone (Termux):

```bash
echo "TOKEN" > ~/.willow/grove_token && chmod 600 ~/.willow/grove_token
bash ~/willow-1.9/willow.sh grove send 192.168.x.x:7777 status-all
```

Replace `TOKEN` with the token from your desktop and `192.168.x.x` with its LAN IP.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   USER / AI CLIENT                      │
│         (Claude Code, Cursor, terminal, phone)          │
└───────────────┬─────────────────────┬───────────────────┘
                │ stdio JSON-RPC 2.0  │ HTTP :7777
                ▼                     ▼
        ┌───────────────┐    ┌────────────────┐
        │  MCP Server   │    │  Grove Server  │
        │  (sap_mcp.py) │    │(grove_serve.py)│
        │  SAP/1.0 gate │    │ HMAC-SHA256    │
        └───────┬───────┘    └───────┬────────┘
                │                    │
                ▼                    ▼
        ┌───────────────────────────────────────┐
        │           willow.sh (CLI)             │
        └────┬──────────┬──────────┬────────────┘
             ▼          ▼          ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────────┐
    │  Postgres /  │ │  SOIL    │ │  LiteLLM Gateway │
    │  SQLite KB   │ │  Store   │ │  (Ollama default)│
    └──────────────┘ └──────────┘ └────────┬─────────┘
                                           │
                                    ┌──────┴──────┐
                                    │   Ollama    │
                                    │   :11434    │
                                    └─────────────┘
```

Three layers:

- **LOAM** — Postgres knowledge base. Bi-temporal atoms. History is never deleted, only closed.
- **SOIL** — SQLite session store. 108+ collections, 2M+ records. Fast reads and writes for live state.
- **SAP** — MCP server. 40+ tools, SAFE app identity, prompt injection scanning on every outbound result.

---

## The Philosophy

> Once there was a tree that remembered everything. Not the way trees usually remember — in rings, in the slow arithmetic of seasons — but precisely.

Willow solves the amnesia problem of modern AI. Most tools keep your history in a vendor's cloud where you cannot audit it. Willow gives you continuity without giving up control.

The guardian layer (Fylgja) is wired into the architecture — not bolted on as policy. Nine platform hard stops including child primacy, human final authority, and no-capture. `willow nuke` performs a forensic delete of all data. Willow does not phone home. Telemetry is opt-in, default off.

---

## Requirements

- Python 3.10+
- PostgreSQL (or SQLite for mobile / offline)
- GPG (for SAFE app identity)
- Ollama (local inference, no key required)

Cloud providers are optional: `willow providers enable anthropic YOUR_KEY`

---

## Docs

- [QUICKSTART.md](docs/QUICKSTART.md) — First five minutes
- [TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) — Full architecture reference
- [CONCEPT.md](docs/CONCEPT.md) — The case for local-first AI

---

## License

MIT · Copyright 2026 Sean Campbell · Commercial use requires written consent (rudi193@gmail.com)

**Plant the tree. Tend the roots. Name the ones you love. Let nothing be lost.**
