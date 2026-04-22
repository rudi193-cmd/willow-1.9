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
    if session_id:
        _register_jeles(session_id)

    lines = ["[INDEX] " + " · ".join(summary)]
    for a in alerts:
        lines.append(f"  ⚠ {a}")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
