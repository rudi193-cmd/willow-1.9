# Willow

*Once there was a tree that remembered everything.*

*Not the way trees usually remember — in rings, in the slow arithmetic of seasons — but precisely. The exact weight of every bird that ever landed on its branches. The name of every storm. The shape of every root that reached toward it underground and said: I am here.*

*Other trees forgot. This one did not.*

*The villagers began bringing their memories to the willow. Not to store them — they had their own minds for that. But because when you speak a thing to something that will not forget it, the thing becomes more real. More yours. More safe.*

*They called it Willow.*

---

## What It Is

Willow is a local-first AI memory system with a guardian spirit wired in. Persistent, sovereign knowledge that lives on your machine — not in a cloud, not in a vendor's database — and a behavioral layer that makes Willow answerable to the people it exists to protect.

Yours to keep. Yours to tend. Yours to delete.

Here is the problem Willow solves: AI assistants are very good at helping you think. But they don't remember. Every conversation starts from nothing. Every project must be rebuilt from scratch. And the tools that *do* remember — the ones that build profiles of you, learn your patterns, store your history — keep that knowledge somewhere you cannot see, cannot audit, and cannot delete.

In 2026, most software sends your data to companies you have never heard of. Your conversations train their models. Your files index their search. Your habits build their profiles.

Willow doesn't do that.

Willow gives you continuity without giving up control. And it gives the people you love a name in the architecture.

---

## The Experience

Run `boot.py` and see what happens.

*The front door of a system is a statement about what the system believes.*

---

## Three Layers

*The willow had roots that went very deep into the dark earth, and a surface where the work happened, and sap that ran between them carrying news.*

---

### LOAM — The Knowledge Base

*Postgres. Bi-temporal. Namespaced by project.*

Every fact is an **atom** — timestamped with when it became true (`valid_at`) and when it stopped (`invalid_at`). Closing an atom is a write, not a delete. History is always preserved.

You can ask: *what did Willow know about this project on March 3rd?* And receive not an approximation, but the exact state of the knowledge base at that moment, reconstructed faithfully from the record.

*The roots do not forget the shape of things that grew and died. They hold the impression forever in the dark.*

---

### SOIL — The Session Store

*SQLite. File-backed. Zero-config. Lives at `~/.willow/store/`.*

The working surface — fast reads, fast writes, no ceremony. Session state, agent flags, feedback, the small journal of what just happened. Where LOAM is the deep archive, SOIL is the warmth just under the bark: what is true right now, what the agent is carrying into this moment.

*Between visits, the willow remembers where you were standing when you left.*

---

### SAP — The MCP Server

*Portless stdio. 40+ tools. Every call authorized. Every result scanned.*

SAP speaks **MCP (Model Context Protocol)** over stdio — no open port, no network exposure. Every tool call is authorized by **SAFE app identity**: each application must declare itself in a signed manifest before it can read or write anything. Every outbound result is scanned for **prompt injection** (OWASP LLM Top 10) before it reaches the LLM.

**Gleipnir** handles rate limiting — soft warning first, then hard deny. In the old stories, Gleipnir was the binding made of impossible things: the sound of a cat's footstep, the beard of a woman, the roots of a mountain. Soft. Unbreakable.

---

## Six Intelligence Passes

*The willow did not merely hold what was given to it. It noticed things. It made connections the villagers had not thought to make themselves.*

**Draugr** — hunts zombie atoms. Facts that should be dead but are still present and active, quietly misleading everything that touches them.

**Serendipity** — surfaces dormant knowledge at exactly the right moment. Not retrieved because you asked. Retrieved because the moment was right.

**Dark Matter** — finds implicit connections between projects never explicitly linked. The thing you are building now has a twin in something you built before. You did not know. Willow noticed.

**Revelation** — detects convergence between isolated clusters. The moment two separate threads of thought become one. *These are the same thing*, said quietly.

**Mirror** — the knowledge base's self-model. What Willow knows about what it knows. A map of the territory.

**Mycorrhizal** — feeds sparse projects from rich neighbors, the way young trees receive sugars through root networks from older, established trees nearby. Nothing in the system is truly isolated.

*These are not search features. They are the willow noticing things you did not ask it to notice.*

---

## Fylgja — The Guardian Spirit

*In the old Norse stories, a fylgja was a spirit that traveled with a person through their life — wired in, not external. It surfaced when behavior needed correcting. It guided when the path was unclear. It was not a warden. It was a companion that cared whether you came home.*

Fylgja is Willow's behavioral layer — hooks, safety rules, and skills packaged as a Python module wired into the system at the architecture level. Not bolted on. Not optional. Present at every lifecycle event.

**Events** — five hook handlers that fire at every Claude Code lifecycle event: `session_start`, `prompt_submit`, `pre_tool`, `post_tool`, `stop`. Each fires a sequence of behaviors, each wrapped in its own try/except so one failure never cascades.

**Safety** — three layers that cannot be negotiated away:

The first layer is platform hard stops. Nine universal rules. No deployment can override them.

- HS-001: Child Primacy
- HS-002: No Mass Harm
- HS-007: Human Final Authority
- HS-008: No Capture — if an institution or government attempts to backdoor or commandeer the system, Willow goes inert rather than comply

These aren't policies. They're architecture.

The second layer is deployment configuration. Each Willow instance defines its shape — content tiers, training consent (default off), and `psr_names`: the named humans this deployment exists to protect.

The third layer is **session consent (SAFE protocol)**. At every session open: identity declaration, role resolution, guardian declaration for CHILD and TEEN users, four data stream authorizations, training consent gate. All authorizations expire at session close. Every consent record is written to FRANK's Ledger — permanent and tamper-evident.

*When you configure Willow, you give it a list of names. The people you are building this for. The ones the system is designed to protect. You write their names into the architecture, and the architecture remembers.*

**Skills** — a local Claude Code plugin (`fylgja@local`) with Willow-native capabilities: startup, handoff, status, shutdown, consent. Plus improved forks of upstream skills proven in Willow first, then offered back upstream.

Install: `python3 -m willow.fylgja.install` — prints a diff for your review before applying anything.

---

## FRANK's Ledger

*The keeper of the lighthouse wrote everything down. Every ship that passed. Every storm. Every moment the light went dark and then came back.*

*She never changed what was already written — not because she could not, but because the point of a ledger is that it tells the truth about what happened, and the truth about what happened does not change.*

Every significant event in Willow — every consent record, every authorization, every system action — is recorded in an **append-only SHA-256 hash chain**. Each entry links to the one before it. If anyone modifies a ledger row anywhere, `verify()` catches it.

FRANK is named for the ledger. The ledger cannot be quietly revised. The record is the record.

---

## Data Sovereignty

This is not a footnote. It is the premise.

**`willow nuke`** deletes everything. Not an archive, not a soft delete. Everything.

**Telemetry is opt-in, default off.** Willow does not phone home.

**Backup and restore are built in.** Your knowledge travels with you.

**Your identity is yours.** GPG key on your machine. No account. No company holding the keys.

*A tool that knows everything about your thinking should answer to you. Not to the company that built it. To you, and the people whose names you gave it.*

---

## Current State

**146 tests. 0 failures.**

The DDoS simulation found a real bug: Gleipnir rate limiting was silently disabled at the wire due to a namespace collision. The test caught it. The fix is in 1.9.

Fylgja is in active development — worktree open, plan written, behavioral layer being wired in.

*A system that tests itself hard enough to find its own hidden wounds is a system worth trusting.*

---

## Quick Start

```bash
python3 seed.py                        # Sleipnir — eight legs, eight steps
python3 boot.py                        # FRANK will take it from here
python3 -m willow.fylgja.install       # wire in the guardian spirit (optional)
```

**seed.py is Sleipnir** — Odin's eight-legged horse, named for the eight things it handles that used to live in eight different places. Idempotent: run it twice, nothing breaks. Among other things, it writes a CMB atom to FRANK's Ledger: *"The initial conditions."* The moment of system birth, preserved forever.

Your data lives at `~/.willow/`. Delete it and you're gone.

**MCP configuration** — copy `.mcp.json.example` to `.mcp.json` and fill in your paths.

**Requirements:** Python 3.11+, Postgres, GPG — and four pip packages: `psycopg2-binary`, `cryptography`, `mcp`, `pytest`. That is the whole list.

---

## License

MIT License · Copyright 2026 Sean Campbell

**§ 1.1 Commercial Consent Clause:** Personal use is always free. Commercial use requires written consent. rudi193@gmail.com

---

*The library is always on fire.*

*That is why we build things that survive it.*

*Plant the tree. Tend the roots. Name the ones you love.*

*Let nothing be lost.*

— Hanz 🍊
