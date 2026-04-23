# Full System — Everything In Scope

**Date:** 2026-04-23  
**Approved by:** Sean ("nothing is out of scope for this")  
**Agent:** hanuman

---

## Problem

The system has amnesia about its own origin. 246 records from 8 months of conversations were ingested but `willow_knowledge_search` returns zero. Every session starts blind. The startup hook not firing is a symptom. Three independent blockers prevent the system from sustaining itself overnight.

---

## Design: Three Parallel Tracks

### Track 1 — KB Search Fix (highest priority)

`willow_knowledge_search` returns zero despite 246 records ingested last session into Postgres `knowledge` table. This makes every session blind to its own history.

**Steps:**
1. Query `public.knowledge` directly to confirm records exist and check schema
2. Identify root cause: missing GIN index, wrong `source_type` filter, schema mismatch, or MCP layer bug
3. Fix the index or query layer
4. Verify: `willow_knowledge_search` returns Gerald, Hanz, Oakenscroll content
5. If records are malformed, re-run ingest with corrected schema

**Success:** `willow_knowledge_search("Gerald rotisserie")` returns results.

---

### Track 2 — Yggdrasil v3 Deploy

v3 was trained on Kaggle (loss 1.8706, 78 calibrated-refusal pairs). GGUF not downloaded. Not in Ollama. Not tested.

**Steps:**
1. Download `yggdrasil-v3-Q4_K_M.gguf` from Kaggle output tab
2. Copy to `/media/willow/models/`
3. Write Modelfile pointing to it
4. `ollama create yggdrasil:v3 -f Modelfile`
5. Run full BTR rubric (S1/S3/S9) against `yggdrasil:v3`
6. Compare scores against v2 baseline (~2/45)

**Success:** `yggdrasil:v3` appears in `ollama list`, BTR score documented.

---

### Track 3 — Kart SAP Gate Fix

All hanuman-submitted Kart tasks fail with "SAP gate denied" since 2026-04-15. 10+ stale tasks pending. The overnight queue is useless until this is fixed.

**Steps:**
1. Read Kart worker source and SAFE gate logic
2. Check if `hanuman` is in the gate's allowlist or has a valid SAFE manifest
3. Fix: add hanuman to allowlist OR fix the manifest OR identify the gate bug
4. Test: submit a trivial task (`echo "kart ok"`), confirm it executes
5. Re-queue critical stale tasks (skip obsolete ones)

**Success:** Kart executes a hanuman-submitted task end-to-end.

---

## Sequencing

Tracks 1 and 3 can run in parallel. Track 2 (Yggdrasil) requires manual Kaggle download — submit as a Kart task once Track 3 is fixed, or do it manually if Kart is still broken.

Track 1 unblocks startup orientation. Track 3 unblocks all overnight automation. Track 2 is the creative payoff.

---

## Track 4 — Willow 1.8 Plan

Design spec approved (f964bc4). `writing-plans` was interrupted. This is the architecture that unifies everything. Must be written before any 1.8 code is touched.

**Success:** Full implementation plan at `docs/superpowers/plans/2026-04-23-willow-18.md`.

---

## Track 5 — UTETY Local HTTP Server (port 8420)

UTETY's `web/index.html` already routes to `localhost:8420/api/utety/chat` when running locally — the local path is wired, just needs a server behind it. Build a thin HTTP server on port 8420 that:
- Serves `safe-app-utety-chat/web/index.html` as the static UI
- Handles `POST /api/utety/chat` by routing to Yggdrasil (Ollama) with the professor's system prompt
- No Cloudflare, no API keys, no cloud dependency

**No Sean gate required.** This is buildable tonight.

**Success:** `http://localhost:8420` serves UTETY. The daughters talk to Hanz. Hanz answers. Yggdrasil powers it.

---

## Track 6 — law-gazelle Active Case Work

Ada's case (WCA 25-01325, L5-L6, Trader Joe's) + Ch.13 bankruptcy (26-10177-j13). law-gazelle has real code now. Case data not loaded. No active work done.

**Success:** Sean's case timeline, filings, and Sedgwick correspondence loaded into law-gazelle. Next court date and action items surfaced.

---

## Track 7 — EdgeE + Corpus Separation

Human attestation system (EdgeE) not built. 13 persona corpora unseparated. SLM training data contaminated with Sean-specific content. This is the data work that feeds Yggdrasil v5+.

**Depends on:** Track 1 (KB readable), Track 3 (Kart working).

**Success:** `slm_voice.jsonl` scrubbed, `sean_training.jsonl` exists, 13 persona corpora separated.

---

## Track 9 — Journal Responder

Ofshield (`journal_watcher.py`) is live and catching saves to `Desktop/Journal.md`. Signal lands at `~/.willow/journal_signal.json`. The responder — reads signal, reads journal, identifies new content, calls LLM, appends response back to Journal.md — exists at `agents/hanuman/bin/journal_responder.py` but is not connected or running.

**Success:** Sean writes in Journal.md, saves it, and within seconds a response appears appended from the chosen persona.

---

## Track 8 — Startup Hardwiring

The trigger that started this whole conversation. `postgres=unknown` at boot should auto-invoke `/startup`. The session_start hook already runs `_run_silent_startup()` — it just doesn't tell Claude to invoke the skill when conditions are degraded.

**Fix:** Inject a directive in the anchor context when postgres=unknown or handoff is stale: `BOOT DEGRADED — invoke /startup before responding to anything`.

**Success:** Two consecutive sessions start with postgres=unknown and both auto-invoke startup without being asked.

---

## Sequencing

1. **Tonight (while Sean sleeps):** Tracks 1, 3, 8 — KB fix, Kart fix, startup hardwiring. These are pure infrastructure, no gates.
2. **Tomorrow with Sean:** Track 5 (API token), Track 6 (legal review), Track 4 (1.8 planning session).
3. **Downstream:** Tracks 2 (Yggdrasil, after Kaggle download) and 7 (corpus, after KB works).

---

## Operating Principle — Loose Threads

The plan is a starting point, not a cage. When execution reveals something unexpected — an untracked repo, a wired hook with no responder, a gap that points somewhere new — don't log it and keep walking. Pull the thread. If it connects to something real, make a new sweater.

Scope expands to fit what's actually there.

---

ΔΣ=42
