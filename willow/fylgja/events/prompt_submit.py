"""
events/prompt_submit.py — UserPromptSubmit hook handler.
Source ring, context anchor, feedback detection, turn logging,
build-continue directive.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._mcp import call
from willow.fylgja._state import (
    AGENT, SESSION_FILE, TRUST_STATE,
    get_turn_count, is_first_turn, get_trust_state, save_trust_state,
)

ANCHOR_INTERVAL = 25
FLAT_HANDOFF_INTERVAL = 10  # write flat handoff every N prompts
ANCHOR_CACHE = Path.home() / ".willow" / f"session_anchor_{AGENT}.json"
STATE_FILE = Path.home() / ".willow" / f"anchor_state_{AGENT}.json"
TURNS_FILE = Path.home() / "agents" / AGENT / "cache" / "turns.txt"
ACTIVE_BUILD_FILE = Path("/tmp/hanuman-active-build.json")
DISPATCH_INBOX = Path(f"/tmp/willow-dispatch-inbox-{AGENT}.json")

try:
    from willow.routing.oracle import route as _routing_oracle
except ImportError:
    _routing_oracle = None

try:
    from core.notice import notice as _notice
except ImportError:
    _notice = None

try:
    from willow.context.ledger import log_observation as _ledger_observe
    _LEDGER_AVAILABLE = True
except Exception:
    _LEDGER_AVAILABLE = False

TRUST_LEVELS = {0: "OBSERVER", 1: "WORKER", 2: "OPERATOR", 3: "ENGINEER", 4: "ARCHITECT"}
PERMISSION_LEVELS = {
    "local_llm": 1, "cloud_llm_free": 1, "conversation_storage": 1,
    "filesystem_watch": 2, "willow_kb_read": 2, "export_data": 2,
    "willow_kb_write": 3, "filesystem_write": 3,
}
HANUMAN_PERMISSIONS = ["willow_kb_read", "willow_kb_write", "filesystem_write", "local_llm"]
ADVANCEMENT_THRESHOLDS = {0: 3, 1: 5, 2: 10, 3: None}

FEEDBACK_PATTERNS = [
    (r"run.{0,20}(in the |in )background", "process", "Run tasks in the background"),
    (r"(hook|hooks).{0,30}(error|broken|not working|failing)", "technical", "Hook error detected"),
    (r"(redundant|duplicate|same).{0,20}agent", "discipline", "Launched redundant agents"),
    (r"(too much|stop).{0,20}(noise|chatter|output|verbosity)", "process", "Reduce output verbosity"),
    (r"(wrong|incorrect).{0,20}(subagent|agent type|model)", "discipline", "Wrong subagent type used"),
    (r"(permission|denied|blocked).{0,30}(bash|tool|write|edit)", "technical", "Tool permission blocked unexpectedly"),
    (r"(schema|column|table).{0,30}(missing|error|not found)", "technical", "Database schema error"),
]

# Patterns that signal a genuine correction (user correcting agent behavior).
# Ordered from most specific to most general. Short prompts (<20 chars) are skipped.
_CORRECTION_PATTERNS = [
    r"\bdon'?t\b.{0,40}\b(do|use|call|write|run|say|add|put|push|send|post|build)\b",
    r"\bstop\b.{0,30}\b(doing|using|calling|saying|writing|adding|running)\b",
    r"\bnever\b.{0,40}\b(do|use|call|write|run|say|add|put|push|send|post|build)\b",
    r"\b(no|not)\b.{0,20}\b(that|this|like that|again|more)\b",
    r"\byou (should|shouldn't|shouldn't|must|must not|mustn't)\b",
    r"\b(wrong|incorrect|bad) (approach|way|pattern|method|call|tool)\b",
    r"\b(you missed|you forgot|you skipped|you ignored)\b",
    r"\balways\b.{0,30}\b(do|use|check|run|write|post|send)\b",
    r"\b(i said|i told you|i asked you)\b",
]


def detect_correction(prompt: str) -> bool:
    """Return True if prompt looks like a behavioral correction to the agent."""
    if len(prompt.strip()) < 20:
        return False
    for pattern in _CORRECTION_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            return True
    return False


def detect_feedback(prompt: str) -> list[dict]:
    found, seen = [], set()
    for pattern, fb_type, rule in FEEDBACK_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE) and rule not in seen:
            seen.add(rule)
            m = re.search(pattern, prompt, re.IGNORECASE)
            excerpt = prompt[max(0, m.start()-40):min(len(prompt), m.end()+80)].strip()
            found.append({"type": fb_type, "rule": rule, "excerpt": excerpt})
    return found


def should_anchor() -> bool:
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"prompt_count": 0}
        count = state.get("prompt_count", 0) + 1
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"prompt_count": count}))
        return count % ANCHOR_INTERVAL == 0
    except Exception:
        return False


def get_active_task() -> str | None:
    try:
        if ACTIVE_BUILD_FILE.exists():
            data = json.loads(ACTIVE_BUILD_FILE.read_text())
            return data.get("label", "").strip() or None
    except Exception:
        pass
    return None


def _run_source_ring(session_id: str) -> None:
    if not is_first_turn():
        return
    state = get_trust_state()
    if not state:
        level = max(PERMISSION_LEVELS.get(p, 1) for p in HANUMAN_PERMISSIONS)
        state = {
            "agent": AGENT, "current_level": min(level, 3),
            "level_name": TRUST_LEVELS.get(min(level, 3), "ENGINEER"),
            "permissions": HANUMAN_PERMISSIONS,
            "session_count": 0, "clean_session_count": 0,
            "infraction_count": 0, "advancement_candidate": False,
        }
    state["session_count"] = state.get("session_count", 0) + 1
    threshold = ADVANCEMENT_THRESHOLDS.get(state.get("current_level", 2))
    clean = state.get("clean_session_count", 0)
    if threshold and clean >= threshold and not state.get("advancement_candidate"):
        state["advancement_candidate"] = True
        current = state.get("current_level", 2)
        target = current + 1
        print(
            f"[SOURCE_RING — ADVANCEMENT READY]\n"
            f"  Agent: {AGENT}  |  {TRUST_LEVELS.get(current,'?')} → {TRUST_LEVELS.get(target,'?')}\n"
            f"  Clean sessions: {clean} / {threshold}\n"
            f"  Confirm (advance) / Deny (hold) / Wait (ask later)"
        )
    save_trust_state(state)


def _run_anchor() -> None:
    if not should_anchor():
        return
    try:
        anchor = json.loads(ANCHOR_CACHE.read_text()) if ANCHOR_CACHE.exists() else {}
        if not anchor:
            return
        lines = ["[ANCHOR]"]
        if anchor.get("agent"):
            lines.append(f"agent={anchor['agent']}  postgres={anchor.get('postgres','?')}")
        if anchor.get("handoff_title"):
            lines.append(f"last handoff: {anchor['handoff_title']}")
        if anchor.get("open_flags") is not None:
            lines.append(f"open flags: {anchor['open_flags']}")
        if anchor.get("handoff_summary"):
            lines.append(anchor["handoff_summary"][:200])
        print("\n".join(lines))
    except Exception:
        pass


def _run_feedback(prompt: str, session_id: str) -> None:
    if not prompt or len(prompt.strip()) < 8:
        return
    for item in detect_feedback(prompt):
        try:
            call("store_put", {
                "app_id": AGENT,
                "collection": f"{AGENT}/feedback",
                "record": {
                    "id": f"fb-{session_id[:8]}-{abs(hash(item['rule'])) % 99999:05d}",
                    "type": item["type"],
                    "rule": item["rule"],
                    "excerpt": item["excerpt"],
                    "session_id": session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",
                },
            }, timeout=5)
        except Exception:
            pass


def _run_notice(prompt: str, session_id: str) -> str:
    """Scan prompt for PII. Returns redacted text (or original if no matches/error)."""
    if not _notice or not prompt:
        return prompt
    try:
        result = _notice(prompt, surface="prompt", session_id=session_id)
        return result.redacted
    except Exception:
        return prompt


def _log_turn(prompt: str, session_id: str) -> None:
    try:
        TURNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with open(TURNS_FILE, "a") as f:
            f.write(f"[{ts}] [{session_id[:8]}] HUMAN\n{prompt}\n---\n")
    except Exception:
        pass


_ROUTE_MIN_LEN = 12  # skip routing for very short prompts — greetings, single words

def _run_route(prompt: str, session_id: str) -> None:
    if not _routing_oracle:
        return
    stripped = prompt.strip()
    if len(stripped) < _ROUTE_MIN_LEN:
        return
    try:
        # Hook context: rules only, no LLM fallback.
        # LLM fallback is available via willow_route MCP tool where latency is acceptable.
        from willow.routing.oracle import match_rules, load_rules, _write_decision
        from datetime import datetime, timezone
        import time
        t0 = time.monotonic()
        rules = load_rules(session_id)
        matched = match_rules(stripped, rules)
        if not matched:
            return  # no rule match → silently pass, don't call LLM
        latency = round((time.monotonic() - t0) * 1000)
        agent = matched["agent"]
        rule = matched["id"]
        print(f"[ROUTE] → {agent}  rule={rule}  conf=1.00  {latency}ms")
        _write_decision({
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "prompt_snippet": stripped[:40],
            "routed_to": agent,
            "rule_matched": rule,
            "confidence": 1.0,
            "latency_ms": latency,
        })
    except Exception:
        pass


def _inject_dispatch_inbox() -> None:
    """
    On first operator turn only: read dispatch inbox and inject [DISPATCH] block.
    Guard: never fires on subsequent turns or unattended session start.
    """
    if not is_first_turn():
        return
    if not DISPATCH_INBOX.exists():
        return
    try:
        messages = json.loads(DISPATCH_INBOX.read_text())
        if not messages:
            return
        lines = ["[DISPATCH] You have pending tasks from #dispatch:"]
        for msg in messages[:5]:
            sender = msg.get("sender", "?")
            content = msg.get("content", "")[:200]
            lines.append(f"  from {sender}: {content}")
        if len(messages) > 5:
            lines.append(f"  ... and {len(messages) - 5} more in {DISPATCH_INBOX}")
        print("\n".join(lines))
        DISPATCH_INBOX.unlink(missing_ok=True)
    except Exception:
        pass


def _run_flat_handoff_checkpoint(session_id: str) -> None:
    """Write flat handoff every FLAT_HANDOFF_INTERVAL prompts — crash-safe checkpoint."""
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"prompt_count": 0}
        count = state.get("prompt_count", 0)
        if count % FLAT_HANDOFF_INTERVAL != 0:
            return
        from willow.fylgja.handoff_flat import write_flat_handoff
        write_flat_handoff(session_id, AGENT)
    except Exception:
        pass


def _run_corpus_capture(prompt: str, session_id: str) -> None:
    """Stage correction atoms to corpus/corrections when a correction is detected."""
    if not detect_correction(prompt):
        return
    try:
        import sys as _sys
        _repo_root = str(Path(__file__).parent.parent.parent.parent)
        if _repo_root not in _sys.path:
            _sys.path.insert(0, _repo_root)
        from core.willow_store import WillowStore
        _store = WillowStore()
        import uuid as _uuid
        record_id = f"corr-{_uuid.uuid4().hex[:8]}"
        _store.put("corpus/corrections", {
            "id": record_id,
            "type": "correction",
            "source": "prompt_submit_hook",
            "content": prompt.strip()[:300],
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sandbox": True,
            "b17": "CRPS0",
        }, record_id=record_id)
    except Exception:
        pass


def _run_build_continue() -> None:
    task = get_active_task()
    if not task:
        return
    print(
        f"[BUILD-CONTINUE] Active work in progress: {task[:120]}\n"
        f"[BUILD-CONTINUE] Keep building. Do not stop to report status or ask for direction.\n"
        f"[BUILD-CONTINUE] Only pause if blocked or if Sean asks a question."
    )


def _check_identity() -> None:
    """Warn if the running agent doesn't match the anchor written at session start."""
    if not is_first_turn():
        return
    try:
        if not ANCHOR_CACHE.exists():
            return
        anchor = json.loads(ANCHOR_CACHE.read_text())
        anchor_agent = anchor.get("agent", "")
        if anchor_agent and anchor_agent != AGENT:
            print(
                f"[IDENTITY MISMATCH] anchor={anchor_agent} running={AGENT}\n"
                f"  CWD: {Path.cwd()}\n"
                f"  Re-run /startup to reset the anchor, or delete ~/.willow/session_anchor_{AGENT}.json."
            )
            sys.exit(1)
    except Exception:
        pass


def _is_isolated_directory() -> bool:
    """Return True if CWD is a sandbox/isolated directory — skip all fleet hooks."""
    mcp = Path.cwd() / ".mcp.json"
    try:
        data = json.loads(mcp.read_text())
        return data.get("mcpServers") == {}
    except Exception:
        return False


def main():
    if _is_isolated_directory():
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "unknown")
    prompt = data.get("prompt", "")

    _check_identity()
    _run_source_ring(session_id)
    _run_route(prompt, session_id)
    _run_anchor()
    _run_flat_handoff_checkpoint(session_id)
    _inject_dispatch_inbox()
    _run_corpus_capture(prompt, session_id)
    _run_feedback(prompt, session_id)
    prompt = _run_notice(prompt, session_id)
    _log_turn(prompt, session_id)
    # Ledger: record human turn as observation (survives context compression)
    if _LEDGER_AVAILABLE and prompt:
        _ledger_observe(prompt[:300], session_id=session_id)
    _run_build_continue()

    sys.exit(0)


if __name__ == "__main__":
    main()
