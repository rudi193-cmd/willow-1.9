"""
willow/flags.py — Live gap flagging.
b17: FLAG1  ΔΣ=42

Write flags to hanuman/flags without going through MCP.
Importable from hooks, shutdown, anywhere in the system.

Usage:
    from willow.flags import flag, clear_flag, list_flags

    flag("BOOT-SHOOT-IMPORTS",
         title="shoot.py has broken imports",
         bridge="root.py → shoot.py",
         gap="from seed import ... will crash",
         severity="major")

    clear_flag("BOOT-SHOOT-IMPORTS")
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.willow_store import WillowStore

_COLLECTION = "hanuman/flags"

_SEVERITY_DEVIATION = {
    "routine":     0.0,
    "significant": math.pi / 4,   # ~0.785
    "major":       math.pi / 2,   # ~1.571
    "reversal":    math.pi,        # ~3.142
}


def flag(
    flag_id: str,
    title: str,
    bridge: str,
    gap: str,
    severity: str = "significant",
    file: str = "",
) -> str:
    """Write or overwrite a flag. Returns the flag_id."""
    store = WillowStore()
    deviation = _SEVERITY_DEVIATION.get(severity, math.pi / 4)
    store.put(
        _COLLECTION,
        {
            "id":       flag_id,
            "title":    title,
            "bridge":   bridge,
            "gap":      gap,
            "severity": severity,
            "file":     file,
        },
        record_id=flag_id,
        deviation=deviation,
    )
    return flag_id


def clear_flag(flag_id: str) -> bool:
    """Remove a flag by ID. Returns True if it existed."""
    store = WillowStore()
    try:
        conn = store._conn(_COLLECTION)
        cur = conn.execute("DELETE FROM records WHERE id = ?", (flag_id,))
        conn.commit()
        conn.close()
        return cur.rowcount > 0
    except Exception:
        return False


def list_flags() -> list[dict]:
    """Return all active flags, sorted by severity (major first)."""
    import json
    store = WillowStore()
    try:
        conn = store._conn(_COLLECTION)
        rows = conn.execute("SELECT id, data FROM records ORDER BY created DESC").fetchall()
        conn.close()
        order = {"reversal": 0, "major": 1, "significant": 2, "routine": 3}
        flags = [{"id": r[0], **json.loads(r[1])} for r in rows]
        return sorted(flags, key=lambda f: order.get(f.get("severity", "routine"), 9))
    except Exception:
        return []


def flag_ids() -> set[str]:
    """Return just the set of active flag IDs."""
    return {f["id"] for f in list_flags()}
