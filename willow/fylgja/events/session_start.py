"""
events/session_start.py — SessionStart hook handler.
Hardware state, willow_status, JELES registration.
Outputs additionalContext JSON.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from willow.fylgja._mcp import call
from willow.fylgja._grove import call as _grove_call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
INDEX_DIR = Path.home() / "agents" / AGENT / "index"
THREAD_FILE = Path("/tmp/willow-context-thread.json")


def _clear_stale_thread():
    try:
        if THREAD_FILE.exists():
            THREAD_FILE.unlink()
    except Exception:
        pass


def _scan_hardware() -> tuple[list[str], list[str]]:
    summary, alerts = [], []
    try:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,FSTYPE,SIZE,MOUNTPOINT,LABEL,TYPE"],
            capture_output=True, text=True, timeout=5
        )
        hw = json.loads(r.stdout) if r.returncode == 0 else {}
        ntfs_unmounted = []

        def _gb(s):
            s = (s or "").upper()
            if s.endswith("G"): return float(s[:-1])
            if s.endswith("T"): return float(s[:-1]) * 1024
            return 0

        def _walk(devices):
            for d in devices:
                if d.get("fstype") == "ntfs" and not d.get("mountpoint"):
                    if _gb(d.get("size", "0")) >= 10:
                        ntfs_unmounted.append(d["name"])
                if d.get("children"):
                    _walk(d["children"])

        _walk(hw.get("blockdevices", []))
        if ntfs_unmounted:
            alerts.append(f"NTFS unmounted: {', '.join(ntfs_unmounted)}")
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        (INDEX_DIR / "hardware.json").write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "lsblk": hw, "ntfs_unmounted": ntfs_unmounted,
        }, indent=2))
        summary.append("drives")
    except Exception as e:
        alerts.append(f"hardware: {e}")

    try:
        zones = []
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            try:
                temp = int((zone / "temp").read_text().strip()) / 1000
                type_ = (zone / "type").read_text().strip()
                zones.append({"zone": zone.name, "type": type_, "temp_c": round(temp, 1)})
                if temp > 85:
                    alerts.append(f"HIGH TEMP: {type_} {temp}°C")
            except Exception:
                pass
        if zones:
            peak = max(z["temp_c"] for z in zones)
            summary.append(f"{peak}°C")
            (INDEX_DIR / "thermals.json").write_text(json.dumps({
                "timestamp": datetime.now().isoformat(), "zones": zones
            }, indent=2))
    except Exception as e:
        alerts.append(f"thermals: {e}")

    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k.strip() in ("MemTotal", "MemAvailable"):
                mem[k.strip()] = v.strip()
        if "MemAvailable" in mem and "MemTotal" in mem:
            avail = int(mem["MemAvailable"].split()[0])
            total = int(mem["MemTotal"].split()[0])
            summary.append(f"{round(avail/total*100)}% RAM free")
        (INDEX_DIR / "memory.json").write_text(json.dumps({
            "timestamp": datetime.now().isoformat(), **mem
        }, indent=2))
    except Exception as e:
        alerts.append(f"memory: {e}")

    return summary, alerts


def _check_willow_status() -> str:
    try:
        result = call("willow_status", {"app_id": AGENT}, timeout=5)
        pg = result.get("postgres", "unknown")
        if isinstance(pg, dict):
            return "postgres=up"
        return f"postgres={pg}"
    except Exception:
        return "postgres=unknown"


def _register_jeles(session_id: str) -> None:
    try:
        projects_dir = Path.home() / ".claude" / "projects"
        jsonl_files = list(projects_dir.rglob(f"{session_id}.jsonl"))
        if jsonl_files:
            call("willow_jeles_register", {
                "app_id": AGENT,
                "agent": AGENT,
                "jsonl_path": str(jsonl_files[0]),
                "session_id": session_id,
            }, timeout=10)
    except Exception:
        pass


DISPATCH_INBOX = Path(f"/tmp/willow-dispatch-inbox-{AGENT}.json")


def _subscribe_dispatch() -> int:
    """
    Pull #dispatch messages addressed to this agent since last cursor.
    Writes unread messages to DISPATCH_INBOX. Returns count of new messages.
    """
    cursor_file = Path(f"/tmp/willow-dispatch-cursor-{AGENT}.json")
    cursors: dict = {}
    if cursor_file.exists():
        try:
            cursors = json.loads(cursor_file.read_text())
        except Exception:
            pass
    since_id = cursors.get("dispatch", 0)
    try:
        result = _grove_call("grove_get_history", {
            "channel": "dispatch",
            "since_id": since_id,
            "limit": 50,
        }, timeout=8)
    except Exception:
        return 0

    if not isinstance(result, dict):
        return 0
    messages = result.get("messages", [])
    addressed = [
        m for m in messages
        if AGENT.lower() in m.get("content", "").lower()
        or m.get("to", "").lower() == AGENT.lower()
    ]
    last_id = max((m.get("id", 0) for m in messages), default=since_id)
    if last_id > since_id:
        cursors["dispatch"] = last_id
        try:
            cursor_file.write_text(json.dumps(cursors))
        except Exception:
            pass
    if addressed:
        try:
            DISPATCH_INBOX.write_text(json.dumps(addressed))
        except Exception:
            pass
    return len(addressed)


def _ensure_grove_mcp() -> str:
    """Start grove-mcp.service if not running. Returns status string."""
    import urllib.request
    grove_port = os.environ.get("GROVE_MCP_PORT", "8765")
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{grove_port}/mcp", timeout=1)
        return "grove=up"
    except Exception:
        pass
    # Not reachable — try systemctl start
    try:
        subprocess.run(
            ["systemctl", "--user", "start", "grove-mcp.service"],
            capture_output=True, timeout=5,
        )
        return "grove=starting"
    except Exception:
        return "grove=unavailable"


_SOURCE_MULTIPLIERS = {
    "user_statement": 2.0,
    "insight": 1.8,
    "chunk": 1.5,
    "reflection": 1.2,
    "observation": 1.0,
    "inference": 0.8,
}


def _position_order(atoms: list) -> list:
    """Sort ascending by composite score — worst first, best last (U-curve fix)."""
    def _score(a: dict) -> float:
        return (
            float(a.get("importance", 5))
            * float(a.get("weight", 1.0))
            * float(a.get("stability", 1.0))
            * _SOURCE_MULTIPLIERS.get(a.get("source", "observation"), 1.0)
        )
    return sorted(atoms, key=_score)


def _query_preference_atoms(atoms: list, limit: int = 10) -> list:
    """Query B — user_statement or insight atoms, ordered by importance desc."""
    filtered = [
        a for a in atoms
        if a.get("invalid_at") is None
        and (a.get("source") == "user_statement" or a.get("type") == "insight")
    ]
    filtered.sort(key=lambda a: float(a.get("importance", 5)), reverse=True)
    return filtered[:limit]


def _query_world_state_atoms(atoms: list, limit: int = 10) -> list:
    """Query C — chunk and insight atoms, valid only, ordered by next_review then weight."""
    filtered = [
        a for a in atoms
        if a.get("invalid_at") is None
        and a.get("type") in ("chunk", "insight")
    ]
    filtered.sort(key=lambda a: (
        a.get("next_review") or "9999",
        -float(a.get("weight", 1.0)),
    ))
    return filtered[:limit]


def _run_silent_startup() -> dict:
    """
    Silent startup — runs before the first prompt regardless of what the user says.
    Derives context from store queries (traces, gaps, promoted atoms) rather than
    the handoff narrative. Returns structured dict; writes session_anchor.json.
    """
    anchor_dir = Path.home() / ".willow"
    anchor_file = anchor_dir / "session_anchor.json"
    state_file = anchor_dir / "anchor_state.json"

    result = {
        "handoff_title": "",
        "handoff_summary": "",
        "open_flags": 0,
        "top_flags": [],
        "postgres": "unknown",
        "loaded_skills": [],
        "recent_traces": [],
        "open_gaps": [],
        "promoted_atoms": [],
        "next_bite": "",
    }

    # 1. Latest handoff — timestamp boundary only (not narrative)
    handoff_date = ""
    try:
        h = call("willow_handoff_latest", {"app_id": AGENT}, timeout=8)
        result["handoff_title"] = h.get("filename", "")
        handoff_date = h.get("session_date", h.get("created", ""))
    except Exception:
        pass

    # 2. Trace atoms since last handoff
    try:
        params: dict = {"app_id": AGENT, "collection": "hanuman/turns/store", "query": ""}
        if handoff_date:
            params["after"] = handoff_date
        traces = call("store_search", params, timeout=5)
        result["recent_traces"] = (traces or [])[:10]
    except Exception:
        pass

    # 3. Open gaps sorted by severity
    try:
        gaps = call("store_list", {"app_id": AGENT, "collection": "hanuman/gaps/store"}, timeout=5)
        open_gaps = sorted(
            [g for g in (gaps or []) if g.get("status") == "open"],
            key=lambda g: g.get("severity", 0),
            reverse=True,
        )
        result["open_gaps"] = open_gaps[:5]
        result["open_flags"] = len(open_gaps)
        result["top_flags"] = [g.get("title", "")[:60] for g in open_gaps[:3]]
    except Exception:
        try:
            flags = call("store_list", {"app_id": AGENT, "collection": "hanuman/flags"}, timeout=5)
            open_flags = [f for f in (flags or []) if f.get("flag_state") == "open"]
            result["open_flags"] = len(open_flags)
            result["top_flags"] = [f.get("title", "")[:60] for f in open_flags[:3]]
        except Exception:
            pass

    # Query B — preference atoms (user_statement + insights)
    # Query C — world state (chunks + insights)
    result["preference_atoms"] = []
    result["world_state_atoms"] = []
    try:
        all_atoms = call("store_list", {
            "app_id": AGENT,
            "collection": "hanuman/atoms/store",
        }, timeout=6) or []
        skills = call("store_list", {
            "app_id": AGENT,
            "collection": "hanuman/skills/store",
        }, timeout=5) or []

        result["preference_atoms"] = _position_order(_query_preference_atoms(all_atoms))
        result["world_state_atoms"] = _position_order(
            _query_world_state_atoms(all_atoms + skills)
        )

        # norn_pass review injection — atoms past their next_review date
        today = datetime.now().date().isoformat()
        due = [
            a for a in all_atoms
            if a.get("next_review") and a.get("next_review") <= today
            and a.get("invalid_at") is None
        ]
        if due:
            result["preference_atoms"] = due + result["preference_atoms"]
    except Exception:
        pass

    # 4. Promoted atoms (weight > 1.5 = frequently accessed historical context)
    try:
        promoted = call("willow_knowledge_search", {
            "app_id": AGENT,
            "query": "weight:>1.5",
            "limit": 5,
        }, timeout=5)
        result["promoted_atoms"] = (promoted or [])[:5]
    except Exception:
        pass

    # 5. Next bite from latest session composite
    try:
        sessions = call("store_list", {
            "app_id": AGENT,
            "collection": "hanuman/sessions/store",
        }, timeout=5)
        if sessions:
            latest = sorted(sessions, key=lambda s: s.get("date", ""), reverse=True)[0]
            result["next_bite"] = latest.get("next_bite", "")
    except Exception:
        pass

    # Derive handoff_summary from store data (not from handoff .md file)
    if result["next_bite"]:
        result["handoff_summary"] = result["next_bite"][:200]
    elif result["top_flags"]:
        result["handoff_summary"] = "Open: " + "; ".join(result["top_flags"])

    # Postgres state
    try:
        s = call("willow_status", {"app_id": AGENT}, timeout=5)
        result["postgres"] = "up" if isinstance(s.get("postgres"), dict) else "unknown"
    except Exception:
        pass

    # Auto-create session fork
    fork_id = ""
    try:
        fork_result = call("willow_fork_create", {
            "app_id": AGENT,
            "title": f"Session {datetime.now().strftime('%Y-%m-%d')} — {AGENT}",
            "created_by": AGENT,
            "topic": "session",
        }, timeout=5)
        fork_id = fork_result.get("fork_id", "") if isinstance(fork_result, dict) else ""
    except Exception:
        pass

    # Auto-load relevant skills (seeded from next_bite or top gap)
    loaded_skills = []
    try:
        skill_context = result["next_bite"] or result["handoff_summary"] or "session started"
        skill_result = call("willow_skill_load", {
            "app_id": AGENT,
            "context": skill_context[:100],
        }, timeout=5)
        loaded_skills = skill_result.get("skills", []) if isinstance(skill_result, dict) else []
        result["loaded_skills"] = loaded_skills
    except Exception:
        pass

    # Write anchor cache
    try:
        anchor_dir.mkdir(parents=True, exist_ok=True)
        anchor_file.write_text(json.dumps({
            "written_at": datetime.now().isoformat(),
            "agent": AGENT,
            "postgres": result["postgres"],
            "handoff_title": result["handoff_title"],
            "handoff_summary": result["handoff_summary"],
            "open_flags": result["open_flags"],
            "top_flags": result["top_flags"],
            "fork_id": fork_id,
            "trace_count": len(result["recent_traces"]),
            "promoted_count": len(result["promoted_atoms"]),
        }, indent=2))
        state_file.write_text(json.dumps({"prompt_count": 0}))
    except Exception:
        pass

    return result


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")
    _clear_stale_thread()
    summary, alerts = _scan_hardware()
    summary.append(_check_willow_status())
    summary.append(_ensure_grove_mcp())
    if session_id:
        _register_jeles(session_id)
    dispatch_count = _subscribe_dispatch()
    if dispatch_count:
        summary.append(f"dispatch={dispatch_count}")

    # Silent startup — runs always, regardless of first prompt
    startup = _run_silent_startup()

    lines = ["[INDEX] " + " · ".join(summary)]
    for a in alerts:
        lines.append(f"  ⚠ {a}")

    # Anchor context — always injected
    lines.append("[ANCHOR]")
    _fork_line = f"agent={AGENT}  postgres={startup['postgres']}"
    if startup.get("fork_id"):
        _fork_line += f"  fork={startup['fork_id']}"
    lines.append(_fork_line)
    if startup["handoff_title"]:
        lines.append(f"last handoff: {startup['handoff_title']}")
    # Recent traces (what happened since last handoff)
    traces = startup.get("recent_traces", [])
    if traces:
        trace_summaries = [t.get("summary", t.get("tool", "?"))[:60] for t in traces[:5]]
        lines.append(f"recent traces ({len(traces)}): " + " · ".join(trace_summaries))
    # Open gaps
    if startup["open_flags"]:
        lines.append(f"open gaps: {startup['open_flags']}")
        for flag in startup["top_flags"]:
            lines.append(f"  · {flag}")
    else:
        lines.append("open gaps: 0")
    # Promoted atoms (historical context worth surfacing)
    promoted = startup.get("promoted_atoms", [])
    if promoted:
        promoted_titles = [a.get("title", a.get("id", "?"))[:50] for a in promoted[:3]]
        lines.append("promoted atoms: " + " · ".join(promoted_titles))
    # World state (Query C) — background context
    world_state = startup.get("world_state_atoms", [])
    if world_state:
        ws_summaries = [a.get("summary", a.get("id", "?"))[:80] for a in world_state[-3:]]
        lines.append("WORLD STATE: " + " · ".join(ws_summaries))
    # Preference atoms (Query B) — how Sean wants things done
    prefs = startup.get("preference_atoms", [])
    if prefs:
        pref_summaries = [a.get("summary", a.get("id", "?"))[:80] for a in prefs[-5:]]
        lines.append("PREFERENCES: " + " · ".join(pref_summaries))
    # Next bite directive (from session composite, beats handoff narrative)
    if startup.get("next_bite"):
        lines.append(f"NEXT: {startup['next_bite']}")
    elif startup["handoff_summary"]:
        lines.append(startup["handoff_summary"])
    if startup["postgres"] == "unknown":
        lines.append("BOOT DEGRADED — invoke /startup before responding to anything.")
    if startup.get("loaded_skills"):
        skill_names = ", ".join(s["name"] for s in startup["loaded_skills"])
        lines.append(f"SKILLS LOADED: {skill_names}")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
