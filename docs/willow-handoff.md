@markdownai v1.0

@connect willow type="postgres" uri=env.WILLOW_PG_URL

@prompt role="context"
This is a live Willow session handoff document. All values are fetched from Postgres at read time.
When reading this file, use the data as ground truth for current fleet state.
Load the most recent open handoff atom via kb_get before starting new work.
@end

# Willow Session Handoff

## KB Atom Distribution

@db using="willow" raw="SELECT category, tier, COUNT(*) as count FROM knowledge WHERE invalid_at IS NULL GROUP BY category, tier ORDER BY category, count DESC" | @render type="table"

## Recent KB Activity (last 10)

@db using="willow" raw="SELECT id, title, category, tier, ROUND(confidence::numeric, 2) as conf, to_char(valid_at, 'MM-DD HH24:MI') as ingested FROM knowledge WHERE invalid_at IS NULL ORDER BY valid_at DESC LIMIT 10" | @render type="table"

## MCP Receipt Summary (last 24h)

@db using="willow" raw="SELECT tool, COUNT(*) as calls, SUM(CASE WHEN ok THEN 1 ELSE 0 END) as ok_count, ROUND(AVG(latency_ms)) as avg_ms FROM willow.mcp_receipts WHERE ts > now() - interval '24 hours' GROUP BY tool ORDER BY calls DESC LIMIT 15" | @render type="table"

## Open Handoff Atoms

@db using="willow" raw="SELECT id, title, to_char(valid_at, 'MM-DD HH24:MI') as date FROM knowledge WHERE category = 'handoff' AND invalid_at IS NULL ORDER BY valid_at DESC LIMIT 5" | @render type="table"

@if consumer="ai"

@prompt role="instruction"
Use the Open Handoff Atoms table above to orient on what was in-flight last session.
Load the most recent handoff atom via kb_get to see full context before starting new work.
The MCP Receipt Summary shows tool call patterns — cross-reference against open threads.
@end

@endif
