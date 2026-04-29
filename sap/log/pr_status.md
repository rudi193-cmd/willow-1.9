# PR Status Report

**Generated:** 2026-04-29T19:05:50Z

---

## Access Constraints

> The GitHub MCP server available in this session is scoped exclusively to
> `rudi193-cmd/willow-1.9`. No `gh` CLI is installed, no `GITHUB_TOKEN` is
> set, and unauthenticated GitHub REST API calls return HTTP 403. As a result,
> the three requested PRs cannot be fetched and are recorded below with an
> `ACCESS_DENIED` status.

---

## PR: modelcontextprotocol/python-sdk #2494

| Field | Value |
|-------|-------|
| **State** | UNKNOWN — repository outside MCP scope |
| **CI checks** | UNKNOWN |
| **Reviews** | UNKNOWN |
| **Last commit SHA** | UNKNOWN |
| **Fetch error** | HTTP 403 / no auth token; MCP restricted to rudi193-cmd/willow-1.9 |

---

## PR: punkpeye/awesome-mcp-servers #5247

| Field | Value |
|-------|-------|
| **State** | UNKNOWN — repository outside MCP scope |
| **CI checks** | UNKNOWN |
| **Reviews** | UNKNOWN |
| **Last commit SHA** | UNKNOWN |
| **Fetch error** | HTTP 403 / no auth token; MCP restricted to rudi193-cmd/willow-1.9 |

---

## PR: rudi193-cmd/willow-1.5 #4 *(closed without merge — tracked)*

| Field | Value |
|-------|-------|
| **State** | UNKNOWN — `willow-1.5` is outside MCP scope (MCP limited to `willow-1.9`) |
| **CI checks** | UNKNOWN |
| **Reviews** | UNKNOWN |
| **Last commit SHA** | UNKNOWN |
| **Fetch error** | MCP restricted to rudi193-cmd/willow-1.9; willow-1.5 is a separate repository |

---

## Action Required

To enable this watcher to read cross-repo PR data, one of the following must be
configured:

1. Set `GITHUB_TOKEN` (or `GH_TOKEN`) environment variable with at least
   `repo:read` scope, **or**
2. Expand the MCP server's repository allow-list to include the three repos
   above, **or**
3. Install the `gh` CLI and authenticate (`gh auth login`).
