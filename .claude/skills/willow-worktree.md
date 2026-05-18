---
name: willow-worktree
description: Set up a git worktree + Willow fork for scoped development work. Use for any bounded feature or multi-session project.
---

A Willow dev project needs two things: a git worktree (isolated branch) and a Willow fork (SOIL tracking record). Do both together.

## 1. Create the git branch + worktree

```bash
# Convention: feat/<short-slug>
git worktree add ../willow-wt/<slug> -b feat/<slug>
```

Worktrees live alongside the repo at `../willow-wt/<slug>` so they don't clutter the main tree. The `-b` flag creates the branch.

## 2. Create the Willow fork

```
fork_create(
  title="<human title>",
  created_by="heimdallr",
  topic="<slug>",
  app_id="willow"
)
```

Save the returned `fork_id`.

## 3. Log the branch to the fork

```
fork_log(
  fork_id=<fork_id>,
  component="git",
  type="branch",
  ref="feat/<slug>",
  app_id="willow"
)
```

## 4. Note the worktree path

The worktree is at `../willow-wt/<slug>` (absolute: `/home/sean-campbell/willow-wt/<slug>`).
Open it in a new Claude Code session or editor window. The Willow MCP server runs from the main repo — the worktree shares it.

## Teardown (after merge)

```bash
git worktree remove ../willow-wt/<slug>
git branch -d feat/<slug>
```

Then close the fork:
```
fork_merge(fork_id=<fork_id>, outcome_note="merged to master", app_id="willow")
```
