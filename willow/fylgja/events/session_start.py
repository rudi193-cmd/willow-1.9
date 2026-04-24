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


def _run_silent_startup() -> dict:
    """
    Silent startup — runs before the first prompt regardless of what the user says.
    Returns a dict with handoff summary, open flags, and postgres state.
    Writes session_anchor.json and resets anchor_state.json.
    """
    anchor_dir = Path.home() / ".willow"
    anchor_file = anchor_dir / "session_anchor.json"
    state_file = anchor_dir / "anchor_state.json"

    result = {"handoff_title": "", "handoff_summary": "", "open_flags": 0, "top_flags": [], "postgres": "unknown"}

    # Get latest handoff
    try:
        h = call("willow_handoff_latest", {"app_id": AGENT}, timeout=8)
        result["handoff_title"] = h.get("filename", "")
        summary = h.get("summary", "")
        result["handoff_summary"] = summary[:120] if summary else ""
    except Exception:
        pass

    # Check open flags
    try:
        flags = call("store_list", {"app_id": AGENT, "collection": "hanuman/flags"}, timeout=5)
        open_flags = [f for f in (flags or []) if f.get("flag_state") == "open"]
        result["open_flags"] = len(open_flags)
        result["top_flags"] = [f.get("title", "")[:60] for f in open_flags[:3]]
    except Exception:
        pass

    # Postgres state from already-run willow_status
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
    lines.append(f"[ANCHOR]")
    _fork_line = f"agent={AGENT}  postgres={startup['postgres']}"
    if startup.get("fork_id"):
        _fork_line += f"  fork={startup['fork_id']}"
    lines.append(_fork_line)
    if startup["handoff_title"]:
        lines.append(f"last handoff: {startup['handoff_title']}")
    lines.append(f"open flags: {startup['open_flags']}")
    if startup["handoff_summary"]:
        lines.append(startup["handoff_summary"])
    if startup["postgres"] == "unknown":
        lines.append("BOOT DEGRADED — invoke /startup before responding to anything.")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
