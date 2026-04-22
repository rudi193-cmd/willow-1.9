"""
SAP Gate v2 — SAFE folder + PGP manifest verification
b17: 0293H
ΔΣ=42

Authorization chain (all four must pass):
1. SAFE/Applications/<app_id>/ folder exists
2. safe-app-manifest.json present and readable
3. safe-app-manifest.json.sig present
4. gpg --verify confirms signature against Sean's key

Any failure → deny + log to sap/log/gaps.jsonl.
Revocation = delete folder or signature.

Hardened gate for Willow 1.7. Replaces the filesystem-only
gate in Willow 1.5 / Ashokoa/sap/core/gate.py (b17: 36N22).
"""

import json
import logging
import os
import re as _re
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

SAFE_ROOT = Path(os.environ.get("WILLOW_SAFE_ROOT", "/media/willow/SAFE/Applications"))
PROFESSOR_ROOT = SAFE_ROOT / "utety-chat" / "professors"
LOG_DIR = Path(__file__).parent.parent / "log"

# Dev fallback: search $WILLOW_DEV_SAFE_ROOT/safe-app-<app_id>/ when SAFE_ROOT lacks the folder.
# PGP is skipped for dev paths — logged as dev_access_granted, not access_granted.
_DEV_SAFE_ROOT = Path(os.environ["WILLOW_DEV_SAFE_ROOT"]) if os.environ.get("WILLOW_DEV_SAFE_ROOT") else None

_EXPECTED_FP = os.environ.get(
    "WILLOW_PGP_FINGERPRINT",
    "96B92D78875F60BE229A0A348F414B8C1B402BB0",
).upper().replace(" ", "")

_APP_ID_RE = _re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]*$')

# Maps semantic permission strings (as declared in safe-app-manifest.json)
# to the set of tool names they grant. Fail-closed: any tool not covered → deny.
PERMISSION_GROUPS: dict[str, frozenset] = {
    "store_read": frozenset({
        "store_get", "store_search", "store_list", "store_search_all",
        "store_edges_for", "store_stats", "store_audit",
    }),
    "store_write": frozenset({
        "store_put", "store_update", "store_delete", "store_add_edge",
    }),
    "conversation_storage": frozenset({
        "store_put", "store_get", "store_search", "store_list", "store_update",
    }),
    "export_data": frozenset({
        "store_list", "store_search_all",
    }),
    "postgres_read": frozenset({
        "willow_knowledge_search", "willow_query", "willow_agents",
        "willow_status", "willow_system_status", "willow_governance",
        "willow_memory_check", "willow_handoff_latest", "willow_handoff_search",
    }),
    "knowledge_write": frozenset({
        "willow_knowledge_ingest", "willow_journal",
    }),
    "safe_manifest_read": frozenset({
        "willow_status", "willow_system_status",
    }),
    "local_llm": frozenset({
        "willow_chat", "willow_persona", "willow_route", "willow_speak",
    }),
    "cloud_llm_free": frozenset({
        "willow_chat",
    }),
    "task_submit": frozenset({
        "willow_task_submit", "willow_task_status", "willow_task_list",
    }),
    "opus_read": frozenset({
        "opus_search", "opus_feedback",
    }),
    "opus_write": frozenset({
        "opus_ingest", "opus_feedback_write", "opus_journal",
    }),
    "jeles_fetch": frozenset({
        "jeles_fetch", "jeles_sources",
    }),
    "nest": frozenset({
        "willow_nest_scan", "willow_nest_queue", "willow_nest_file",
    }),
    "pipeline": frozenset({
        "willow_agent_create", "willow_jeles_register", "willow_jeles_extract",
        "willow_binder_file", "willow_binder_edge", "willow_ratify",
        "willow_base17", "willow_handoff_rebuild", "willow_reload",
        "willow_restart_server",
    }),
    # Combined read: postgres_read + store_read + safe_manifest_read.
    # Used by SAFE partition manifests (e.g. Willow-dashboard).
    "willow_kb_read": frozenset({
        "willow_knowledge_search", "willow_query", "willow_agents",
        "willow_status", "willow_system_status", "willow_governance",
        "willow_memory_check", "willow_handoff_latest", "willow_handoff_search",
        "store_get", "store_search", "store_list", "store_search_all",
        "store_edges_for", "store_stats", "store_audit",
    }),
}

# If set, only these app_ids are accepted (comma-separated). INFRA IDs are always exempt.
_ALLOWED_IDS_RAW = os.environ.get("WILLOW_ALLOWED_APP_IDS", "")
_ALLOWED_APP_IDS: frozenset[str] = (
    frozenset(x.strip() for x in _ALLOWED_IDS_RAW.split(",") if x.strip())
    if _ALLOWED_IDS_RAW.strip() else frozenset()
)


def _resolve_dev_app_path(app_id: str) -> Optional[Path]:
    """Check $WILLOW_DEV_SAFE_ROOT for a manifest. Tries safe-app-<app_id>/ then <app_id>/."""
    if _DEV_SAFE_ROOT is None:
        return None
    for dirname in (f"safe-app-{app_id}", app_id):
        candidate = _DEV_SAFE_ROOT / dirname
        if candidate.is_dir() and (candidate / "safe-app-manifest.json").exists():
            return candidate
    return None


def _resolve_app_path(root: Path, app_id: str) -> Optional[Path]:
    """Return the app directory under root, matching app_id case-insensitively."""
    exact = root / app_id
    if exact.exists() and exact.is_dir():
        return exact
    try:
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.lower() == app_id.lower():
                return entry
    except (PermissionError, OSError):
        pass
    return None


def _validate_app_id(app_id: str) -> str:
    """Reject app_id values that could escape SAFE_ROOT via path traversal."""
    if not _APP_ID_RE.match(app_id or ""):
        raise ValueError(f"Invalid app_id: {app_id!r} — must match ^[a-zA-Z0-9][a-zA-Z0-9_\\-]*$")
    return app_id


logger = logging.getLogger("sap.gate")


def _log_gap(app_id: str, reason: str) -> None:
    """Record unauthorized access attempt."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "event": "access_denied",
        "reason": reason,
    }
    logger.warning("SAP gate denied: app_id=%s reason=%s", app_id, reason)
    log_path = LOG_DIR / "gaps.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _log_grant(app_id: str) -> None:
    """Record authorized access."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "event": "access_granted",
    }
    log_path = LOG_DIR / "grants.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _log_dev_grant(app_id: str, path: Path) -> None:
    """Record dev-mode access (no PGP). Logged separately so prod grants stay clean."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.warning("SAP gate DEV grant (no PGP): app_id=%s path=%s", app_id, path)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "event": "dev_access_granted",
        "path": str(path),
        "pgp": "skipped",
    }
    log_path = LOG_DIR / "grants.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _log_tool_denied(app_id: str, tool_name: str, perms: list) -> None:
    """Record a capability denial — identity passed but tool not in permissions."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "event": "tool_not_permitted",
        "tool": tool_name,
        "declared_permissions": perms,
    }
    logger.warning("SAP gate tool denied: app_id=%s tool=%s perms=%s", app_id, tool_name, perms)
    log_path = LOG_DIR / "gaps.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _verify_pgp(manifest_path: Path) -> tuple[bool, str]:
    """
    Verify the manifest's GPG detached signature AND confirm signer identity.

    Uses gpg --status-fd=1 to get machine-readable output and parse
    the primary key fingerprint from the VALIDSIG status line.
    Expected fingerprint is read from WILLOW_PGP_FINGERPRINT env var.

    Returns (ok, reason).
    """
    sig_path = manifest_path.parent / (manifest_path.name + ".sig")

    if not sig_path.exists():
        return False, f"No signature file: {sig_path.name}"

    try:
        result = subprocess.run(
            ["gpg", "--verify", "--status-fd=1", str(sig_path), str(manifest_path)],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            return False, f"gpg verify failed: {stderr[:200]}"

        stdout = result.stdout.decode("utf-8", errors="replace")
        signer_fp = None
        for line in stdout.splitlines():
            if line.startswith("[GNUPG:] VALIDSIG"):
                parts = line.split()
                # Full line: [GNUPG:] VALIDSIG <subkey-fp> <date> <ts> <ts-exp>
                #            <expire> <reserved> <pk-algo> <hash-algo> <sig-class> <primary-fp>
                # parts indices: 0=[GNUPG:] 1=VALIDSIG 2=subkey-fp ... 11=primary-fp
                if len(parts) >= 12:
                    signer_fp = parts[11].upper()
                    break

        if signer_fp is None:
            excerpt = stdout[:200].replace("\n", " ")
            return False, f"gpg returned success but no VALIDSIG in status output — got: {excerpt}"
        if signer_fp != _EXPECTED_FP:
            return False, f"signature by unexpected key: {signer_fp[:16]}... (expected: {_EXPECTED_FP[:16]}...)"
        return True, "signature verified"

    except FileNotFoundError:
        return False, "gpg not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "gpg verify timed out (5s)"
    except Exception as e:
        return False, f"gpg verify error: {e}"


def authorized(app_id: str) -> bool:
    """
    Four-step authorization check.

    1. SAFE folder exists
    2. Manifest present and readable
    3. Signature file present (checked inside _verify_pgp)
    4. GPG verifies the signature

    Logs all denials. Returns True only when all four pass.
    """
    try:
        app_id = _validate_app_id(app_id)
    except ValueError as e:
        _log_gap(app_id, f"Invalid app_id rejected: {e}")
        return False

    if _ALLOWED_APP_IDS and app_id not in _ALLOWED_APP_IDS:
        _log_gap(app_id, f"app_id not in allowlist (WILLOW_ALLOWED_APP_IDS)")
        return False

    # Check top-level Applications first, then UTETY/professors/ fallback
    app_path = _resolve_app_path(SAFE_ROOT, app_id) or _resolve_app_path(PROFESSOR_ROOT, app_id)

    if app_path is not None:
        manifest_path = app_path / "safe-app-manifest.json"
        if not manifest_path.exists():
            _log_gap(app_id, f"No manifest at: {manifest_path}")
            return False
        try:
            manifest_path.read_text(encoding="utf-8")
        except Exception as e:
            _log_gap(app_id, f"Manifest unreadable: {e}")
            return False
        sig_ok, sig_reason = _verify_pgp(manifest_path)
        if not sig_ok:
            _log_gap(app_id, f"PGP verification failed: {sig_reason}")
            return False
        _log_grant(app_id)
        return True

    # Dev fallback: $WILLOW_DEV_SAFE_ROOT/safe-app-<app_id>/ — no PGP required
    dev_path = _resolve_dev_app_path(app_id)
    if dev_path is not None:
        try:
            (dev_path / "safe-app-manifest.json").read_text(encoding="utf-8")
        except Exception as e:
            _log_gap(app_id, f"Dev manifest unreadable: {e}")
            return False
        _log_dev_grant(app_id, dev_path)
        return True

    _log_gap(app_id, f"SAFE folder not found: {PROFESSOR_ROOT / app_id}")
    return False


def require_authorized(app_id: str) -> None:
    """
    Assert authorization. Raises PermissionError on denial.
    Prefer this over checking authorized() — callers cannot silently ignore it.
    """
    if not authorized(app_id):
        raise PermissionError(
            f"SAP gate denied: '{app_id}' failed authorization. "
            f"Check SAFE folder exists, manifest is present, "
            f"and safe-app-manifest.json.sig is valid."
        )


def get_manifest(app_id: str) -> Optional[dict]:
    """
    Load the safe-app-manifest.json for an authorized app.
    Returns None if not authorized or manifest is malformed.
    Full auth chain runs — including PGP.
    """
    try:
        app_id = _validate_app_id(app_id)
    except ValueError:
        return None

    if not authorized(app_id):
        return None

    app_path = (
        _resolve_app_path(SAFE_ROOT, app_id)
        or _resolve_app_path(PROFESSOR_ROOT, app_id)
        or _resolve_dev_app_path(app_id)
    )
    if app_path is None:
        return None

    try:
        raw = (app_path / "safe-app-manifest.json").read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception as e:
        logger.error("Manifest parse error for %s: %s", app_id, e)
        return None


def permitted(app_id: str, tool_name: str) -> bool:
    """
    Check if an authorized app may call a specific tool.

    Reads permissions[] from the manifest and expands via PERMISSION_GROUPS.
    Unknown permission strings are treated as literal tool names.
    Fail-closed: empty or missing permissions → deny all tool calls.
    Does NOT re-run PGP — call after authorized() has already passed.
    """
    try:
        app_id = _validate_app_id(app_id)
    except ValueError:
        return False

    app_path = (
        _resolve_app_path(SAFE_ROOT, app_id)
        or _resolve_app_path(PROFESSOR_ROOT, app_id)
        or _resolve_dev_app_path(app_id)
    )
    if app_path is None:
        return False

    try:
        raw = (app_path / "safe-app-manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(raw)
    except Exception as e:
        logger.error("permitted(): manifest unreadable for %s: %s", app_id, e)
        return False

    perms: list = manifest.get("permissions", [])
    if not perms:
        _log_tool_denied(app_id, tool_name, perms)
        return False

    allowed: set = set()
    for perm in perms:
        group = PERMISSION_GROUPS.get(perm)
        if group is not None:
            allowed.update(group)
        else:
            allowed.add(perm)

    if tool_name not in allowed:
        _log_tool_denied(app_id, tool_name, perms)
        return False

    return True


def list_authorized() -> list[str]:
    """
    Return all app_ids that pass the full authorization chain.
    Runs gpg --verify for each candidate — use sparingly.
    """
    if not SAFE_ROOT.exists():
        return []

    result = []
    for entry in sorted(SAFE_ROOT.iterdir()):
        if entry.is_dir() and (entry / "safe-app-manifest.json").exists():
            if authorized(entry.name):
                result.append(entry.name)
    return result
