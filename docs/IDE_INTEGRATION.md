# IDE Integration — SAP MCP Server HTTP Transport

The SAP MCP Server can run in HTTP (SSE) mode to enable IDE clients to connect without Claude Code CLI.

## Running SAP MCP in HTTP Mode

### Manual startup
```bash
python3 sap/sap_mcp.py --http
```

Server starts at `http://127.0.0.1:6274/sse` by default.

### Systemd (automatic at login)
```bash
systemctl --user enable willow-mcp.service
systemctl --user start willow-mcp.service
```

Check status:
```bash
systemctl --user status willow-mcp.service
```

## VS Code + Continue.dev

1. Install [Continue](https://www.continue.dev/) extension for VS Code
2. Open VS Code settings (Cmd+,) and find "Continue: Config"
3. Edit your `~/.continue/config.json`:

```json
{
  "models": [...],
  "contextProviders": [
    {
      "name": "willow",
      "params": {
        "serverUrl": "http://localhost:6274/sse"
      }
    }
  ]
}
```

4. Continue will fetch context from Willow's MCP tools

## VS Code Copilot MCP Preview

VS Code's Copilot MCP feature (preview) requires local configuration.

1. Create `.vscode/mcp.json` in your workspace:

```json
{
  "mcpServers": {
    "willow": {
      "command": "sse",
      "url": "http://localhost:6274/sse"
    }
  }
}
```

2. Copilot will connect to Willow for tool use

## JetBrains IDEs (IntelliJ, PyCharm, WebStorm, etc.)

JetBrains has an [MCP plugin](https://plugins.jetbrains.com/plugin/MCP) available:

1. Install the "MCP Client" plugin from JetBrains Marketplace
2. Go to Settings → Tools → MCP Client
3. Add new server:
   - **Name:** Willow
   - **Type:** HTTP/SSE
   - **URL:** `http://localhost:6274/sse`

4. Save and the IDE will connect

## Cursor

Cursor already supports stdio MCP by default (via Claude Code). To use HTTP transport instead:

1. Edit `~/.cursor/settings.json`:

```json
{
  "mcpServers": {
    "willow": {
      "type": "sse",
      "url": "http://localhost:6274/sse"
    }
  }
}
```

2. Cursor will use HTTP instead of stdio

## Customizing Host and Port

By default, the server listens on `127.0.0.1:6274`. To change:

```bash
python3 sap/sap_mcp.py --http --host 0.0.0.0 --port 5000
```

**Note:** Exposing to `0.0.0.0` makes the server public — use only on private networks.

For systemd, edit `willow-mcp.service` and change ExecStart:
```
ExecStart=%h/willow-1.9/.venv-dev/bin/python3 %h/willow-1.9/sap/sap_mcp.py --http --port 5000
```

## Troubleshooting

**Connection refused:**
```bash
curl -s http://localhost:6274/sse
```
If it fails, check if willow-mcp is running:
```bash
systemctl --user status willow-mcp.service
```

**Port already in use:**
```bash
lsof -i :6274  # find process holding port
```

**IDE can't connect:**
- Check firewall allows localhost:6274
- Verify SAP MCP server is running (`ps aux | grep sap_mcp`)
- Check logs: `journalctl --user -u willow-mcp.service -n 50 -f`

## Architecture

- **Transport:** Server-Sent Events (SSE) over HTTP
- **Framework:** Starlette (async ASGI)
- **Server:** uvicorn
- **MCP SDK:** Uses native `mcp.server.sse` transport
- **Default Endpoint:** `http://127.0.0.1:6274/sse`
- **Stdio mode** (default for Claude Code) unaffected by HTTP changes
