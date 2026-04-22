**Willow 1.9**. Following the "Inverted Funnel" approach suggested in the studio critique, this version prioritizes immediate technical utility while preserving the mythic "soul" of the project as a secondary, depth-giving layer.
# Willow 1.9: Local-First AI Memory
### Portless MCP Server • Yours to Keep • Yours to Delete
**Willow** is a hardened, local-first system designed to ensure that an AI which knows everything about your thinking answers only to you and the people you love. It combines bi-temporal knowledge storage with a "guardian" behavioral layer wired directly into the architecture.
## ⚡ Quick Start: The "First Bite"
Get Willow running on your local machine in under 60 seconds.
```bash
# 1. Clone and enter
git clone https://github.com/rudi193-cmd/willow-1.9.git && cd willow-1.9

# 2. Setup environment (Requires Python 3.11+, Postgres, GPG)
pip install -r requirements.txt
cp .mcp.json.example .mcp.json

# 3. Plant the tree (Initialize database and FRANK's Ledger)
python3 seed.py

# 4. Boot the system
python3 boot.py

```
## 🛠 Technical Requirements & Stack
Before installing, ensure your local environment meets these specifications:
 * **Runtime**: Python 3.11+
 * **Primary Store**: Postgres (Production: willow_19 | Test: willow_19_test)
 * **Security**: GPG (for SAFE app identity and manifest signing)
 * **Dependencies**: psycopg2-binary, cryptography, mcp, pytest
## 🌲 The Architecture: Three Layers
Willow is structured to provide continuity without sacrificing sovereignty.
### 1. LOAM — Postgres Knowledge Base (The Deep Archive)
 * **Technical**: A bi-temporal Postgres database namespaced by project.
 * **Function**: Every fact is an "atom" timestamped with valid_at and invalid_at. Closing an atom is a write, not a delete—history is reconstructed faithfully, never approximated.
 * **Metaphor**: The roots do not forget the shape of things that grew and died; they hold the impression forever in the dark.
### 2. SOIL — SQLite Session Store (The Working Surface)
 * **Technical**: File-backed SQLite database located at ~/.willow/store/.
 * **Function**: Fast reads/writes for session state, agent flags, and immediate journals.
 * **Metaphor**: If LOAM is the deep archive, SOIL is the warmth under the bark: what is true *right now*.
### 3. SAP — The MCP Server (The Coordination Layer)
 * **Technical**: Portless stdio implementation of the Model Context Protocol (MCP).
 * **Function**: 40+ tools authorized via **SAFE app identity**. Outbound results are scanned for prompt injection (OWASP LLM Top 10), and **Gleipnir** handles rate limiting.
 * **Metaphor**: In the old stories, Gleipnir was the unbreakable binding made of impossible things.
## 🛡 Fylgja: The Guardian Spirit
Fylgja is Willow’s behavioral layer—hooks and safety rules wired in at the architecture level, not "bolted on" as a policy.
 * **Events**: Five hook handlers firing at every Claude Code lifecycle event (session_start, prompt_submit, pre_tool, post_tool, stop).
 * **Platform Hard Stops**: Nine universal, non-negotiable rules (e.g., **HS-001: Child Primacy**, **HS-007: Human Final Authority**, and **HS-008: No Capture**).
 * **Sovereignty**: willow nuke performs a forensic delete of all data. Willow does not "phone home" and telemetry is opt-in (default off).
## 📖 The Philosophy: The Tree That Remembered
> Once there was a tree that remembered everything. Not the way trees usually remember — in rings, in the slow arithmetic of seasons — but precisely.
> The villagers brought their memories to the willow. Not to store them, but because when you speak a thing to something that will not forget it, the thing becomes more real.
> 
Willow solves the "amnesia problem" of modern AI. Most tools keep your history in a vendor's cloud where you cannot audit it. Willow gives you **continuity without giving up control**, naming the people you love in the very architecture of the code.
## ⚖️ License & Integrity
 * **Integrity**: Every significant event is recorded in **FRANK’s Ledger**, an append-only SHA-256 hash chain.
 * **License**: MIT License · Copyright 2026 Sean Campbell.
 * **Commercial Use**: Requires written consent (rudi193@gmail.com).
**The library is always on fire. That is why we build things that survive it.**
**Plant the tree. Tend the roots. Name the ones you love. Let nothing be lost.**
