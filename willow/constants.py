"""
constants.py — Willow system-wide constants.
b17: FE088  ΔΣ=42

Single source of truth for agent tiers, TTLs, dispatch channels, Grove ingest scope.
"""

# ── Agent tiers ───────────────────────────────────────────────────────────────

ENGINEER = {"hanuman", "heimdallr", "kart", "shiva", "ganesha", "opus"}
OPERATOR  = {"willow", "ada", "steve"}
WORKER    = {"hanz", "jeles", "pigeon", "riggs"}
WITNESS   = {"gerald"}

ALL_AGENTS = ENGINEER | OPERATOR | WORKER | WITNESS

# ── Agent TTL thresholds (seconds) ───────────────────────────────────────────

AGENT_RUNNING_TTL_S = 120    # last message < 2 min ago → RUNNING  → SendMessage
AGENT_IDLE_TTL_S    = 900    # last message < 15 min ago → IDLE    → RemoteTrigger
AGENT_STALE_TTL_S   = 3600   # last message < 1 hr ago  → STALE   → CronCreate

# ── Dispatch channels ─────────────────────────────────────────────────────────

CHANNEL_DISPATCH            = "dispatch"
CHANNEL_DISPATCH_ESCALATIONS = "dispatch-escalations"
CHANNEL_DISPATCH_VIOLATIONS  = "dispatch-violations"
CHANNEL_ARCHITECTURE        = "architecture"
CHANNEL_GENERAL             = "general"
CHANNEL_HANDOFFS            = "handoffs"

# ── Grove ingest scope (channels composted on /shutdown) ─────────────────────

GROVE_INGEST_CHANNELS = [
    CHANNEL_ARCHITECTURE,
    CHANNEL_GENERAL,
    CHANNEL_HANDOFFS,
    CHANNEL_DISPATCH,
    CHANNEL_DISPATCH_ESCALATIONS,
]

# ── Dispatch hard stops ───────────────────────────────────────────────────────

DISPATCH_MAX_DEPTH = 3       # depth > 3 → hard stop → post to #dispatch-violations

# ── Compact context TTL ───────────────────────────────────────────────────────

COMPACT_CONTEXT_TTL_S = 3600  # 1 hour
