"""
fylgja/handoff_flat.py — Flat file handoff writer and reader.
b17: 932BE  ΔΣ=42

Writes a verifiable flat file at session end. Read and verified at session start.
The file is ground truth the next session can cross-check — not trusted prose.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


_HANDOFF_ROOT = Path.home() / ".willow" / "handoffs"


def _find_jsonl(session_id: str) -> tuple[Path | None, str]:
    """
    Return (path, runtime_label) for the session JSONL if found.

    Claude Code CLI sessions typically live under ~/.claude/projects.
    Cursor sessions typically live under ~/.cursor/projects/*/agent-transcripts.
    """
    candidates: list[tuple[Path, str]] = [
        (Path.home() / ".claude" / "projects", "claude-code"),
        (Path.home() / ".cursor" / "projects", "cursor"),
    ]
    for root, runtime in candidates:
        try:
            if not root.exists():
                continue
            files = list(root.rglob(f"{session_id}.jsonl"))
            if files:
                return files[0], runtime
        except Exception:
            continue
    return None, "unknown"


def _extract_last_user_message(jsonl_path: Path) -> str:
    """Read JSONL tail, return last human text message."""
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("type") == "user" or entry.get("role") == "user":
                    content = entry.get("message", {}).get("content", "")
                    if isinstance(content, str) and content.strip():
                        return content.strip()[:200]
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "").strip()
                                if text:
                                    return text[:200]
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _get_open_gates(agent: str) -> list[str]:
    """Query SOIL for open flags/gaps. Returns list of title strings."""
    gates: list[str] = []
    try:
        from willow.fylgja._mcp import call
        for collection in (f"{agent}/flags", f"{agent}/gaps/store"):
            try:
                records = call("store_list", {"app_id": agent, "collection": collection}, timeout=5)
                if isinstance(records, list):
                    for r in records:
                        if r.get("flag_state") == "open" or r.get("status") == "open":
                            gates.append(r.get("title", r.get("id", "?"))[:80])
            except Exception:
                continue
    except Exception:
        pass
    return gates[:10]


def write_flat_handoff(session_id: str, agent: str) -> Path | None:
    """Write a flat verifiable handoff file. Returns path written or None on failure."""
    try:
        agent_dir = _HANDOFF_ROOT / agent
        agent_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = agent_dir / f"session_handoff-{today}.md"

        jsonl_path, runtime = _find_jsonl(session_id)
        anchor = _extract_last_user_message(jsonl_path) if jsonl_path else ""
        gates = _get_open_gates(agent)

        lines = [
            f"# Handoff — {agent} — {today}",
            f"written_at: {datetime.now(timezone.utc).isoformat()}",
            f"runtime: {runtime}",
            "",
        ]

        if anchor:
            lines += [
                "## Last real message",
                f'"{anchor}"',
                "# next session: grep JSONL for this string to verify handoff is honest",
                "",
            ]

        if jsonl_path:
            lines += [
                "## JSONL",
                str(jsonl_path),
                "",
            ]

        if gates:
            lines += ["## Open gates"]
            for g in gates:
                lines.append(f"- {g}")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    except Exception:
        return None


def read_flat_handoff(agent: str) -> dict:
    """Read most recent flat handoff for agent. Returns parsed dict."""
    result: dict = {
        "anchor": "", "jsonl_path": "", "open_gates": [],
        "written_at": "", "runtime": "", "path": "",
    }
    try:
        agent_dir = _HANDOFF_ROOT / agent
        # New location: ~/.willow/handoffs/{agent}/session_handoff-*.md
        # Backward compat: ~/.willow/handoffs/{agent}-*.md
        new_files = sorted(agent_dir.glob("session_handoff-*.md"), reverse=True) if agent_dir.exists() else []
        old_files = sorted(_HANDOFF_ROOT.glob(f"{agent}-*.md"), reverse=True)
        files = new_files or old_files
        if not files:
            return result
        result["path"] = str(files[0])
        text = files[0].read_text(encoding="utf-8")
        lines = text.splitlines()
        in_gates = False
        for i, line in enumerate(lines):
            if line.startswith("written_at:"):
                result["written_at"] = line.split(":", 1)[1].strip()
            elif line.startswith("runtime:"):
                result["runtime"] = line.split(":", 1)[1].strip()
            elif line == "## Last real message" and i + 1 < len(lines):
                result["anchor"] = lines[i + 1].strip().strip('"')
            elif line == "## JSONL" and i + 1 < len(lines):
                result["jsonl_path"] = lines[i + 1].strip()
            elif line == "## Open gates":
                in_gates = True
            elif in_gates and line.startswith("- "):
                result["open_gates"].append(line[2:])
            elif in_gates and line.strip() and not line.startswith("- "):
                in_gates = False
    except Exception:
        pass
    return result


def verify_anchor(anchor: str, jsonl_path: str) -> bool:
    """Return True if anchor string appears in the JSONL file."""
    if not anchor or not jsonl_path:
        return False
    try:
        path = Path(jsonl_path)
        if not path.exists():
            return False
        return anchor[:80] in path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
