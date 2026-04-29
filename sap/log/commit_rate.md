# Commit Rate Report

**Generated:** 2026-04-29T19:05:50Z
**Windows checked:** last 2 h (since 2026-04-29T17:05:50Z) · last 24 h (since 2026-04-28T19:05:50Z)

---

## Access Constraints

> The GitHub MCP server available in this session is scoped exclusively to
> `rudi193-cmd/willow-1.9`. No `gh` CLI is installed and no `GITHUB_TOKEN` is
> set. Only `willow-1.9` commit data could be retrieved; all other repos under
> `rudi193-cmd` are listed as INACCESSIBLE.

---

## Repositories — rudi193-cmd

| Repo | Commits (2 h) | Commits (24 h) | Classification | Notes |
|------|:---:|:---:|---|---|
| willow-1.9 | 0 | 0 | **stable** | — |
| willow-1.5 | — | — | INACCESSIBLE | Outside MCP scope |
| *(other repos)* | — | — | INACCESSIBLE | `gh repo list` unavailable; no token |

---

## Detail: willow-1.9

- **Classification:** stable (no commits in last 24 h)
- **2-h window commits:** 0
- **24-h window commits:** 0
- **Change summary:** none

---

## Settling Repos

*(none accessible)*

---

## Action Required

To enable full multi-repo commit-rate monitoring, one of the following must be
configured:

1. Set `GITHUB_TOKEN` (or `GH_TOKEN`) environment variable with at least
   `repo:read` scope, **or**
2. Expand the MCP server's repository allow-list to include all monitored repos,
   **or**
3. Install the `gh` CLI and authenticate (`gh auth login`).
