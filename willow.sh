#!/usr/bin/env bash
# willow.sh — Willow 1.9 launcher
# b17: WLW19  ΔΣ=42
#
# Usage:
#   ./willow.sh              — start SAP MCP server (stdio)
#   ./willow.sh status       — check Postgres + metabolic socket
#   ./willow.sh metabolic    — run Norn pass now
#   ./willow.sh update       — check for updates and apply if available
#   ./willow.sh export       — dump user data to ~/.willow/export.json
#   ./willow.sh purge <proj> — delete a project namespace entirely
#   ./willow.sh ledger [proj] — show FRANK's ledger (optional project filter)
#   ./willow.sh verify       — verify all SAFE manifests

set -euo pipefail

WILLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WILLOW_ROOT
SAP_MCP="${WILLOW_ROOT}/sap/sap_mcp.py"

# Python
if [[ -z "${WILLOW_PYTHON:-}" ]]; then
    if [[ -x "${HOME}/.willow-venv/bin/python3" ]]; then
        WILLOW_PYTHON="${HOME}/.willow-venv/bin/python3"
    else
        WILLOW_PYTHON="$(command -v python3)"
    fi
fi
export WILLOW_PYTHON

# ── User store always at ~/.willow/store/ — never inside the repo ─────────────
export WILLOW_STORE_ROOT="${WILLOW_STORE_ROOT:-${HOME}/.willow/store}"
export WILLOW_VAULT="${WILLOW_VAULT:-${HOME}/.willow/vault.db}"
export WILLOW_SAFE_ROOT="${WILLOW_SAFE_ROOT:-${HOME}/SAFE/Applications}"

# Postgres — Unix socket, willow_19 DB (clean break from 1.7)
unset WILLOW_PG_HOST WILLOW_PG_PORT WILLOW_PG_PASS
export WILLOW_PG_DB="${WILLOW_PG_DB:-willow_19}"
export WILLOW_PG_USER="${WILLOW_PG_USER:-$(whoami)}"
export WILLOW_AGENT_NAME="heimdallr"

# Python path — willow-1.9 first, no legacy paths
export PYTHONPATH="${WILLOW_ROOT}:${PYTHONPATH:-}"

cmd="${1:-start}"

case "$cmd" in
    start|"")
        exec "${WILLOW_PYTHON}" "${SAP_MCP}"
        ;;

    status)
        echo "Willow 1.9 — status"
        echo "  Store:    ${WILLOW_STORE_ROOT}"
        echo "  Vault:    ${WILLOW_VAULT}"
        echo "  Version:  $(cat "${HOME}/.willow/version" 2>/dev/null || echo 'not installed')"
        "${WILLOW_PYTHON}" -c "
import sys, os
sys.path.insert(0, '${WILLOW_ROOT}')
os.environ['WILLOW_PG_DB'] = '${WILLOW_PG_DB}'
from core.pg_bridge import try_connect
pg = try_connect()
print('  Postgres:', 'connected' if pg else 'NOT CONNECTED')
if pg: pg.close()
"
        systemctl --user is-active willow-metabolic.socket 2>/dev/null \
            && echo "  Metabolic socket: active" \
            || echo "  Metabolic socket: inactive"
        ;;

    metabolic)
        echo "Willow 1.9 — running Norn pass"
        WILLOW_PG_DB="${WILLOW_PG_DB}" exec "${WILLOW_PYTHON}" "${WILLOW_ROOT}/core/metabolic.py"
        ;;

    update)
        echo "Willow 1.9 — checking for updates"
        CURRENT=$(cat "${HOME}/.willow/version" 2>/dev/null || echo "unknown")
        LATEST=$(curl -s --max-time 5 \
            "https://api.github.com/repos/rudi193-cmd/willow-1.9/releases/latest" \
            2>/dev/null | "${WILLOW_PYTHON}" -c \
            "import json,sys; d=json.load(sys.stdin); print(d.get('tag_name','unknown'))" \
            2>/dev/null || echo "unknown")
        echo "  Current: ${CURRENT}  Latest: ${LATEST}"
        if [[ "${CURRENT}" == "${LATEST}" || "${LATEST}" == "unknown" ]]; then
            echo "  Already up to date."
            exit 0
        fi
        echo "  Updating..."
        git -C "${WILLOW_ROOT}" pull origin master
        "${WILLOW_PYTHON}" "${WILLOW_ROOT}/seed.py" --skip-gpg
        echo "  Update complete. Version: $(cat "${HOME}/.willow/version")"
        ;;

    export)
        echo "Willow 1.9 — exporting user data to ~/.willow/export.json"
        WILLOW_PG_DB="${WILLOW_PG_DB}" "${WILLOW_PYTHON}" -c "
import sys, json, os
sys.path.insert(0, '${WILLOW_ROOT}')
os.environ['WILLOW_PG_DB'] = '${WILLOW_PG_DB}'
from core.willow_store import WillowStore
store = WillowStore()
data = {'store': {}}
for col in store.collections():
    data['store'][col] = store.list(col)
output = os.path.expanduser('~/.willow/export.json')
with open(output, 'w') as f:
    json.dump(data, f, indent=2, default=str)
print(f'  Exported to {output}')
print(f'  Collections: {len(data[\"store\"])}')
"
        ;;

    purge)
        PROJECT="${2:-}"
        if [[ -z "${PROJECT}" ]]; then
            echo "Usage: willow.sh purge <project>"
            exit 1
        fi
        echo "  Purging project namespace: ${PROJECT}"
        echo "  This deletes all KB edges, atoms, and community nodes for ${PROJECT}."
        read -rp "  Type the project name to confirm: " CONFIRM
        if [[ "${CONFIRM}" != "${PROJECT}" ]]; then
            echo "  Cancelled."
            exit 0
        fi
        PURGE_PROJECT="${PROJECT}" WILLOW_PG_DB="${WILLOW_PG_DB}" "${WILLOW_PYTHON}" -c "
import sys, os
sys.path.insert(0, '${WILLOW_ROOT}')
from core.pg_bridge import PgBridge
project = os.environ['PURGE_PROJECT']
bridge = PgBridge()
with bridge.conn.cursor() as cur:
    cur.execute('DELETE FROM knowledge WHERE project = %s', (project,))
    count = cur.rowcount
bridge.conn.commit()
print(f'  Deleted {count} KB edges for project: {project}')
"
        ;;

    ledger)
        echo "Willow 1.9 — FRANK's Ledger"
        LEDGER_PROJECT="${2:-}"
        LEDGER_PROJECT="${LEDGER_PROJECT}" WILLOW_PG_DB="${WILLOW_PG_DB}" "${WILLOW_PYTHON}" -c "
import sys, os, json
sys.path.insert(0, '${WILLOW_ROOT}')
from core.pg_bridge import PgBridge
bridge = PgBridge()
project = os.environ.get('LEDGER_PROJECT') or None
entries = bridge.ledger_read(project=project, limit=20)
result = bridge.ledger_verify()
print(f'  Chain: {\"VALID\" if result[\"valid\"] else \"BROKEN\"}  Entries: {result[\"count\"]}')
print()
for e in entries:
    ts = e['created_at'].strftime('%Y-%m-%d %H:%M') if hasattr(e['created_at'], 'strftime') else str(e['created_at'])[:16]
    content = e.get('content') or {}
    note = content.get('note', json.dumps(content)[:60])
    print(f'  [{ts}] {e[\"project\"]:20s} {e[\"event_type\"]:15s} {note}')
"
        ;;

    nuke)
        echo ""
        echo "  ╔══════════════════════════════════════════════════════════╗"
        echo "  ║                  W I L L O W   N U K E                  ║"
        echo "  ╠══════════════════════════════════════════════════════════╣"
        echo "  ║                                                          ║"
        echo "  ║  This permanently deletes ALL of your Willow data.      ║"
        echo "  ║                                                          ║"
        echo "  ║  What will be destroyed:                                 ║"
        echo "  ║    • Every project namespace and its knowledge           ║"
        echo "  ║    • Every session, every atom, every edge               ║"
        echo "  ║    • Your API keys (vault)                               ║"
        echo "  ║    • Your GPG master key                                 ║"
        echo "  ║    • FRANK's ledger                                      ║"
        echo "  ║    • Your CMB atom — the first session fossil record     ║"
        echo "  ║    • All backups stored inside ~/.willow/                ║"
        echo "  ║    • Your telemetry preferences                          ║"
        echo "  ║                                                          ║"
        echo "  ║  What will NOT be touched:                               ║"
        echo "  ║    • The software (this repo stays)                      ║"
        echo "  ║    • ~/SAFE/Applications/ (your SAFE folder)             ║"
        echo "  ║    • The willow_19 Postgres database                     ║"
        echo "  ║                                                          ║"
        echo "  ║  There is no undo. There is no recovery.                ║"
        echo "  ║  Run 'willow backup' first if you want a copy.          ║"
        echo "  ║                                                          ║"
        echo "  ╚══════════════════════════════════════════════════════════╝"
        echo ""
        read -rp "  Type DELETE MY DATA to proceed (anything else cancels): " CONFIRM
        if [[ "${CONFIRM}" != "DELETE MY DATA" ]]; then
            echo ""
            echo "  Cancelled. Nothing was deleted."
            exit 0
        fi
        echo ""
        echo "  Deleting ~/.willow/ ..."
        rm -rf "${HOME}/.willow/"
        echo "  Done."
        echo ""
        echo "  Your data is gone. The software remains."
        echo "  Run python3 seed.py to start fresh."
        echo ""
        ;;

    verify)
        echo "Willow 1.9 — manifest verification"
        SAFE_ROOT="${WILLOW_SAFE_ROOT}"
        pass=0; fail=0
        for manifest in "${SAFE_ROOT}"/*/safe-app-manifest.json; do
            [[ -f "$manifest" ]] || continue
            sig="${manifest}.sig"
            label="$(basename "$(dirname "$manifest")")"
            if [[ ! -f "$sig" ]]; then
                echo "  MISSING SIG: ${label}"; fail=$((fail+1))
            elif gpg --verify "$sig" "$manifest" > /dev/null 2>&1; then
                echo "  OK: ${label}"; pass=$((pass+1))
            else
                echo "  BAD SIG: ${label}"; fail=$((fail+1))
            fi
        done
        echo "  Passed: ${pass}  Failed: ${fail}"
        [[ $fail -eq 0 ]]
        ;;

    *)
        echo "Usage: willow.sh [start|status|metabolic|update|export|purge <project>|ledger [project]|verify]"
        exit 1
        ;;
esac
