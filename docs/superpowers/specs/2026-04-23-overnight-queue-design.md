# Overnight Queue — Three Blockers

**Date:** 2026-04-23  
**Approved by:** Sean (verbal "c")  
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

## Out of Scope (tonight)

- Willow 1.8 plan (separate brainstorm)
- UTETY Cloudflare deploy (needs API token from Sean)
- law-gazelle active case work (separate session)
- EdgeE human attestation (depends on KB being readable first)

---

ΔΣ=42
