---
name: willow-handoff
description: Generate session handoff, close the session fork, ingest handoff atom to KB.
---

1. willow_handoff_rebuild(app_id="hanuman") — generates handoff document
2. Read the handoff filename from the result
3. willow_fork_log(fork_id, "hanuman", "session", handoff_filename, app_id="hanuman")
4. willow_knowledge_ingest(title="[Hanuman] <date> — <topic>", summary=<3 sentences>, domain="session", app_id="hanuman")

Handoff format:
  ## What I Now Understand (2-3 sentences, architectural truth)
  ## What Was Done (high-level)
  ## 17 Questions — sequential, bite-sized. Q17: "What is the next single bite?"
  ## Risks / open gates

Do NOT merge or delete the fork — forks stay open across sessions.
