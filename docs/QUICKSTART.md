# Willow Quick Start

Local-first AI stack. Your hardware. Your data. No API key required to start.

---

## What You Get

| Component | What it does |
|---|---|
| **Ollama inference** | LLM runs on your machine — no key, no cloud |
| **Knowledge graph** | Postgres or SQLite, persists across every session |
| **30+ MCP tools** | File ops, web fetch, task queue, KB search — all callable by the agent |
| **Skill system** | Composable agent behaviors, works with any LLM or API key |
| **Grove dashboard** | Terminal UI showing system health at a glance |
| **LAN remote control** | Phone → desktop over your local network, no cloud relay |

Cloud providers (Anthropic, OpenAI, Gemini) are optional. Enable them when you want them.

---

## Install

### Linux / macOS

```bash
git clone https://github.com/rudi193-cmd/willow-1.9
cd willow-1.9
python3 root.py
```

Sleipnir handles everything from here: dependencies, GPG key, vault setup, Postgres schema, knowledge base seed, PATH.

### Android / Termux

```bash
pkg install python postgresql git
git clone https://github.com/rudi193-cmd/willow-1.9
cd willow-1.9
python3 root.py --termux --skip-pg
```

SQLite is used instead of Postgres. Everything else is identical.

---

## First Five Minutes

```bash
willow status-all          # check that all components came up
willow health              # run boot diagnostics
willow providers list      # see what's active (Ollama is on by default)
```

Add a cloud key when you want one:

```bash
willow providers enable anthropic YOUR_API_KEY
willow providers enable openai YOUR_API_KEY
willow providers enable gemini YOUR_API_KEY
```

Start the LAN server:

```bash
willow serve
```

Expected output:

```
[grove] Listening on 0.0.0.0:7777
[grove] Token: abc123def456
```

---

## Connect Your Phone

On the desktop, generate a pairing token:

```bash
willow serve          # if not already running
willow grove pair     # prints the token
```

On the phone (Termux):

```bash
echo "TOKEN" > ~/.willow/grove_token && chmod 600 ~/.willow/grove_token
bash ~/willow-1.9/willow.sh grove send 192.168.x.x:7777 status-all
```

Replace `TOKEN` with the token from `grove pair` and `192.168.x.x` with your desktop's LAN IP.

---

## Skills

Skills are composable agent behaviors — think of them as named, reusable prompts with tool access.

Browse and install from ClawHub:

```bash
npx clawhub install willow-system-health
```

Or load a built-in skill directly:

```bash
willow skill load system-health
```

Built-in skills live in `willow/fylgja/skills/`. Drop a `.yaml` file there to add your own.

---

## Knowledge Base

The KB persists everything the agent learns across sessions.

```bash
willow kb search "postgres setup"      # search stored knowledge
willow kb ingest path/to/notes.md      # add a document
```

The agent uses MCP tools (`willow_knowledge_search`, `willow_knowledge_ingest`) to read and write the KB automatically during tasks.

---

## What's Next

- Browse skills: [https://clawhub.ai](https://clawhub.ai)
- Technical spec: `docs/TECHNICAL_SPEC.md`
- Community: Discord — **LLM Physics**

---

## What This Actually Means

Willow is a stack, not a product. You clone it, you run it, and from that point forward the inference, the memory, and the tooling all live on hardware you control. The cloud providers are there when you need them — for a model you don't have weights for, or a task that needs more headroom — but they're addons, not the foundation. The foundation is local. That's the point.
