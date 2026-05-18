-- MCP receipts v0 — 2026-05-18
-- Audit log of every tool call that passes the sap_gate.

CREATE SCHEMA IF NOT EXISTS willow;

CREATE TABLE IF NOT EXISTS willow.mcp_receipts (
    id          bigserial   PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    app_id      text        NOT NULL,
    tool        text        NOT NULL,
    ok          boolean     NOT NULL,
    latency_ms  integer,
    error_type  text
);

CREATE INDEX IF NOT EXISTS mcp_receipts_ts_idx     ON willow.mcp_receipts(ts DESC);
CREATE INDEX IF NOT EXISTS mcp_receipts_app_tool_idx ON willow.mcp_receipts(app_id, tool);
CREATE INDEX IF NOT EXISTS mcp_receipts_ok_idx     ON willow.mcp_receipts(ok) WHERE ok = false;
