@markdownai v1.0

@connect willow type="postgres" uri=env.WILLOW_PG_URL

@prompt role="context"
This is a live Willow fleet monitor. All data is fetched from Postgres at read time.
Use this document to orient on fleet health, knowledge base state, and agent activity
before starting any fleet-wide operation or quorum proposal.
@end

# Willow Fleet Monitor

## Knowledge Base Health

@db using="willow" raw="SELECT category, tier, COUNT(*) as atoms, ROUND(AVG(confidence)::numeric, 2) as avg_conf FROM knowledge WHERE invalid_at IS NULL GROUP BY category, tier ORDER BY category, tier" | @render type="table"

## Recently Invalidated Atoms (last 48h)

@db using="willow" raw="SELECT id, title, category, to_char(invalid_at, 'MM-DD HH24:MI') as retired FROM knowledge WHERE invalid_at IS NOT NULL AND invalid_at > now() - interval '48 hours' ORDER BY invalid_at DESC LIMIT 10" | @render type="table"

## MCP Tool Activity (last 24h)

@db using="willow" raw="SELECT tool, COUNT(*) as calls, SUM(CASE WHEN ok THEN 1 ELSE 0 END) as ok, SUM(CASE WHEN NOT ok THEN 1 ELSE 0 END) as errors, ROUND(AVG(latency_ms)) as avg_ms, ROUND(MAX(latency_ms)) as max_ms FROM willow.mcp_receipts WHERE ts > now() - interval '24 hours' GROUP BY tool ORDER BY calls DESC LIMIT 20" | @render type="table"

## Recent Errors (last 24h)

@db using="willow" raw="SELECT ts::time::text as time, app_id, tool, error_type FROM willow.mcp_receipts WHERE ts > now() - interval '24 hours' AND NOT ok ORDER BY ts DESC LIMIT 10" | @render type="table"

## Governance History (open + recent)

@db using="willow" raw="SELECT id, title, tier, ROUND(confidence::numeric, 2) as conf, to_char(valid_at, 'MM-DD HH24:MI') as date, CASE WHEN invalid_at IS NULL THEN 'open' ELSE 'closed' END as status FROM knowledge WHERE category IN ('governance', 'handoff') ORDER BY valid_at DESC LIMIT 15" | @render type="table"

## KB Ingestion Rate (last 7 days, by day)

@db using="willow" raw="SELECT to_char(valid_at, 'MM-DD') as day, COUNT(*) as ingested, SUM(CASE WHEN invalid_at IS NOT NULL THEN 1 ELSE 0 END) as retired FROM knowledge WHERE valid_at > now() - interval '7 days' GROUP BY to_char(valid_at, 'MM-DD') ORDER BY day DESC" | @render type="table"

@if consumer="ai"

@prompt role="instruction"
Before any fleet-wide operation:
1. Check MCP Tool Activity for elevated error rates on critical tools (kb_ingest, soil_put, fleet_status).
2. Review Governance History for open handoff atoms — these may contain in-flight work.
3. If Recently Invalidated Atoms shows unexpected retirements, investigate before proceeding.
4. Error rate >10% on any tool = surface to user before continuing.
5. Load open handoff atoms via kb_get using their id before starting new work.
@end

@endif
