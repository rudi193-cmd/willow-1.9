"""
nest_intake.py — Nest intake backend for MCP tools.
b17: B2DA2  ΔΣ=42

Called by sap_mcp.py for willow_nest_scan / willow_nest_queue / willow_nest_file.
Manages the review queue at ~/.willow/nest-queue.json.
"""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

NEST_DIRS = [
    Path.home() / "Desktop" / "Nest",
    Path.home() / "Ashokoa" / "Nest" / "processed",
]

QUEUE_FILE = Path.home() / ".willow" / "nest-queue.json"

TRACK_TO_DEST = {
    # Sean's files — ~/personal/
    "journal":         Path.home() / "personal" / "journal",
    "legal":           Path.home() / "personal" / "legal",
    "knowledge":       Path.home() / "personal" / "knowledge",
    "narrative":       Path.home() / "personal" / "writing",
    "photos_personal": Path.home() / "personal" / "photos" / "personal",
    "photos_camera":   Path.home() / "personal" / "photos" / "camera",
    "screenshots":     Path.home() / "personal" / "photos" / "screenshots",
    # Agent artifacts — ~/Ashokoa/
    "handoffs":        Path.home() / "Ashokoa" / "Filed" / "reference" / "handoffs",
    "specs":           Path.home() / "Ashokoa" / "Filed" / "specs",
}


def _classify(filename: str) -> str | None:
    """Inline classifier — mirrors classify.py without import dependency."""
    import re
    n = filename.lower()
    ext = Path(filename).suffix.lower()

    if re.match(r"^\d{4}-\d{2}-\d{2}\.md$", filename):
        return "journal"

    legal = ["earnings_statement", "form_b", "debtor", "bankruptcy", "loa_extension",
             "physical therapy", "work status report", "healthcare and workers",
             "debtorcc", "approved leave", "return to work", "notice leave",
             "adobe scan", "3dkxz"]
    if any(k in n for k in legal):
        return "legal"

    handoffs = ["session_handoff", "handoff_", "master_handoff"]
    if any(k in n for k in handoffs):
        return "handoffs"

    knowledge = ["knowledge_extraction", "campbell_sean_knowledge", "aionic_record"]
    if any(k in n for k in knowledge):
        return "knowledge"

    specs = ["architecture", "utety", "willow", "working_paper", "llmphysics",
             "world_bible", "oakenscroll", "readme", "changelog", "specs"]
    if any(k in n for k in specs):
        return "specs"

    narrative = ["regarding jane", "chapter", "dispatch", "gerald", "professor",
                 "author's note", "books of mann"]
    if any(k in n for k in narrative):
        return "narrative"

    if ext in (".jpg", ".jpeg", ".png"):
        if any(k in n for k in ["feeld", "facebook", "messages"]):
            return "photos_personal"
        if re.match(r"^\d{8}_\d{6}|^\d{13}\.", filename):
            return "photos_camera"
        return "screenshots"

    return None


def _load_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    return json.loads(QUEUE_FILE.read_text())


def _save_queue(queue: list[dict]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, default=str))


def _unique_dest(dest_dir: Path, filename: str) -> Path:
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{i}{suffix}"
        i += 1
    return dest


def scan_nest() -> list[dict]:
    """Scan drop zones, classify new files, stage in queue. Returns newly staged items."""
    queue = _load_queue()
    existing_paths = {item["src"] for item in queue if item["status"] == "pending"}
    newly_staged = []

    for nest_dir in NEST_DIRS:
        if not nest_dir.exists():
            continue
        for f in sorted(nest_dir.iterdir()):
            if not f.is_file() or f.name.startswith("."):
                continue
            src = str(f)
            if src in existing_paths:
                continue
            track = _classify(f.name)
            dest_dir = TRACK_TO_DEST.get(track) if track else None
            proposed = str(_unique_dest(dest_dir, f.name)) if dest_dir else None
            item = {
                "id": len(queue) + len(newly_staged) + 1,
                "src": src,
                "filename": f.name,
                "track": track or "unknown",
                "proposed_dest": proposed,
                "status": "pending",
                "staged_at": datetime.now(timezone.utc).isoformat(),
            }
            newly_staged.append(item)

    if newly_staged:
        queue.extend(newly_staged)
        _save_queue(queue)

    return newly_staged


def get_queue() -> list[dict]:
    return [item for item in _load_queue() if item["status"] == "pending"]


def confirm_review(item_id: int, override_dest: str | None = None) -> dict:
    queue = _load_queue()
    item = next((i for i in queue if i["id"] == item_id), None)
    if not item:
        return {"error": f"item {item_id} not found"}

    src = Path(item["src"])
    if not src.exists():
        item["status"] = "error"
        item["error"] = "source file missing"
        _save_queue(queue)
        return {"error": f"source file missing: {src}"}

    dest = Path(override_dest) if override_dest else (
        Path(item["proposed_dest"]) if item["proposed_dest"] else None
    )
    if not dest:
        return {"error": "no destination — track unknown, use override_dest"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    final_dest = _unique_dest(dest.parent, dest.name)
    shutil.move(str(src), str(final_dest))

    item["status"] = "confirmed"
    item["final_dest"] = str(final_dest)
    item["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    _save_queue(queue)

    return {
        "status": "confirmed",
        "item_id": item_id,
        "filename": item["filename"],
        "track": item["track"],
        "moved_to": str(final_dest),
    }


def skip_item(item_id: int) -> dict:
    queue = _load_queue()
    item = next((i for i in queue if i["id"] == item_id), None)
    if not item:
        return {"error": f"item {item_id} not found"}
    item["status"] = "skipped"
    item["skipped_at"] = datetime.now(timezone.utc).isoformat()
    _save_queue(queue)
    return {"status": "skipped", "item_id": item_id, "filename": item["filename"]}
