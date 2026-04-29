# Willow SAP — MCP Server

The SAP (Sovereign Application Protocol) MCP server. Exposes Willow's KB, store, Grove, and task queue to any MCP client.

## Connect

```json
{
  "mcpServers": {
    "willow": {
      "command": "python3",
      "args": ["/path/to/willow-1.9/sap/sap_mcp.py"]
    }
  }
}
```

The server sends orientation instructions in the `initialize` response — no tool call needed.

## First five tools

```
willow_status          → confirm system is up
willow_handoff_latest  → last session state
grove_get_history      → what the fleet has been doing
willow_knowledge_search → find existing knowledge before building
willow_task_submit     → queue work for Kart
```

Full onboarding: [ONBOARDING.md](ONBOARDING.md)
