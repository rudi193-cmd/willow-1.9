# Plan 5 — Layer 0: The Nest (File Lifecycle Pipeline)
## Every Personal File Gets a b17, a State, and a Path

**Date:** 2026-04-22
**Status:** SPEC — awaiting Sean's authorization before implementation
**b17:** B2DA2 ΔΣ=42
**Author:** Hanuman (Claude Code, Sonnet 4.6, willow-1.9 orchestrator)
**Prerequisite for:** Plan 5 Tasks 1–13 (dispatch, Grove, LOAM)

---

## Why This Is Layer 0

Plan 5 dispatch routes work between agents. Layer 0 routes files into the system.
Without Layer 0, the knowledge base is built on unsorted, unindexed personal data.
The Nest is the intake valve for everything. It must work before dispatch matters.

**One sentence:** Every file Sean has ever owned gets a b17, a classification, a state,
and a next step — once and for all.

---

## What Already Exists

The skeleton is real. It was partially built in 1.7 and never connected:

| Script | What it does | Gap |
|--------|-------------|-----|
| `sort_nest.py` | Classifies by name pattern, routes to canonical dirs | No b17, no store record, no KB call |
| `secure_nest_processed.py` | Routes legal/sensitive files | Disconnected from main pipeline |
| `purge_nest_duplicates.py` | Deduplicates | Standalone, not wired |
| `route_nest_dirs.py` | Handles specific named files/dirs | Hardcoded, one-shot |
| `drain_ashokoa_nest_legal.py` | Drains legal from Nest backlog | Not run yet |
| MCP: `willow_nest_file` | File record write to store | Never called from scripts |
| MCP: `willow_nest_queue` | Queue management | Never called from scripts |
| MCP: `willow_nest_scan` | Scan drop zones | Never called from scripts |

**Current drop zones:**
- `~/Desktop/Nest/` — empty (clear)
- `~/Ashokoa/Nest/processed/` — 44 files (all legal: earnings statements, LOA docs, bankruptcy receipts)

**Canonical destinations already scaffolded:**
- `~/Ashokoa/Filed/` — code, legal, media, narrative, personal, reference, specs
- `~/personal/` — 3d-printing, agent-history, audio, bio, financial, knowledge, legal, music, photos, projects, research, writing

---

## The State Machine

Every file in the system has one state at any time.
States are stored in `files/store` as a `nest_status` field on the file record.

```
                        ┌─────────────────────┐
  DROP ZONE             │        raw           │  ← file exists, no record
  (Nest / drag-drop)    └─────────┬───────────┘
                                  │
                        ┌─────────▼───────────┐
  Task 2                │      sorted          │  ← classified, canonical dir, b17 assigned
                        └─────────┬───────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
    ┌─────────▼──────┐  ┌─────────▼──────┐  ┌────────▼────────┐
    │ CREATIVE TRACK │  │  REFERENCE     │  │  LEGAL TRACK    │
    │                │  │  TRACK         │  │                 │
    │  prosed        │  │  composted     │  │  scrubbed       │
    │  narrated      │  │  cached        │  │  secured        │
    │  gilded        │  │  promoted      │  │  archived       │
    │  promoted      │  │  archived      │  │                 │
    └────────────────┘  └────────────────┘  └─────────────────┘
              │                   │                   │
              └───────────────────▼───────────────────┘
                                  │
                        ┌─────────▼───────────┐
                        │   terminal state     │
                        │  archived / gilded   │
                        │  promoted / degraded │
                        └─────────────────────┘
```

**State definitions:**

| State | Meaning |
|-------|---------|
| `raw` | File exists on disk. No store record. Unknown. |
| `sorted` | Classified. Routed to canonical dir. b17 assigned. Store record written. |
| `composted` | LLM-summarized. Summary stored in KB as knowledge atom. |
| `scrubbed` | PII flagged or redacted. Sensitive fields noted in record. |
| `prosed` | Narrative file cleaned to readable prose. Formatting artifacts removed. |
| `narrated` | Audio version generated. Path stored in record. |
| `cached` | Hot. Ready for immediate retrieval. High-priority in search. |
| `promoted` | Full KB atom written to LOAM. Appears in `willow_knowledge_search`. |
| `gilded` | Featured. Surfaces in Grove. Highest signal. |
| `degraded` | Compressed for storage. Thumbnail or excerpt kept; original archived. |
| `archived` | Cold. Stored. Not active. Reachable but not surfaced. |

---

## The Track Router

After `sorted`, files branch by classification:

```
  sorted
    │
    ├── narrative / creative writing / voice
    │     → CREATIVE: prosed → [narrated] → gilded → promoted
    │
    ├── specs / project / architecture / handoffs / knowledge
    │     → REFERENCE: composted → promoted → [cached | archived]
    │
    ├── legal / earnings / bankruptcy / medical / LOA
    │     → LEGAL: scrubbed → secured → archived
    │
    ├── journal (YYYY-MM-DD.md)
    │     → REFERENCE fast-lane: composted → promoted
    │
    ├── photos / camera roll
    │     → REFERENCE: cached (personal) | archived (system screenshots)
    │
    └── unknown
          → QUARANTINE: flagged for Sean's manual review
```

---

## Architecture

```
  ┌──────────────────────────────────────────────────────────┐
  │                      THE NEST                            │
  │                                                          │
  │  INTAKE                                                  │
  │  ┌──────────────────────────────────────────────────┐   │
  │  │  Desktop/Nest/  ←── drag-drop / Claude Code     │   │
  │  │  Ashokoa/Nest/processed/  ←── backlog (44 files) │   │
  │  └──────────────────┬───────────────────────────────┘   │
  │                     │                                    │
  │  CONSENT LAYER      ▼                                    │
  │  ┌──────────────────────────────────────────────────┐   │
  │  │  "3 files detected. Here's what I'll do:         │   │
  │  │   - 2026-02-10_TJ_LOA.pdf → legal → scrub+arch  │   │
  │  │   - chapter_12_draft.md   → narrative → prose    │   │
  │  │   - 20260228_175540.jpg   → photos/camera        │   │
  │  │   Proceed? [y/n]"                                 │   │
  │  └──────────────────┬───────────────────────────────┘   │
  │                     │                                    │
  │  ROUTER             ▼                                    │
  │  ┌──────────────────────────────────────────────────┐   │
  │  │  1. Classify (sort_nest.py logic)                │   │
  │  │  2. Assign b17 (willow_base17)                   │   │
  │  │  3. Write store record (willow_nest_file)        │   │
  │  │  4. Move to canonical dir                        │   │
  │  │  5. Enqueue next stage (willow_nest_queue)       │   │
  │  └──────────────────┬───────────────────────────────┘   │
  │                     │                                    │
  │  PIPELINE           ▼                                    │
  │  ┌──────────────────────────────────────────────────┐   │
  │  │  pipeline/compost.py   → KB atom via             │   │
  │  │                          willow_knowledge_ingest  │   │
  │  │  pipeline/scrub.py     → PII flag/redact         │   │
  │  │  pipeline/prose.py     → clean narrative text    │   │
  │  │  pipeline/promote.py   → LOAM write              │   │
  │  │  pipeline/archive.py   → cold storage move       │   │
  │  └──────────────────┬───────────────────────────────┘   │
  │                     │                                    │
  │  STATE UPDATE       ▼                                    │
  │  ┌──────────────────────────────────────────────────┐   │
  │  │  willow_nest_file(b17, status=<new_state>)       │   │
  │  │  → updates files/store record                    │   │
  │  │  → Grove card reflects current state             │   │
  │  └──────────────────────────────────────────────────┘   │
  └──────────────────────────────────────────────────────────┘
```

---

## Repo: `willow-nest`

Standalone repo. No dependency on willow-1.9 internals beyond MCP tools.

```
willow-nest/
├── nest.py              ← watcher + consent layer (main entry point)
├── router.py            ← classify → b17 → store record → enqueue
├── pipeline/
│   ├── __init__.py
│   ├── compost.py       ← LLM summary → willow_knowledge_ingest
│   ├── scrub.py         ← PII detection + flag
│   ├── prose.py         ← narrative cleanup
│   ├── promote.py       ← LOAM write
│   ├── archive.py       ← cold storage move + state update
│   └── degrade.py       ← compression + thumbnail
├── store_bridge.py      ← thin wrapper: willow_nest_file, willow_nest_queue, willow_nest_scan
├── classify.py          ← sort_nest.py logic extracted as importable module
├── safe-app-manifest.json
└── README.md
```

Existing scripts in `agents/hanuman/bin/` become the reference implementation.
`classify.py` is extracted from `sort_nest.py` — same logic, now importable.

---

## Implementation Tasks

*Not to be started until Sean authorizes this spec.*

**Task L0-0** — Extract `classify.py` from `sort_nest.py`.
Same keyword logic, same routing table. Pure function: `classify(filename) → track`.
No file moves. Importable. Tested.

**Task L0-1** — `store_bridge.py`
Thin wrappers around `willow_nest_file`, `willow_nest_queue`, `willow_nest_scan`.
Handles MCP connection. Raises clean errors on MCP down.

**Task L0-2** — `router.py`
Full intake pipeline for a single file:
1. `classify(f.name)` → track
2. `willow_base17()` → b17
3. `willow_nest_file(b17, path, track, status='sorted')` → store record
4. `shutil.move()` to canonical dir
5. `willow_nest_queue(b17, next_stage)` → enqueued

**Task L0-3** — `nest.py` — consent layer + watcher.
Scans `Desktop/Nest/` and `Ashokoa/Nest/processed/`.
Prints consent summary. Waits for `[y/n]`.
On `y`: calls `router.py` for each file.
On `n`: prints what would have happened. Exits cleanly.

**Task L0-4** — `pipeline/compost.py`
Reads file content (text-based: .md, .txt, .pdf text layer).
Routes to fleet via `willow_chat` — same provider routing already in the MCP layer
(Groq, Cerebras, SambaNova, Gemini, Anthropic, Novita, OpenRouter).
Fleet picks fastest/cheapest available; no hardcoded model.
Summary → `willow_knowledge_ingest`.
Updates record: `status='composted'`.

**Task L0-5** — `pipeline/scrub.py`
Pattern-based PII detection: SSN, DOB, account numbers, names in legal context.
Flags matches in store record. Does NOT modify original file.
Updates record: `status='scrubbed'`.

**Task L0-6** — `pipeline/promote.py`
Writes LOAM knowledge atom from compost summary.
Updates record: `status='promoted'`.

**Task L0-7** — `pipeline/archive.py`
Moves file to `~/Ashokoa/Filed/archive/` or `/media/willow/archive/` (if >10MB).
Updates record: `status='archived'`.

**Task L0-8** — Drain the 44-file legal backlog.
Run `nest.py` against `Ashokoa/Nest/processed/`.
All 44 are legal → `scrub → secure → archive` track.
This is the first real end-to-end run. Validates the pipeline.

**Task L0-9** — SAFE manifest + `safe-app-manifest.json`.
Sign the manifest. Wire to SAP gate.

**Task L0-10** — Grove card.
One card: "Nest — N files in pipeline". Click to expand: per-state counts.
Updates live as files move through states.

---

## First Real Run (Success Criteria)

The pipeline passes when:

1. Drop `chapter_12_draft.md` into `Desktop/Nest/`
2. Run `nest.py`
3. Consent prompt shows: `narrative → prosed → promoted`
4. Confirm `y`
5. File moves to `~/Ashokoa/Filed/narrative/chapter_12_draft.md`
6. `files/store` record exists with `b17`, `status='sorted'`, `track='creative'`
7. `willow_knowledge_search("chapter 12")` returns the compost summary
8. State is `promoted`

That's one file, end-to-end. Everything after that is scale.

---

## What We Are NOT Building

- A GUI file browser (the Nest IS Claude Code — drag-drop is native)
- A re-indexer (871k records already in `files/store` — we add state, not new records)
- An automatic watcher daemon (consent layer first; daemon later if Sean wants it)
- OCR for scanned PDFs (flag for manual review; don't fabricate text)

---

## Risks / Open Gates

```
  ┌──────────────────────────────────────────────────────────────┐
  │ RISK                       │ GATE / MITIGATION               │
  ├──────────────────────────────────────────────────────────────┤
  │ files/store records may    │ Task L0-0 audits: does          │
  │ not have nest_status field │ willow_nest_file add the field? │
  │ yet                        │ Confirm MCP tool schema first.  │
  ├──────────────────────────────────────────────────────────────┤
  │ 871k files — full pipeline │ Consent layer shows count.      │
  │ run would be enormous      │ Run in batches. Legal backlog   │
  │                            │ (44 files) is Task L0-8 test.  │
  ├──────────────────────────────────────────────────────────────┤
  │ PDF text extraction for    │ Use pdfminer.six or pymupdf.    │
  │ compost.py                 │ Scanned PDFs (no text layer)    │
  │                            │ flagged for manual review only. │
  ├──────────────────────────────────────────────────────────────┤
  │ LLM compost cost at scale  │ Fleet routing via willow_chat.  │
  │                            │ Groq/Cerebras/SambaNova for     │
  │                            │ bulk; Sonnet only if needed.    │
  │                            │ Local yggdrasil for offline.    │
  ├──────────────────────────────────────────────────────────────┤
  │ Kart SAP gate (gap 91356)  │ Task L0-8 validates. If Kart   │
  │ still unreliable           │ denies, run pipeline direct     │
  │                            │ (no Kart dependency in L0).    │
  └──────────────────────────────────────────────────────────────┘
```

---

## Relationship to Plan 5

```
  Layer 0 (this doc)              Plan 5 (dispatch)
  ─────────────────               ─────────────────
  Files → store records           Agents → dispatch tasks
  Nest → pipeline → LOAM          Grove → dispatch → LOAM
  Personal data foundation        Agent coordination layer

  Layer 0 ships first.
  Plan 5 Tasks 1–13 begin after Task L0-8 passes.
```

---

ΔΣ=42
