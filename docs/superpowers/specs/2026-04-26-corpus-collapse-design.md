# Corpus Collapse — The Willow Learning Protocol
**b17:** 0BB5E  
**date:** 2026-04-26  
**status:** draft  
**author:** Hanuman (session b, 2026-04-26)  
ΔΣ=42

---

## Why This Exists

There are two daughters.

Their names are Opal and Ruby. They are nine years old. Their father is building something so that when they grow up, technology works for them — not the other way around.

Every system in Willow exists because of that sentence. The consent framework. The local-first architecture. The knowledge graph. The agents. All of it flows from one place: technology should not be a burden on the people you love.

This spec is about how Willow learns. How it receives a person — any person — from the very first moment, and builds itself around them. How it gets better the more they use it, without them having to understand the machinery. How what they learn can help people they'll never meet, if they choose to share it.

The spec starts at 0. A person. Nothing yet.

It ends at 0. That same person. Everything working. Nothing to manage.

What comes out the other side is the point.

---

## The Human Journey

```
                    THE WILLOW EXPERIENCE
                    ═════════════════════

  ┌─────────────────────────────────────────────────────────┐
  │  DAY 0 — ARRIVAL                                        │
  │                                                         │
  │  A person opens Willow.                                 │
  │  They have: themselves.                                 │
  │  Maybe they have old files. Maybe not.                  │
  │  The system asks one question:                          │
  │                                                         │
  │         "Why are you here?"                             │
  │                                                         │
  │  That answer becomes the seed.                          │
  │  Everything the system learns about them                │
  │  will be measured against it.                           │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │  DAY 0 — BRINGING WHAT THEY HAVE (optional)            │
  │                                                         │
  │  "I have years of notes in Google Drive."               │
  │  "I have old conversations with Claude."                │
  │  "I have nothing, let's start fresh."                   │
  │                                                         │
  │  All three are fine.                                    │
  │  If they have history, Willow imports it.               │
  │  It becomes searchable, connected, alive.               │
  │  They don't need to organize it.                        │
  │  The system finds what's in it.                         │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │  SESSION 1 — THE SYSTEM RECEIVES THEM                   │
  │                                                         │
  │  Willow knows: why they're here.                        │
  │  Willow knows: what history they brought.               │
  │  Willow does not yet know: how they like to work.       │
  │                                                         │
  │  That's fine. It learns.                                │
  │                                                         │
  │  When it gets something wrong, it notices.              │
  │  It doesn't ask the person to remember to tell it.      │
  │  It catches the correction itself.                      │
  │  It holds it.                                           │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │  SESSION 5 — THE SYSTEM STARTS TO KNOW THEM             │
  │                                                         │
  │  It has seen enough to recognize patterns.              │
  │  It anticipates instead of reacts.                      │
  │  The corrections become rare.                           │
  │  The work gets faster.                                  │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │  SESSION 20 — THE SYSTEM KNOWS THEM                     │
  │                                                         │
  │  It loads who they are before the first tool fires.     │
  │  It knows their why.                                    │
  │  It knows how they communicate.                         │
  │  It knows what they've corrected before                 │
  │  and doesn't repeat those mistakes.                     │
  │                                                         │
  │  It feels like working with someone who knows you.      │
  │  Because it does.                                       │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │  ONGOING — GIVING BACK (consent-gated)                  │
  │                                                         │
  │  The things they figured out —                          │
  │  the patterns, the corrections, the fixes —             │
  │  can help other Willow users.                           │
  │                                                         │
  │  But only if they say yes.                              │
  │  Default is always: keep it to yourself.                │
  │  The gate is always there.                              │
  │  The choice is always theirs.                           │
  └─────────────────────────────────────────────────────────┘
```

---

## The Problem This Solves

Every session that starts cold is a tax. A tax on the person's time. A tax on their trust. A tax on the promise that this technology works for them.

The agent wakes up not knowing who you are. You have to re-explain. The lesson you taught it last Tuesday isn't there. The correction you made three sessions ago — gone. The system that was supposed to know you treats you like a stranger.

That's the problem. Not a technical problem. A loyalty problem.

```
THE TAX (what we're eliminating)
═════════════════════════════════

  Session N:
  "Don't use Bash for file listings."
  Agent corrected. Lesson learned (in context).

  Session N+1:
  Agent uses Bash for file listings.
  Same correction.
  Same tax.

  Session N+2:
  Same.

  This has happened. Many times. To Sean.
  To every Willow user.
  It will happen to Opal if we don't fix it.

  THE FIX: the correction from session N
  is in the room before session N+1 starts.
  Not buried in a store. In the room.
```

---

## The Architecture

`willow.corpus` is the module that makes the human journey possible. It is not new infrastructure. Every piece it uses already exists. It is the wire that connects them.

```
THE FULL PICTURE
════════════════

                         THE PERSON
                             │
              ┌──────────────┴──────────────┐
              │                             │
         ARRIVAL                      EACH SESSION
         (once)                       (ongoing)
              │                             │
              ▼                             ▼
       corpus.intake                 corpus.capture
       (import mode)                 (learn mode)
              │                             │
              │    ┌────────────────────────┘
              │    │
              ▼    ▼
          corpus.ingest
          (shared write layer)
                │
                ▼
         KB + local store
         (the memory)
                │
                ▼
         corpus.propagate
         (consent-gated git flow)
                │
      ┌─────────┴──────────┐
      │                    │
      ▼                    ▼
  personal              upstream
  branch                (with consent)
  (automatic)                │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
              Sean's main        future public
              (willow-1.9)       Willow repo
              (consent gate)     (opt-in only)
```

---

## Component 1: `corpus.intake` — Arrival Mode

The first thing a new person does. Or an existing person discovering old data.

```
IMPORT FLOW
═══════════

  "I have this."
       │
       ▼
  ┌───────────────────────────────────────────────────┐
  │  corpus.intake receives the source                │
  │  (path, URL, file, directory, service)            │
  └───────────────────────┬───────────────────────────┘
                          │
                          ▼
  ┌───────────────────────────────────────────────────┐
  │  willow_nest_scan                                 │
  │  "What's in here? What format is this?"           │
  │  Returns: list of importable items                │
  └───────────────────────┬───────────────────────────┘
                          │
                          ▼
  ┌───────────────────────────────────────────────────┐
  │  willow_nest_queue                                │
  │  "Stage these for processing."                    │
  │  Assigns typed importer per item                  │
  └───────────────────────┬───────────────────────────┘
                          │
                          ▼
  ┌───────────────────────────────────────────────────┐
  │  willow_nest_file (per item)                      │
  │  Typed importers handle format                    │
  │                                                   │
  │  Known formats today:                             │
  │  • Claude Desktop memories.json                   │
  │  • Willow JSONL session files                     │
  │  • Markdown documents                             │
  │  • Plain text                                     │
  │  • CSV / spreadsheet                              │
  │                                                   │
  │  Unknown formats → gap atom written               │
  │  "We don't know this format yet.                  │
  │   Here's how to add support for it."              │
  └───────────────────────┬───────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       knowledge atoms          identity seeds
       (history, sessions,      IF detectable:
        documents, notes)       • why they're here
                                • how they communicate
                                • what they've learned
              │                       │
              └───────────┬───────────┘
                          ▼
                   corpus.ingest
                          │
                          ▼
                  git commit:
                  "corpus: import — N atoms"

  THE PERSON EXPERIENCES:
  "I dropped in my old stuff.
   It's searchable now.
   The system knows my history.
   I didn't have to organize anything."
```

---

## Component 2: `corpus.capture` — Learn Mode

What happens in every session, automatically. The person does nothing.

```
CORRECTION CAPTURE FLOW
═══════════════════════

  SOMETHING GOES WRONG IN THE SESSION:

  Agent tries wrong tool          Agent makes wrong assumption
         │                                  │
         ▼                                  ▼
  pre_tool hook fires            UserPromptSubmit detects
  tool BLOCKED                   correction keyword
  ("use Glob, not Bash")         ("no", "wrong", "don't")
         │                                  │
         └──────────────┬───────────────────┘
                        ▼
               corpus.capture.stage()
               writes to:
               hanuman/corrections/pending
                        │
                        │  (survives session — in the store)
                        │
                        ▼
                NOTHING ELSE YET.
                The person keeps working.
                The system is holding the lesson.

  ───────────────────────────────────────────────

  SESSION ENDS:

  SessionEnd hook fires
          │
          ▼
  reads corrections/pending
          │
          ├── EMPTY: "Session clean. No patterns staged."
          │
          └── HAS CANDIDATES:
              ┌─────────────────────────────────────────┐
              │  "3 patterns staged this session:        │
              │                                          │
              │  1. Bash listing blocked                 │
              │     → tool_priority pattern              │
              │                                          │
              │  2. MCP env var in wrong file            │
              │     → mcp_config_location pattern        │
              │                                          │
              │  3. Correction: announce-then-don't      │
              │     → execute_before_narrating pattern   │
              │                                          │
              │  /learn to capture  /skip to clear"      │
              └─────────────────────────────────────────┘
                          │
                          ▼
                   /learn runs
                   (review, not recall —
                    the system already knows
                    what happened)
                          │
                          ▼
                   skill files written
                   KB feedback atoms written
                   corrections/pending cleared
```

---

## Component 3: `corpus.ingest` — The Shared Write Layer

One path to the KB. Both import and capture flow through here.

```
INGEST LAYER
════════════

  corpus.intake ──────────┐
                          ▼
  corpus.capture ────────► corpus.ingest.write(
                              atom: the knowledge,
                              collection: where it lives,
                              domain: whose it is,
                              identity_fields: if present
                           )
                                    │
                          ┌─────────┴──────────┐
                          ▼                    ▼
                  willow_knowledge_ingest    store_put
                  (Postgres KB —             (local store —
                   searchable,               fast, offline)
                   long-term)
                          │                    │
                          └─────────┬──────────┘
                                    ▼
                             b17 assigned
                             atom persisted
                             ready for propagate

  DOMAIN NAMESPACING:
  Every user has their own namespace.
  Sean's atoms: hanuman/*, sean/*
  New user's atoms: their_agent/*, their_name/*
  Never mixed. Never overwritten.
  The system knows whose knowledge is whose.
```

---

## Component 4: `corpus.propagate` — The Consent Gates

What happens to the knowledge after it's captured. The person is always in control.

```
PROPAGATION MODEL
═════════════════

  ┌──────────────────────────────────────────────────────────────┐
  │  LEVEL 0 — Pending (volatile)                               │
  │                                                             │
  │  corrections/pending in store                               │
  │  "Something happened. We're holding it."                    │
  │  Lives until /learn or /skip                                │
  │  Person never sees this layer.                              │
  └──────────────────────────────┬──────────────────────────────┘
                                 │  /learn
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  LEVEL 1 — Personal Branch (persistent, local)             │
  │                                                             │
  │  ~/.claude/skills/learned/<pattern>.md                      │
  │  {agent}/feedback/store atoms                               │
  │  git branch: corpus/learn-<date>                            │
  │                                                             │
  │  Automatic. No consent needed.                              │
  │  This is theirs. It stays with them.                        │
  └──────────────────────────────┬──────────────────────────────┘
                                 │  person merges (optional)
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  LEVEL 2 — Personal Main (local canon)                     │
  │                                                             │
  │  git merge corpus/learn-<date>                              │
  │  "This is my canonical knowledge state."                    │
  │                                                             │
  │  Consent: implicit (they merged it)                         │
  └──────────────────────────────┬──────────────────────────────┘
                                 │  corpus.propagate asks:
                                 │  "Share this upstream?"
                                 │  DEFAULT: NO
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  LEVEL 3 — Main Main (willow-1.9 today)                    │
  │                                                             │
  │  PR opened. Sean reviews. Sean merges.                      │
  │  This pattern now helps everyone.                           │
  │                                                             │
  │  Consent: EXPLICIT. Separate prompt.                        │
  │  Person must say yes. No defaults here.                     │
  └──────────────────────────────┬──────────────────────────────┘
                                 │  future: public repo exists
                                 │  separate opt-in, never assumed
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  LEVEL 4 — Public Willow (future)                          │
  │                                                             │
  │  The revolution, digitized.                                 │
  │  What one person figured out helps                          │
  │  someone they'll never meet.                                │
  │                                                             │
  │  Consent: explicit opt-in.                                  │
  │  Never surfaced unless requested.                           │
  │  Never assumed. Never extracted.                            │
  └──────────────────────────────────────────────────────────────┘

  THE PERSON EXPERIENCES:
  "I don't have to think about any of this.
   My patterns stay with me.
   I can share if I want to.
   I never have to."
```

---

## The Identity Layer — What Loads Before Anything Else

Before the first tool fires. Before the first question is asked. The system knows who it's talking to.

```
SESSION START — UPDATED /startup
═════════════════════════════════

  OLD (what loads today):            NEW (what loads tomorrow):
  ─────────────────────────          ────────────────────────────
  willow_status → health             willow_status → health
  handoff → open work                handoff → open work
  flags → standing concerns          flags → standing concerns
                                     +
                                     feedback/store → top 7
                                     corrections by date
                                     +
                                     motivation/store → the why
                                     (Opal + Ruby for Sean,
                                      their answer for anyone)
                                     +
                                     voice/store → how they
                                     communicate

  WHAT THE AGENT KNOWS AT BOOT:

  ┌────────────────────────────────────────────────┐
  │  WHO:    this person's core motivation         │
  │  HOW:    their communication style             │
  │  WHAT:   7 most recent corrections             │
  │  WHERE:  open work from last session           │
  │  FLAGS:  anything standing and open            │
  └────────────────────────────────────────────────┘

  NEW USER (session 1):
  • motivation: seeded by boot.py answer
  • corrections: empty (none yet)
  • voice: empty (learning starts now)
  → Agent knows why they're here.
    Doesn't yet know how they work.
    That's fine. It's session 1.

  SESSION 5:
  • motivation: the root
  • corrections: 5-15 patterns captured
  • voice: emerging picture
  → Agent recognizes patterns.
    Anticipates instead of reacts.

  SESSION 20:
  • Full identity layer.
  → Agent feels like it knows them.
    Because it does.
```

---

## The Self-Repair Loop — When Things Don't Work

The system doesn't just fail silently. It writes down what broke and how to fix it.

```
SELF-REPAIR FLOW
════════════════

  Any corpus operation fails:
  import error, capture error,
  ingest error, unknown format
           │
           ▼
  ┌────────────────────────────────────────────────────┐
  │  corpus writes gap atom to {agent}/gaps            │
  │                                                    │
  │  {                                                 │
  │    "what_failed": "nest_scan",                     │
  │    "why": "path not found",                        │
  │    "proposed_fix": "check NEST_ROOT env var",      │
  │    "status": "open",                               │
  │    "severity": "medium"                            │
  │  }                                                 │
  └────────────────────────┬───────────────────────────┘
                           │
                           ▼
                  /status surfaces open gaps
                  "3 open gaps: [list]"
                           │
                           ▼
                  Kart reads open gaps
                  queues fix tasks
                           │
                           ▼
                  Fix executes
                           │
                           ▼
                  gap → status: "resolved"
                  corpus commits: "fix: close gap <id>"

  THE PERSON EXPERIENCES:
  "Something didn't work.
   The system told me what.
   It fixed it, or told me how.
   I didn't have to debug anything."
```

---

## The New User Complete Journey

```
A PERSON ARRIVES
════════════════

  ┌──────────────────────────────────────────────────────────┐
  │  boot.py                                                 │
  │                                                          │
  │  "Why are you here?"                                     │
  │  [their answer]                                          │
  │                                                          │
  │  → motivation atom created                               │
  │  → SAFE identity created                                 │
  │  → Willow Grove connected                                │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │  corpus.intake (optional)                                │
  │                                                          │
  │  "Do you have existing data to bring in?"                │
  │                                                          │
  │  YES: drop in files/folders                              │
  │  → Nest processes all known formats                      │
  │  → Identity seeds extracted where detectable            │
  │  → History searchable from session 1                     │
  │  → git commit: "corpus: initial import — N atoms"       │
  │                                                          │
  │  NO: that's fine. Start fresh.                           │
  │  → Identity builds from session 1 forward               │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │  SESSION 1                                               │
  │                                                          │
  │  /startup loads:                                         │
  │  ✓ motivation (from boot.py)                             │
  │  ✗ corrections (none yet — that's expected)             │
  │  ✗ voice (none yet — that's expected)                   │
  │                                                          │
  │  Work happens.                                           │
  │  Tool blocks auto-staged.                                │
  │  Corrections auto-staged.                                │
  │                                                          │
  │  SessionEnd: "2 patterns staged. /learn to capture."    │
  │  /learn runs.                                            │
  │  git commit: "corpus: session-1 — 2 patterns"           │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │  SESSION 2                                               │
  │                                                          │
  │  /startup loads:                                         │
  │  ✓ motivation                                            │
  │  ✓ 2 corrections from session 1                         │
  │  ✓ handoff from session 1                               │
  │                                                          │
  │  Agent already knows 2 things about them.               │
  │  Those corrections don't happen again.                   │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
                         ...grows...
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │  SESSION 20+                                             │
  │                                                          │
  │  Full identity layer loaded at boot.                     │
  │  Agent works like it knows them.                         │
  │  Because it does.                                        │
  │                                                          │
  │  Corrections rare.                                       │
  │  Patterns stable.                                        │
  │  Technology working for them.                            │
  │  Not extracting. Not burdening.                          │
  │  Working.                                                │
  └──────────────────────────────────────────────────────────┘
```

---

## The Existing User Journey (Hanuman Today)

```
SEAN, SESSION B, 2026-04-26
════════════════════════════

  /startup (updated):
    ✓ health: all green
    ✓ handoff: wire OpenClaw
    ✓ flags: ORIGIN permanent flag
    ✓ feedback atoms: 27 corrections loaded        ← NEW
    ✓ motivation: Opal + Ruby                       ← NEW
    ✓ voice: earnest, punchy, execute first        ← NEW

  SESSION WORK:
    → tool block: Bash listing
       corpus.capture.stage() fires
       corrections/pending: [{tool: Bash, pattern: use_glob}]

    → correction from Sean: "that's the gap"
       UserPromptSubmit detects correction
       corrections/pending: [..., {type: correction}]

  SESSION END:
    SessionEnd hook:
    "2 patterns staged:
     • Bash listing blocked
     • MCP env var location
     /learn to capture."

    /learn runs.
    2 skill files written.
    2 KB atoms written.
    corrections/pending cleared.

    corpus.propagate:
    git commit: "corpus: learn 2026-04-26-b — 2 patterns"
    branch: corpus/learn-2026-04-26

    "Share upstream?" → NO (default)
    Stays local. Sean's patterns. His to keep.
```

---

## Module Structure

```
willow/
└── corpus/
    ├── __init__.py
    ├── intake.py       # Import mode — orchestrates Nest
    │                   # Entry: corpus.intake.run(source)
    │
    ├── capture.py      # Learn mode — correction staging
    │                   # Entry: corpus.capture.stage(type, ...)
    │                   # Called by: fylgja hooks
    │
    ├── ingest.py       # Shared KB write layer
    │                   # Entry: corpus.ingest.write(atom, ...)
    │                   # Used by: intake + capture
    │
    └── propagate.py    # Git-native consent-gated output
                        # Entry: corpus.propagate.commit(...)
                        # Entry: corpus.propagate.ask_upstream()
```

---

## Gap Inventory — What This Closes

```
┌──────────────────────────────────────┬────────────────────────────────────┐
│  Gap                                 │  Fix                               │
├──────────────────────────────────────┼────────────────────────────────────┤
│  Agent boots without knowing         │  Identity layer added to /startup  │
│  who the user is                     │  (feedback + motivation + voice)   │
├──────────────────────────────────────┼────────────────────────────────────┤
│  Corrections lost between sessions   │  corpus.capture auto-stages them   │
│                                      │  to corrections/pending            │
├──────────────────────────────────────┼────────────────────────────────────┤
│  New users start cold                │  corpus.intake via Nest            │
│  (no history, no identity)           │  imports existing data day 1       │
├──────────────────────────────────────┼────────────────────────────────────┤
│  Patterns die in session             │  corpus.propagate commits to       │
│  (no persistence beyond /learn)      │  personal git branch               │
├──────────────────────────────────────┼────────────────────────────────────┤
│  Improvements never flow upstream    │  Consent-gated git propagation     │
│                                      │  L1→L2→L3→L4                       │
├──────────────────────────────────────┼────────────────────────────────────┤
│  System fails silently               │  Gap atoms + Kart self-repair loop │
├──────────────────────────────────────┼────────────────────────────────────┤
│  SessionEnd reminder too generic     │  Specific candidates from pending  │
│  ("did you run /learn?")             │  ("these 3 things happened")       │
└──────────────────────────────────────┴────────────────────────────────────┘
```

---

## What Is NOT In This Spec

- New MCP tools — uses existing tools only
- New Nest importers — Nest handles format expansion separately
- Changes to handoff system — handoff is a parallel pipeline
- Changes to boot.py — boot.py provides input, is not changed
- Yggdrasil training — separate pipeline
- Changes to Willow Grove — Grove consumes corpus output, not in scope here

---

## Implementation Order

```
Phase 1 — Identity at boot                    (1 session)
  Update /startup to load feedback +
  motivation + voice atoms.
  Test: boot confirms atoms in context.
  HIGHEST LEVERAGE — closes the tax immediately.

Phase 2 — corpus.capture                      (1 session)
  Write capture.py + stage() function.
  Wire pre_tool hook to capture blocks.
  Wire UserPromptSubmit to detect corrections.
  Update SessionEnd to surface specific candidates.
  Test: trigger block, confirm at SessionEnd.

Phase 3 — corpus.ingest                       (1 session)
  Write ingest.py as shared write layer.
  Refactor /learn to write through ingest.
  Test: /learn writes skill + KB atom via ingest.

Phase 4 — corpus.propagate                    (1 session)
  Write propagate.py with git commit logic.
  Wire /learn output to propagate.
  Test: run /learn, confirm branch + commit.

Phase 5 — corpus.intake                       (1-2 sessions)
  Write intake.py orchestrating Nest.
  Test: import Windows memories.json → KB atoms.
  Test: import JSONL sessions → identity seeds.

Phase 6 — Self-repair loop                    (1 session)
  Wire corpus failures to gap atoms.
  Test: force import failure → gap atom written.
  Test: /status surfaces the gap.
```

---

*b17: 0BB5E — ΔΣ=42*

*"The revolution will not be televised, but it will be digitized."*
*— Sean Campbell*
