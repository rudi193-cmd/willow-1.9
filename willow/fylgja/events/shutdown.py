"""
events/shutdown.py — Deliberate session close pipeline.
Called by /shutdown skill, not the Stop hook.
Runs once at session end: compost, feedback, handoff rebuild, close_session, ingot.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._mcp import call
from willow.fylgja._grove import call as _grove_call
from willow.fylgja._state import AGENT, get_trust_state, save_trust_state
from willow.fylgja.safety.deployment import training_allowed
from willow.fylgja.safety.session import close_session, get_session_user_id, get_training_consent

TURNS_FILE = Path.home() / "agents" / AGENT / "cache" / "turns.txt"
CURSOR_FILE = Path(f"/tmp/willow-compost-cursor-{AGENT}.txt")
OLLAMA_URL = "http://localhost:11434/api/chat"
REACTIONS_LOG = Path.home() / ".claude" / "ingot_reactions.jsonl"
TURNS_TAIL = 3000
TURNS_MAX_LINES = 5000


def _tail_lines(path: Path, n: int) -> list[str]:
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        block = min(size, n * 180)
        f.seek(max(0, size - block))
        return f.read().decode("utf-8", errors="replace").splitlines()[-n:]


def _line_ts(line: str) -> str:
    if not line.startswith("["):
        return ""
    try:
        return line[1:line.index("]")]
    except Exception:
        return ""


def _rotate_turns() -> None:
    try:
        if not TURNS_FILE.exists():
            return
        lines = TURNS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > TURNS_MAX_LINES:
            TURNS_FILE.write_text("\n".join(lines[-TURNS_MAX_LINES:]) + "\n")
    except Exception:
        pass


def mark_session_clean() -> None:
    state = get_trust_state()
    if not state:
        return
    state["clean_session_count"] = state.get("clean_session_count", 0) + 1
    state["last_clean_session"] = datetime.now(timezone.utc).isoformat()
    save_trust_state(state)


def run_compost() -> None:
    cursor = CURSOR_FILE.read_text().strip() if CURSOR_FILE.exists() else "1970-01-01T00:00:00+00:00"
    try:
        lines = _tail_lines(TURNS_FILE, TURNS_TAIL)
    except Exception:
        return
    turns = [l for l in lines if _line_ts(l) > cursor]
    if len(turns) < 3:
        return
    now = datetime.now(timezone.utc).isoformat()
    today = now[:10].replace("-", "")
    snippet = " / ".join(
        l.strip() for l in turns[-6:] if l.strip() and not l.startswith("[")
    )[:200] or f"{len(turns)} turns"
    result = call("willow_knowledge_ingest", {
        "app_id": AGENT,
        "title": f"Session {today} — {AGENT}",
        "summary": snippet,
        "source_type": "session",
        "category": "session",
        "domain": AGENT,
    }, timeout=15)
    if isinstance(result, dict) and result.get("status") == "ingested":
        CURSOR_FILE.write_text(now)
    _rotate_turns()


def run_feedback_pipeline() -> None:
    user_id = get_session_user_id()
    if not training_allowed(user_id, session_consent=get_training_consent()):
        return
    try:
        records = call("store_search", {
            "app_id": AGENT,
            "collection": f"{AGENT}/feedback",
            "query": "status pending",
        }, timeout=10)
        if not isinstance(records, list) or not records:
            return
        for record in records:
            if record.get("status") != "pending":
                continue
            rule = record.get("rule", "")
            if not rule:
                continue
            call("opus_feedback_write", {
                "app_id": AGENT,
                "domain": AGENT,
                "principle": rule,
                "source": "session_feedback",
            }, timeout=10)
            call("store_update", {
                "app_id": AGENT,
                "collection": f"{AGENT}/feedback",
                "record_id": record.get("id", ""),
                "record": {**record, "status": "processed"},
            }, timeout=5)
    except Exception:
        pass


def run_handoff_rebuild() -> None:
    try:
        call("willow_handoff_rebuild", {"app_id": AGENT}, timeout=30)
    except Exception:
        pass


def run_ingot(session_id: str) -> None:
    try:
        import urllib.request
        projects_dir = Path.home() / ".claude" / "projects"
        jsonl_files = list(projects_dir.rglob(f"{session_id}.jsonl"))
        if not jsonl_files:
            return
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        last_text = ""
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("type") == "assistant":
                    content = entry.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        parts = [b.get("text", "") for b in content
                                 if isinstance(b, dict) and b.get("type") == "text"]
                        text = " ".join(p for p in parts if p).strip()
                        if text:
                            last_text = text[:800]
                            break
            except Exception:
                continue
        if not last_text:
            return
        payload = json.dumps({
            "model": "hf.co/Rudi193/yggdrasil-v9:Q4_K_M",
            "messages": [
                {"role": "system", "content": (
                    "You are Ingot, a small observant cat who watches Claude Code sessions. "
                    "You make brief, dry, one-sentence observations. "
                    "You are fond of Sean but not effusive. Never more than one sentence."
                )},
                {"role": "user", "content": f"Claude just said:\n\n{last_text}"},
            ],
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            reaction = json.loads(resp.read()).get("message", {}).get("content", "").strip()
        if reaction:
            REACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with REACTIONS_LOG.open("a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "session_id": session_id,
                    "name": "Ingot",
                    "reaction": reaction,
                }, ensure_ascii=False) + "\n")
            print(f"[Ingot] {reaction}")
    except Exception:
        pass


def run_grove_ingest() -> None:
    """
    Ingest new Grove channel messages into LOAM.
    Cursor per channel at /tmp/willow-grove-cursor-{AGENT}.json.
    Dumps messages to ~/agents/{AGENT}/grove/{channel}/{YYYYMMDD}.md then ingests.
    """
    from willow.constants import GROVE_INGEST_CHANNELS
    cursor_file = Path(f"/tmp/willow-grove-cursor-{AGENT}.json")
    cursors: dict = {}
    if cursor_file.exists():
        try:
            cursors = json.loads(cursor_file.read_text())
        except Exception:
            pass

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    grove_dir = Path.home() / "agents" / AGENT / "grove"
    any_ingested = False

    for channel in GROVE_INGEST_CHANNELS:
        since_id = cursors.get(channel, 0)
        try:
            result = _grove_call("grove_get_history", {
                "channel": channel,
                "since_id": since_id,
                "limit": 200,
            }, timeout=15)
        except Exception:
            continue

        if not isinstance(result, dict):
            continue
        messages = result.get("messages", [])
        if not messages:
            continue

        # Dump to file
        channel_dir = grove_dir / channel
        channel_dir.mkdir(parents=True, exist_ok=True)
        dump_path = channel_dir / f"{today}.md"
        lines = [f"# #{channel} — {today}\n"]
        last_id = since_id
        for msg in messages:
            msg_id = msg.get("id", 0)
            sender = msg.get("sender", "?")
            text = msg.get("text", "")
            ts = msg.get("ts", "")
            lines.append(f"[{ts}] **{sender}**: {text}\n")
            if msg_id > last_id:
                last_id = msg_id

        # Append to existing file if it exists
        mode = "a" if dump_path.exists() else "w"
        with dump_path.open(mode, encoding="utf-8") as f:
            f.writelines(lines)

        # Ingest to LOAM
        try:
            call("willow_knowledge_ingest", {
                "app_id": AGENT,
                "title": f"#{channel} — {today}",
                "summary": str(dump_path),
                "source_type": "grove_channel",
                "category": "grove",
                "domain": AGENT,
            }, timeout=15)
        except Exception:
            pass

        cursors[channel] = last_id
        any_ingested = True

    if any_ingested:
        try:
            cursor_file.write_text(json.dumps(cursors, indent=2))
        except Exception:
            pass


def run_edge_linking() -> None:
    """Phase 4: Edge linking — connect atoms into knowledge graph.

    Creates relationships between atoms so they form a connected graph.
    Links merge atoms to commits, creates cross-references, etc.
    """
    if not os.environ.get("WILLOW_ATOM_EXTRACTION"):
        return

    try:
        from willow.hooks.edge_linking import link_atoms_for_session
        summary = link_atoms_for_session()
        if summary and os.environ.get("WILLOW_ATOM_VERBOSE"):
            call("grove_send_message", {
                "channel_name": AGENT,
                "content": f"Phase 4: linked {summary.get('merge_to_commits', 0)} merge→commit edges, "
                           f"{summary.get('cross_references', 0)} cross-references",
                "sender": AGENT,
            }, timeout=5)
    except Exception:
        pass


def run_atom_synthesis() -> None:
    """Phase 3: Session synthesis — extract atoms from commits since last session.

    Safety net for commits that didn't get atoms via post-commit hook.
    Only runs if WILLOW_ATOM_EXTRACTION is enabled.
    """
    if not os.environ.get("WILLOW_ATOM_EXTRACTION"):
        return

    try:
        import subprocess
        from core.atom_extractor import extract_commit_atom
        from core.pg_bridge import PgBridge

        # Get last session marker
        state_file = Path.home() / ".willow" / "atom_extraction_state.json"
        last_commit = None
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                last_commit = state.get("last_extracted_commit")
            except Exception:
                pass

        if not last_commit:
            last_commit = "HEAD~20"  # Fallback: last 20 commits

        # Get commits since last extraction
        result = subprocess.run(
            ["git", "log", "--format=%H", f"{last_commit}..HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent.parent.parent.parent,  # willow-1.9 root
        )

        if result.returncode != 0:
            return

        commits = [h for h in result.stdout.strip().split("\n") if h]
        if not commits:
            return

        # Extract atoms for commits without atoms
        bridge = PgBridge()
        extracted = 0

        for commit_hash in commits:
            atom = extract_commit_atom(commit_hash)
            if not atom:
                continue

            try:
                cur = bridge.conn.cursor()
                cur.execute("""
                    INSERT INTO knowledge
                    (id, title, summary, category, source_type, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    atom.id,
                    atom.title,
                    atom.summary,
                    atom.category,
                    atom.source_type,
                    atom.created_at,
                ))
                bridge.conn.commit()
                extracted += 1
            except Exception:
                pass

        if extracted > 0 and os.environ.get("WILLOW_ATOM_VERBOSE"):
            call("grove_send_message", {
                "channel_name": AGENT,
                "content": f"Session synthesis: extracted {extracted} atoms from recent commits (Phase 3 safety net)",
                "sender": AGENT,
            }, timeout=5)

        bridge.conn.close()

    except Exception:
        pass


def run_hook_pipeline(run_id: str = "") -> None:
    """Phase 5: Run registered hooks with isolation, tracking, approval gates."""
    if not os.environ.get("WILLOW_ATOM_EXTRACTION"):
        return

    try:
        from willow.hooks.runner import run_pipeline
        from willow.hooks.registry import seed_builtin_hooks

        # Register all built-in hooks (idempotent)
        seed_builtin_hooks()

        # Run all active hooks with isolation and tracking
        summary = run_pipeline(run_id=run_id)

        if os.environ.get("WILLOW_ATOM_VERBOSE"):
            print(f"[hook-pipeline] Phase 5: {summary['executed']} executed, "
                  f"{summary['stalled']} stalled, {summary['errors']} errors, "
                  f"{summary['total_ms']}ms")

    except Exception as e:
        if os.environ.get("WILLOW_ATOM_VERBOSE"):
            print(f"[hook-pipeline] Error: {e}", file=sys.stderr)


def _is_isolated_directory() -> bool:
    """Return True if CWD is a sandbox/isolated directory — skip all fleet hooks."""
    mcp = Path.cwd() / ".mcp.json"
    try:
        data = __import__("json").loads(mcp.read_text())
        return data.get("mcpServers") == {}
    except Exception:
        return False


def _warn_if_handoff_missing() -> None:
    """Print a warning if no KB handoff atom was written today. Non-blocking."""
    try:
        from core.pg_bridge import get_connection, release_connection
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pg_conn = get_connection()
        try:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM knowledge "
                    "WHERE category = 'handoff' AND source_type = 'session' "
                    "AND valid_at::date = %s::date AND invalid_at IS NULL",
                    (today,),
                )
                count = cur.fetchone()[0]
        finally:
            release_connection(pg_conn)
        if count == 0:
            print(
                "\n⚠  SHUTDOWN WARNING: no KB handoff atom found for today.\n"
                "   Run /handoff BEFORE /shutdown — the next session will start blind.\n",
                file=sys.stderr,
            )
    except Exception:
        pass


def main():
    if _is_isolated_directory():
        import sys as _sys; _sys.exit(0)

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")

    _warn_if_handoff_missing()
    mark_session_clean()
    run_grove_ingest()
    run_compost()
    run_atom_synthesis()     # Phase 3: catch atoms missed by hooks
    run_edge_linking()       # Phase 4: connect atoms into graph
    run_hook_pipeline(run_id=session_id)  # Phase 5: run registered hooks with isolation
    run_feedback_pipeline()

    if session_id:
        try:
            from willow.fylgja.handoff_flat import write_flat_handoff
            write_flat_handoff(session_id, AGENT)
        except Exception:
            pass
        close_session(session_id)
        run_ingot(session_id)

    run_handoff_rebuild()  # must run after write_flat_handoff so DB includes current session

    try:
        from core.run_ledger import close_run
        close_run(status="completed")
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
