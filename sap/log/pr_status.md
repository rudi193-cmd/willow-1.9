# PR Status Report

**Generated:** 2026-04-30T12:00:00Z

---

## Access Constraints

> The GitHub MCP server in this session is scoped exclusively to
> `rudi193-cmd/willow-1.9`. No `gh` CLI is available. All three requested PRs
> are in repositories outside that scope and return ACCESS_DENIED on every
> fetch attempt. Status is unchanged from the 2026-04-29 run.

---

## PR: modelcontextprotocol/python-sdk #2494

| Field | Value |
|-------|-------|
| **State** | UNKNOWN — repository outside MCP scope |
| **CI checks** | UNKNOWN |
| **Reviews** | UNKNOWN |
| **Last commit SHA** | UNKNOWN |
| **Fetch error** | MCP restricted to rudi193-cmd/willow-1.9 |

---

## PR: punkpeye/awesome-mcp-servers #5247

| Field | Value |
|-------|-------|
| **State** | UNKNOWN — repository outside MCP scope |
| **CI checks** | UNKNOWN |
| **Reviews** | UNKNOWN |
| **Last commit SHA** | UNKNOWN |
| **Fetch error** | MCP restricted to rudi193-cmd/willow-1.9 |

---

## PR: rudi193-cmd/willow-1.5 #4 *(closed without merge — tracked)*

| Field | Value |
|-------|-------|
| **State** | UNKNOWN — `willow-1.5` is outside MCP scope |
| **CI checks** | UNKNOWN |
| **Reviews** | UNKNOWN |
| **Last commit SHA** | UNKNOWN |
| **Fetch error** | MCP restricted to rudi193-cmd/willow-1.9; willow-1.5 is a separate repository |

---

## Action Required

To enable cross-repo PR tracking, configure one of:

1. `GITHUB_TOKEN` / `GH_TOKEN` env var with `repo:read` scope, **or**
2. Expand MCP allow-list to include the three repos above, **or**
3. Install and authenticate `gh` CLI (`gh auth login`).
