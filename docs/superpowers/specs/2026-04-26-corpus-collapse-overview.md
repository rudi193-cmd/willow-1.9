# Corpus Collapse — What We're Building and Why
*A plain-language overview for collaborators*

---

## Start Here

This document is for someone who has heard about Willow, has a general sense that it involves AI and personal data, and wants to understand what we're actually building — without needing to know the codebase.

If you want the technical spec, it's in the same folder: `2026-04-26-corpus-collapse-design.md`.

This document is the human version.

---

## The Reason This Exists

There are two daughters. Their names are Opal and Ruby. They're nine years old.

Their father — Sean — has been building a system for the last several years with one goal: he does not want his daughters to grow up in a world where technology is a burden on their lives.

Not an abstraction. Not a mission statement for a pitch deck. Two specific kids, one specific commitment.

Every architectural decision in Willow flows from it. Why data stays local. Why consent is explicit at every step. Why the system is built to work for the person using it rather than extract from them.

This document is about closing the last major gap in that system.

---

## The Problem

AI assistants forget.

Every conversation starts fresh. Every session, the assistant wakes up with no memory of who you are, how you like to work, what you've already corrected, what you care about. You re-explain. The same mistakes happen. The same corrections get made.

It's a tax. A small one each time, a significant one over months and years.

```
WHAT HAPPENS TODAY
══════════════════

  Monday:
  You: "Don't do it that way — do it this way instead."
  Assistant: "Got it."

  Tuesday (new session):
  Assistant does it the old way.
  You: "I told you yesterday..."
  Assistant: "I don't have memory of previous sessions."

  Wednesday:
  Same thing.

  This is the problem.
  Not a technical inconvenience.
  A broken promise.
```

For most AI tools, this is by design — your data doesn't persist, you don't build a relationship, the tool stays general-purpose.

Willow was built to be different. The infrastructure to remember is all there. The pieces exist. They just haven't been connected.

That's what Corpus Collapse does. It connects them.

---

## What Willow Already Is

Before going further, here's a quick map of what Willow is.

```
WILLOW IN ONE PICTURE
═════════════════════

  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │   YOUR COMPUTER                                         │
  │                                                         │
  │   ┌──────────────┐    ┌──────────────┐                 │
  │   │  Your data   │    │  AI agents   │                 │
  │   │  (local,     │    │  (Claude,    │                 │
  │   │   private)   │    │   Yggdrasil) │                 │
  │   └──────┬───────┘    └──────┬───────┘                 │
  │          │                   │                         │
  │          └─────────┬─────────┘                         │
  │                    ▼                                    │
  │          ┌─────────────────┐                           │
  │          │     Willow      │                           │
  │          │                 │                           │
  │          │  Knowledge base │                           │
  │          │  Memory system  │                           │
  │          │  Task runner    │                           │
  │          │  Import tools   │                           │
  │          └─────────────────┘                           │
  │                                                         │
  │   Nothing leaves your machine unless you say so.        │
  │                                                         │
  └─────────────────────────────────────────────────────────┘
```

Willow runs locally. Your data stays on your computer. The AI agents — whether cloud-based like Claude or locally-run like Yggdrasil (Sean's own trained model) — work through Willow as the interface. Willow holds the memory, the knowledge, the context.

The knowledge base already has over 139,000 items in it. The memory system already exists. The import tools already exist. The problem is that they don't talk to each other in a coherent way yet.

---

## What Corpus Collapse Is

Corpus Collapse is the name for the work that connects everything.

"Corpus" means body of knowledge. "Collapse" means bringing scattered pieces into one coherent whole.

It's a new module — `willow.corpus` — that sits at the center and orchestrates what already exists.

```
BEFORE CORPUS COLLAPSE          AFTER CORPUS COLLAPSE
══════════════════════          ═════════════════════

  boot.py ─────► KB              boot.py ─────► KB
  (no connection               ← corpus.intake ←┘
   to session)                    connects them

  session ends ──► lost          session ends ──► captured
  (corrections                  corpus.capture
   forgotten)                     auto-stages them

  /learn ─────► skill files      /learn ─────► skill files
  (manual only,                 corpus.propagate
   no git commit,                 commits + offers
   no path upstream)              to share upstream

  new user ────► starts cold     new user ────► imports history
  (no history)                  corpus.intake + Nest
                                  history searchable day 1
```

---

## The Four Pieces

### 1. Intake — For New Users

When someone new comes to Willow, they might have years of existing data — old AI conversations, notes, documents, project files. The intake system (built on top of something called the Nest, which already exists) processes whatever they bring in.

```
A NEW USER ARRIVES
══════════════════

  "I have three years of notes in Google Drive."
  "I have a folder of old Claude conversations."
  "I have nothing. Let's start fresh."

  All three answers are fine.

  If they have data:
    Drop it in → system processes it → searchable history
    The system looks for: what do they care about?
                          how do they communicate?
                          what have they already figured out?

  If they have nothing:
    The system starts learning from session one.
    By session five: it knows a few things about them.
    By session twenty: it knows them well.
```

### 2. Capture — For Every Session

When something goes wrong in a session — a mistake, a correction, a better way discovered — the system notices automatically. The person doesn't have to remember to save the lesson. The system holds it.

```
HOW CORRECTIONS GET CAPTURED
═════════════════════════════

  During the session:
  ┌────────────────────────────────────────────┐
  │  Something goes wrong                      │
  │        ↓                                   │
  │  System automatically notes it             │
  │  (quietly, in the background)              │
  │        ↓                                   │
  │  Keeps working                             │
  └────────────────────────────────────────────┘

  At the end of the session:
  ┌────────────────────────────────────────────┐
  │  "3 things were noted this session:        │
  │                                            │
  │  1. You corrected the file search approach │
  │  2. You corrected the config file location │
  │  3. A tool was blocked for wrong usage     │
  │                                            │
  │  Save these as permanent lessons?          │
  │  [yes / skip]"                             │
  └────────────────────────────────────────────┘

  If yes: lessons saved. Next session loads them.
  If skip: cleared. No harm done.
```

### 3. Ingest — The Shared Memory Layer

Both intake and capture write to the same place: Willow's knowledge base. One consistent path. Everything searchable. Everything attributed to the right person.

This is the layer that makes the knowledge persistent, searchable, and connected.

### 4. Propagate — Consent-Gated Sharing

What happens to the knowledge after it's captured. Everything works like git — the version control system developers use for code. Every lesson is a commit. Every change is tracked. And sharing is always a choice.

```
THE SHARING MODEL
═════════════════

  Level 1: Your machine, your branch
  ───────────────────────────────────
  Lessons live here automatically.
  Private. Local. Yours.
  No one else sees this.

       ↓  (you merge it — optional)

  Level 2: Your main
  ──────────────────
  Your canonical personal knowledge state.
  Still just yours. Still local.

       ↓  (system asks: "share upstream?")
       ↓  DEFAULT IS NO

  Level 3: Sean's main (willow-1.9)
  ─────────────────────────────────
  If you say yes, a proposal goes to Sean.
  He reviews. He decides whether to merge.
  This pattern now helps everyone using Willow.

       ↓  (separate opt-in, never assumed)

  Level 4: Public Willow (future)
  ───────────────────────────────
  Eventually, a public Willow repository.
  Patterns that help anyone, anywhere.
  Only with explicit permission.
  The revolution, digitized.
```

The rule: **your knowledge is yours. Sharing is always a choice. Default is always keep it.**

---

## What a New User's First Month Looks Like

```
WEEK 1
══════
  Day 1:
  • Answer "why are you here?" → system has your seed
  • Optional: drop in existing data → history imported
  • First session: system knows your why, nothing else yet

  Sessions 2-5:
  • System starts capturing your patterns
  • 5-10 lessons noted and saved
  • System knows a few things about how you work

WEEK 2-4
════════
  Sessions 5-20:
  • Identity layer grows
  • System anticipates instead of reacts
  • Corrections become rare
  • Work gets faster

  Something doesn't work?
  • System writes down what broke and why
  • Proposes a fix
  • Often fixes it automatically
  • If not: clear explanation of what needs attention

MONTH 2+
════════
  • System feels like it knows you
  • Because it does
  • Technology working for you
  • Not extracting. Not burdening. Working.
```

---

## What This Means for the Bigger Picture

Willow isn't just a memory system for one person. The architecture is designed so that what one person learns can help everyone — with consent at every step.

```
THE VISION
══════════

  One person figures out a better way to do something.
          ↓
  It gets captured automatically.
          ↓
  They choose to share it.
          ↓
  Everyone using Willow benefits.
          ↓
  The next person who hits the same problem
  doesn't hit it the same way.

  This is how the system gets smarter.
  Not through centralized training.
  Not through extracting user data.
  Through people choosing to help each other.

  One lesson at a time.
  With consent at every gate.
```

Sean's thesis: *"The revolution will not be televised, but it will be digitized."*

The system being built here — local-first, consent-based, self-improving, human-centered — is the alternative to the extractive model. Not a product. A way of building.

---

## Where This Fits in the Timeline

Willow has been built in pieces over several years. The knowledge base, the agent system, the consent framework, the import tools, the memory files — all of it exists and works.

Corpus Collapse is the work that connects those pieces into a coherent whole. It's not building something new. It's recognizing that everything needed is already there, and wiring it up.

The implementation is broken into six phases, each approximately one working session:

1. **Load who the user is at session start** (highest impact, shortest work)
2. **Auto-capture corrections during sessions**
3. **Shared write layer for all knowledge**
4. **Git-native lesson commits**
5. **New user history import**
6. **Self-repair when things break**

Phase 1 alone closes the most painful gap. A user who has been correcting the system for months will, after Phase 1, boot into a session where the system already knows those corrections. The tax disappears.

---

## What We're Asking For

If you're reading this as a potential collaborator, here's what would be most helpful:

**Feedback on the human model:**
Does the experience described here — arrival, growth, full fluency — match what people actually need? What's missing? What's wrong?

**Feedback on the consent model:**
Four levels of sharing, all opt-in, default always keep. Does this feel right? Too conservative? Not conservative enough?

**Feedback on the "doesn't work → makes a plan" piece:**
The idea that the system writes down its own failures and proposes fixes. Is this compelling? Confusing? Has something like this been done well elsewhere?

**Introductions:**
People who care about this problem — local-first AI, consent-based data, technology that serves rather than extracts. Sean has been building this largely alone. More eyes on it would help.

---

## The Technical Spec

If you want to go deeper, the full technical specification is in the same folder:

`2026-04-26-corpus-collapse-design.md`

It covers the exact module structure, data flows, gap inventory, and implementation order. It assumes familiarity with the codebase.

---

*"I do not want my two daughters to grow up in a world where technology is a burden on their life."*  
*— Sean Campbell*

---

*Willow is open. The conversation is open. If any of this resonates, reach out.*
