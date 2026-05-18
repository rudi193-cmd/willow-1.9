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
try:
    import psycopg2
except ImportError:
    psycopg2 = None

_safe_root_env = os.environ.get("WILLOW_SAFE_ROOT")
if not _safe_root_env:
    raise RuntimeError(
        "WILLOW_SAFE_ROOT is not set — gate cannot initialize. "
        "Set it to the SAFE/Applications directory (e.g. /home/sean-campbell/SAFE/Applications)."
    )
SAFE_ROOT = Path(_safe_root_env)
PROFESSOR_ROOT = SAFE_ROOT / "utety-chat" / "professors"
LOG_DIR = Path(__file__).parent.parent / "log"

# Dev fallback: search $WILLOW_DEV_SAFE_ROOT/safe-app-<app_id>/ when SAFE_ROOT lacks the folder.
# PGP is skipped for dev paths — logged as dev_access_granted, not access_granted.
# WARNING: if this var is set in a production shell environment, it silently disables PGP verification.
# Unset it in prod launch scripts: unset WILLOW_DEV_SAFE_ROOT
_DEV_SAFE_ROOT = Path(os.environ["WILLOW_DEV_SAFE_ROOT"]) if os.environ.get("WILLOW_DEV_SAFE_ROOT") else None
if _DEV_SAFE_ROOT is not None:
    import sys as _sys
    print(f"[gate] WARNING: WILLOW_DEV_SAFE_ROOT is set ({_DEV_SAFE_ROOT}) — PGP gate disabled for dev manifests. Unset in production.", file=_sys.stderr, flush=True)

_EXPECTED_FP = os.environ.get(
    "WILLOW_PGP_FINGERPRINT",
    "96B92D78875F60BE229A0A348F414B8C1B402BB0",
).upper().replace(" ", "")

_APP_ID_RE = _re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]*$')

# Maps semantic permission strings (as declared in safe-app-manifest.json)
# to the set of tool names they grant. Fail-closed: any tool not covered → deny.
PERMISSION_GROUPS: dict[str, frozenset] = {
    # SAP MCP 2.0 tool names (soil_ prefix replaces store_, new prefixes throughout)
    "store_read": frozenset({
        "soil_get", "soil_search", "soil_list", "soil_search_all",
        "soil_edges_for", "soil_stats", "soil_audit",
    }),
    "store_write": frozenset({
        "soil_put", "soil_update", "soil_delete", "soil_add_edge",
    }),
    "conversation_storage": frozenset({
        "soil_put", "soil_get", "soil_search", "soil_list", "soil_update",
    }),
    "export_data": frozenset({
        "soil_list", "soil_search_all",
    }),
    "postgres_read": frozenset({
        "kb_search", "kb_query", "kb_at", "kb_get",
        "fleet_agents", "fleet_status", "fleet_system_status",
        "fleet_governance", "mem_check",
        "handoff_latest", "handoff_search",
        "session_review", "diagnostic_summary", "env_check",
    }),
    "knowledge_write": frozenset({
        "kb_ingest", "kb_journal",
    }),
    "safe_manifest_read": frozenset({
        "fleet_status", "fleet_system_status",
    }),
    "local_llm": frozenset({
        "infer_chat", "fleet_persona", "agent_route", "infer_speak",
        "voice_keyterms", "session_review", "infer_7b",
    }),
    "cloud_llm_free": frozenset({
        "infer_chat",
    }),
    "task_submit": frozenset({
        "agent_task_submit", "agent_task_status", "agent_task_list",
    }),
    "opus_read": frozenset({
        "index_search", "index_feedback",
    }),
    "opus_write": frozenset({
        "index_ingest", "index_feedback_write", "index_journal",
    }),
    "jeles_fetch": frozenset({
        "mem_jeles_extract", "mem_jeles_register",
    }),
    "nest": frozenset({
        "nest_scan", "nest_queue", "nest_file",
    }),
    "pipeline": frozenset({
        "agent_create",
        "mem_jeles_register", "mem_jeles_extract",
        "mem_binder_file", "mem_binder_edge", "mem_ratify",
        "fleet_base17", "handoff_rebuild",
        "fleet_reload", "fleet_restart",
    }),
    "image_gen": frozenset({
        "infer_imagine",
    }),
    # Combined read: postgres_read + store_read + safe_manifest_read.
    # Used by SAFE partition manifests (e.g. Willow-dashboard).
    "willow_kb_read": frozenset({
        "kb_search", "kb_query", "kb_at", "kb_get",
        "fleet_agents", "fleet_status", "fleet_system_status",
        "fleet_governance", "mem_check",
        "handoff_latest", "handoff_search",
        "soil_get", "soil_search", "soil_list", "soil_search_all",
        "soil_edges_for", "soil_stats", "soil_audit",
        "session_review", "diagnostic_summary", "env_check",
    }),
    # SAP MCP 2.0 — new groups covering domains not in v1
    "fork_manage": frozenset({
        "fork_create", "fork_delete", "fork_join",
        "fork_list", "fork_log", "fork_merge", "fork_status",
    }),
    "skill_manage": frozenset({
        "skill_list", "skill_load", "skill_put",
    }),
    "ledger_read_perm": frozenset({
        "ledger_read",
    }),
    "ledger_write_perm": frozenset({
        "ledger_write",
    }),
    "agent_dispatch": frozenset({
        "agent_dispatch", "agent_dispatch_result", "agent_route",
        "agent_task_submit", "agent_task_status", "agent_task_list",
    }),
    "fleet_admin": frozenset({
        "fleet_health", "fleet_blast",
        "fleet_governance", "fleet_persona", "fleet_base17",
        "fleet_reload", "fleet_restart",
        "policy_put", "policy_list", "policy_delete",
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
        _log_gap(app_id, f"permitted(): no SAFE folder found for {app_id!r} — tool={tool_name!r}")
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


def _parse_app_id_from_collection(collection: str) -> Optional[str]:
    """
    Extract app_id from a collection path.

    Pattern: app-namespace/...
    Example: story-timeline/atoms/ → story-timeline
    Returns None if unable to parse.
    """
    if not collection or "/" not in collection:
        return None
    parts = collection.split("/", 1)
    app_id = parts[0].strip()
    return app_id if app_id and _APP_ID_RE.match(app_id) else None


def authorized_cross_app(requesting_app_id: str, target_collection: str, access: str = "read") -> bool:
    """
    Check if requesting_app_id has an approved connection to target_collection.

    1. If target app is the same as requesting app → allow (own namespace)
    2. Query sap.app_connections for a matching row
    3. Verify scope_path_matches(target_collection, scope_path)

    Returns True if authorized, False otherwise.
    Logs all denials. Handles Postgres unavailability gracefully (deny).
    """
    if psycopg2 is None:
        logger.error("authorized_cross_app(): psycopg2 not available")
        return False

    try:
        requesting_app_id = _validate_app_id(requesting_app_id)
    except ValueError as e:
        logger.warning("authorized_cross_app(): invalid requesting_app_id: %s", e)
        return False

    target_app_id = _parse_app_id_from_collection(target_collection)
    if target_app_id is None:
        logger.warning("authorized_cross_app(): unable to parse target_app_id from %s", target_collection)
        return False

    # Own namespace — always allowed
    if target_app_id == requesting_app_id:
        return True

    try:
        user = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "sean-campbell"))
        conn = psycopg2.connect(dbname="willow_19", user=user)
        cur = conn.cursor()

        # Query for a matching connection with scope path matching
        query = """
            SELECT id FROM sap.app_connections
            WHERE from_app_id = %s
              AND to_app_id = %s
              AND access = %s
              AND sap.scope_path_matches(%s, scope_path)
        """
        cur.execute(query, (requesting_app_id, target_app_id, access, target_collection))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row is not None:
            logger.info("authorized_cross_app: %s → %s granted", requesting_app_id, target_app_id)
            return True

        logger.warning(
            "authorized_cross_app: %s → %s denied (no matching connection)",
            requesting_app_id, target_app_id
        )
        return False

    except Exception as e:
        logger.error("authorized_cross_app(): database error: %s", e)
        return False


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
