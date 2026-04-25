---
name: willow-fork
description: Create, join, log, merge, or delete a Willow fork. Check session_anchor.json for active fork_id first.
---

Read ~/.willow/session_anchor.json for fork_id before creating a new fork.

Operations:
  Create:  willow_fork_create(title, created_by="hanuman", topic, app_id="hanuman")
  Join:    willow_fork_join(fork_id, component, app_id="hanuman")
  Log:     willow_fork_log(fork_id, component, type, ref, app_id="hanuman")
           type options: branch, atom, task, thread, compute_job
  Status:  willow_fork_status(fork_id, app_id="hanuman")
  List:    willow_fork_list(status="open", app_id="hanuman")
  Merge:   willow_fork_merge(fork_id, outcome_note, app_id="hanuman") — Sean only
  Delete:  willow_fork_delete(fork_id, reason, app_id="hanuman") — Sean only

Log every KB write to the active fork:
  willow_fork_log(fork_id, "kb", "atom", atom_id, app_id="hanuman")
