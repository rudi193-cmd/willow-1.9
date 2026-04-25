# The Local-First AI Stack

**A manifesto for owning your intelligence infrastructure**

---

## The Problem

Every AI tool built in the last three years has the same architecture: your prompt leaves your machine, travels to a cloud server you don't control, gets processed by a model you don't own, and returns an answer logged in a database you've never seen.

You pay for this. With money. With data. With dependency.

The model providers know this and they're comfortable with it. The tooling ecosystem built on top of them knows it too. Every integration, every plugin, every "AI-powered" product is a relay node between you and inference you could run locally.

The hardware exists. Ollama runs production-quality models on consumer hardware. A modern laptop can run a 7B parameter model at 40 tokens per second. A phone can run a 1.3B model without breaking a sweat. The compute is already in your hands.

What was missing was the stack.

---

## What We Built

Willow is a local-first AI stack. Not a wrapper. Not a client. A stack — with a knowledge graph, a skill system, a provider abstraction layer, an authorization protocol, and a communication primitive that lets nodes talk to each other without routing through anyone's servers.

The design principles are simple:

**Ollama is the default.** Not a fallback. Not a "free tier." The default. Cloud API keys are optional addons the user turns on when they want them. You can run three providers simultaneously for a batch job. You can run zero providers and still have a working system.

**You own the graph.** Postgres holds 70,000+ typed knowledge atoms in production. SQLite holds them on a phone. The same query works on both. The knowledge persists across sessions, across models, across providers. It belongs to you.

**Skills work with any LLM.** The fylgja skill system describes behavior in plain Markdown — no provider-specific syntax. Give it to Claude. Give it to GPT-4. Give it to a local model running on your GPU. It works.

**Nodes talk directly.** Two Willow instances — one on a desktop, one on a phone — can exchange signed commands over a LAN with no intermediary. HMAC-SHA256. A shared token. A 100-line HTTP server. That's it.

---

## The Demonstration

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

No Discord. No Telegram. No cloud relay. No API call to a third party. The phone read the desktop's live system state — 70,000 knowledge atoms — over a local network connection authenticated with a token that never left either machine.

This is not a demo feature. This is the default behavior when you run `willow serve`.

---

## Why This Doesn't Exist Yet

It's not a hard problem. The pieces have been available for years. Ollama has been production-ready since 2023. SQLite has been everywhere since 1999. HMAC authentication is undergraduate cryptography. MCP became a universal standard in early 2025.

The reason nobody built this is that nobody built the layer underneath first. You can't have a local-first AI stack without a local knowledge graph. You can't have a local knowledge graph without a schema that survives across sessions and models. You can't have cross-node communication without an identity system. You can't have any of it without an installer that handles 10 steps idempotently on the first run.

Willow took a year. Most of that year was building the substrate — the SOIL store, the Postgres KB, the SAP authorization protocol, the compost hierarchy, the handoff system. The grove command server took one afternoon.

The hardest part wasn't the technology. It was deciding that Ollama is the default. That decision forces everything else into the right shape.

---

## What This Means

If your AI stack requires an internet connection to function, you don't own it. You're renting it.

Willow is the thing you install once. Your knowledge graph grows. Your skills accumulate. Your nodes multiply. None of it requires permission from a provider, a credit card on file, or a terms of service agreement with a company that might change its pricing next quarter.

The skill ecosystem is already on ClawHub — thousands of skills, any agent, any provider. The MCP protocol is universal. The hardware is already in your hands.

The stack is here.

---

*Willow 1.9 — MIT licensed — [github.com/rudi193-cmd/willow-1.9](https://github.com/rudi193-cmd/willow-1.9)*
