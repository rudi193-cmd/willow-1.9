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
#   ./willow.sh valhalla     — collect DPO training pairs to ~/.willow/valhalla/
#   ./willow.sh verify       — verify all SAFE manifests

set -euo pipefail

WILLOW_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
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
        "${WILLOW_PYTHON}" "${WILLOW_ROOT}/root.py" --skip-gpg
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

    backup)
        echo "Willow 1.9 — backup"
        WILLOW_PG_DB="${WILLOW_PG_DB}" "${WILLOW_PYTHON}" -c "
import sys, os, json
sys.path.insert(0, '${WILLOW_ROOT}')
from core.backup import create_backup
backup_path = create_backup(pg_db='${WILLOW_PG_DB}')
manifest = json.loads((backup_path.parent / 'manifest.json').read_text())
print(f'  Backup:   {backup_path.parent}')
print(f'  Version:  {manifest[\"version\"]}')
print(f'  Postgres: {\"included\" if manifest[\"pg_included\"] else \"not included (pg_dump unavailable)\"}')
print()
print('  Snorri Sturluson would approve.')
"
        ;;

    restore)
        BACKUP_PATH="${2:-}"
        if [[ -z "${BACKUP_PATH}" ]]; then
            echo "Usage: willow.sh restore <path-to-backup-directory>"
            echo "Backups live at: ~/.willow/backups/"
            exit 1
        fi
        echo "  Restoring from: ${BACKUP_PATH}"
        read -rp "  This overwrites ~/.willow/. Type OVERWRITE MY DATA to proceed: " CONFIRM
        if [[ "${CONFIRM}" != "OVERWRITE MY DATA" ]]; then
            echo "  Cancelled."
            exit 0
        fi
        RESTORE_PATH="${BACKUP_PATH}" WILLOW_PG_DB="${WILLOW_PG_DB}" "${WILLOW_PYTHON}" -c "
import sys, os
sys.path.insert(0, '${WILLOW_ROOT}')
from core.backup import restore_backup
from pathlib import Path
restore_backup(Path(os.environ['RESTORE_PATH']), pg_db='${WILLOW_PG_DB}')
print('  Restore complete.')
"
        ;;

    nuke)
        echo ""
        echo "  ╔══════════════════════════════════════════════════════════╗"
        echo "  ║                  W I L L O W   N U K E                  ║"
        echo "  ╠══════════════════════════════════════════════════════════╣"
        echo "  ║                                                          ║"
        echo "  ║  Deletes ~/.willow/ — your local Willow data folder.    ║"
        echo "  ║                                                          ║"
        echo "  ║  What will be destroyed:                                 ║"
        echo "  ║    • Your API keys (vault)                               ║"
        echo "  ║    • Your GPG master key                                 ║"
        echo "  ║    • Local SOIL SQLite store (~/.willow/store/)          ║"
        echo "  ║    • All local backups (~/.willow/backups/)              ║"
        echo "  ║    • Your telemetry preferences                          ║"
        echo "  ║    • Version pin and session logs                        ║"
        echo "  ║                                                          ║"
        echo "  ║  What will NOT be touched:                               ║"
        echo "  ║    • The software (this repo stays)                      ║"
        echo "  ║    • ~/SAFE/Applications/ (your SAFE folder)             ║"
        echo "  ║    • The willow_19 Postgres database                     ║"
        echo "  ║      (knowledge, ledger, CMB atom live there)            ║"
        echo "  ║      To also wipe Postgres: dropdb willow_19             ║"
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
        echo "  Run python3 root.py to start fresh."
        echo ""
        ;;

    valhalla)
        echo "Willow 1.9 — Valhalla collection"
        echo "  Scanning KB for DPO pair candidates..."
        WILLOW_PG_DB="${WILLOW_PG_DB}" "${WILLOW_PYTHON}" -c "
import sys, os
sys.path.insert(0, '${WILLOW_ROOT}')
os.environ['WILLOW_PG_DB'] = '${WILLOW_PG_DB}'
from core.pg_bridge import PgBridge
from core.willow_store import WillowStore
from core.valhalla import collect_dpo_pairs
bridge = PgBridge()
store = WillowStore()
count = collect_dpo_pairs(bridge, store)
print(f'  Pairs collected: {count}')
print(f'  Output: ~/.willow/valhalla/dpo_pairs.jsonl')
print()
print('  The Einherjar grow stronger.')
"
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

    start-all)
        echo "Willow 1.9 — starting all services"
        _services=(grove-mcp journal-watcher journal-responder willow-dashboard willow-metabolic corpus-watcher)
        for svc in "${_services[@]}"; do
            if systemctl --user is-active --quiet "${svc}.service" 2>/dev/null; then
                echo "  [✓] ${svc} already running"
            else
                systemctl --user start "${svc}.service" 2>/dev/null \
                    && echo "  [↑] ${svc} started" \
                    || echo "  [✗] ${svc} failed to start"
            fi
        done
        echo ""
        echo "  Note: sap_mcp.py is spawned by Claude Code only — not managed here."
        ;;

    stop-all)
        echo "Willow 1.9 — stopping all services"
        _services=(willow-dashboard grove-mcp journal-watcher journal-responder willow-metabolic corpus-watcher)
        for svc in "${_services[@]}"; do
            systemctl --user stop "${svc}.service" 2>/dev/null \
                && echo "  [↓] ${svc} stopped" \
                || echo "  [–] ${svc} was not running"
        done
        ;;

    status-all)
        echo "Willow 1.9 — system status"
        echo ""

        # Postgres
        "${WILLOW_PYTHON}" -c "
import sys, os
sys.path.insert(0, '${WILLOW_ROOT}')
os.environ['WILLOW_PG_DB'] = '${WILLOW_PG_DB}'
from core.pg_bridge import try_connect
pg = try_connect()
if pg:
    cur = pg.cursor()
    cur.execute('SELECT COUNT(*) FROM knowledge')
    count = cur.fetchone()[0]
    print(f'  [\033[32m✓\033[0m] postgres          up ({count} KB atoms)')
    pg.close()
else:
    print('  [\033[31m✗\033[0m] postgres          NOT CONNECTED')
" 2>/dev/null || echo "  [✗] postgres          error"

        # Ollama
        curl -sf http://localhost:11434/api/tags > /dev/null 2>&1 \
            && echo "  [✓] ollama            up" \
            || echo "  [✗] ollama            unreachable"

        # Systemd user services
        _services=(grove-mcp journal-watcher journal-responder willow-dashboard willow-metabolic corpus-watcher)
        for svc in "${_services[@]}"; do
            if systemctl --user is-active --quiet "${svc}.service" 2>/dev/null; then
                printf "  [\033[32m✓\033[0m] %-18s running\n" "${svc}"
            elif systemctl --user is-enabled --quiet "${svc}.service" 2>/dev/null; then
                printf "  [\033[31m✗\033[0m] %-18s dead (enabled)\n" "${svc}"
            else
                printf "  [\033[33m–\033[0m] %-18s disabled\n" "${svc}"
            fi
        done

        # MCP server
        if pgrep -f "sap_mcp.py" > /dev/null 2>&1; then
            echo "  [✓] sap_mcp.py        running (Claude Code session)"
        else
            echo "  [–] sap_mcp.py        not running (start via Claude Code)"
        fi

        echo ""
        ;;

    restart)
        "${BASH_SOURCE[0]}" stop-all
        sleep 2
        "${BASH_SOURCE[0]}" start-all
        ;;

    check-updates)
        echo "Willow 1.9 — checking for updates"
        CURRENT=$(grep -r '' "${HOME}/.willow/version" 2>/dev/null || echo "unknown")
        LATEST=$(curl -sf --max-time 10 \
            "https://api.github.com/repos/rudi193-cmd/willow-1.9/releases/latest" \
            2>/dev/null | "${WILLOW_PYTHON}" -c \
            "import json,sys; d=json.load(sys.stdin); print(d.get('tag_name','unknown'))" \
            2>/dev/null || echo "unknown")

        if [[ "${LATEST}" == "unknown" ]]; then
            echo "  Could not reach GitHub — skipping"
            exit 0
        fi

        if [[ "${CURRENT}" == "${LATEST}" ]]; then
            echo "  Already up to date (${CURRENT})"
            exit 0
        fi

        echo "  Update available: ${CURRENT} → ${LATEST}"

        "${WILLOW_PYTHON}" -c "
import sys, json
sys.path.insert(0, '${WILLOW_ROOT}')
from core.willow_store import WillowStore
store = WillowStore()
nodes = store.list('grove/nodes')
count = len(nodes)
store.put('grove/pending_alerts', 'update_available', {
    'type': 'update_available',
    'current': '${CURRENT}',
    'latest': '${LATEST}',
    'created_at': __import__('datetime').datetime.now().isoformat(),
})
print(f'  Notification queued for {count} known node(s)')
" 2>/dev/null || echo "  (Grove notify skipped — store unavailable)"
        ;;

    logs)
        _n="${2:-50}"
        _log=$(ls -t "${HOME}/.willow/logs/"*.log 2>/dev/null | head -1)
        if [[ -z "${_log}" ]]; then
            echo "No logs found in ~/.willow/logs/"
        else
            echo "=== ${_log} (last ${_n} lines) ==="
            tail -n "${_n}" "${_log}"
        fi
        ;;

    serve)
        _port="${2:-7777}"
        echo "Willow Grove — command server on 0.0.0.0:${_port}"
        echo "  Token: ${HOME}/.willow/grove_token"
        echo "  Share the token with trusted nodes: willow grove pair"
        echo ""
        PYTHONPATH="${WILLOW_ROOT}:${PYTHONPATH:-}" WILLOW_ROOT="${WILLOW_ROOT}" "${WILLOW_PYTHON}" "${WILLOW_ROOT}/core/grove_serve.py" --port "${_port}"
        ;;

    grove)
        _grove_sub="${2:-}"
        case "${_grove_sub}" in
            pair)
                TOKEN_FILE="${HOME}/.willow/grove_token"
                if [[ ! -f "${TOKEN_FILE}" ]]; then
                    # Generate token by starting server briefly
                    "${WILLOW_PYTHON}" -c "
import sys, secrets
from pathlib import Path
tp = Path.home() / '.willow' / 'grove_token'
tp.parent.mkdir(parents=True, exist_ok=True)
token = secrets.token_hex(32)
tp.write_text(token + '\n')
tp.chmod(0o600)
print(token)
" 2>/dev/null
                fi
                echo ""
                echo "  Grove token (share with trusted nodes):"
                echo ""
                echo "  $(grep -v '^$' "${TOKEN_FILE}" | head -1)"
                echo ""
                echo "  On the other node, save it with:"
                echo "    echo <token> > ~/.willow/grove_token && chmod 600 ~/.willow/grove_token"
                echo ""
                ;;
            send)
                _host="${3:-}"
                _cmd="${4:-}"
                if [[ -z "${_host}" || -z "${_cmd}" ]]; then
                    echo "Usage: willow.sh grove send <host:port> <command>"
                    echo "  e.g. willow.sh grove send 192.168.1.5:7777 status-all"
                    exit 1
                fi
                "${WILLOW_PYTHON}" -m core.grove_client "${_host}" "${_cmd}"
                ;;
            add)
                _addr="${3:-}"
                _pubkey="${4:-}"
                if [[ -z "${_addr}" || -z "${_pubkey}" ]]; then
                    echo "Usage: willow.sh grove add <user@host:port> <public_key_hex>"
                    exit 1
                fi
                echo "Willow Grove — adding contact: ${_addr}"
                "${WILLOW_PYTHON}" -c "
import sys
sys.path.insert(0, '${WILLOW_ROOT}')
try:
    from pathlib import Path
    from u2u.contacts import ContactStore
    store = ContactStore(Path.home() / '.willow' / 'grove_contacts.json')
    name = '${_addr}'.split('@')[0]
    contact = store.add('${_addr}', '${_pubkey}', name=name)
    print(f'  Added: {contact.name} ({contact.addr})')
    print(f'  Public key: {contact.public_key_hex[:16]}...')
    print()
    print('  Next: ask them to run: willow.sh grove knock ${_addr}')
except ImportError:
    print('  Grove u2u module not yet available — arriving in Phase 3.')
    print(f'  Contact saved to pending list for import later.')
    import json, datetime
    from pathlib import Path
    pending = Path.home() / '.willow' / 'grove_contacts_pending.json'
    contacts = json.loads(pending.read_text()) if pending.exists() else []
    contacts.append({'addr': '${_addr}', 'pubkey': '${_pubkey}', 'added_at': datetime.datetime.now().isoformat()})
    pending.write_text(json.dumps(contacts, indent=2))
    print(f'  Saved to {pending}')
"
                ;;
            *)
                echo "Usage: willow.sh grove [add <addr> <pubkey>]"
                exit 1
                ;;
        esac
        ;;

    litellm-start)
        echo "Willow 1.9 — starting LiteLLM gateway"
        CONFIG_FILE="${HOME}/.willow/litellm_config.yaml"
        "${WILLOW_PYTHON}" -c "
import sys, yaml, json
sys.path.insert(0, '${WILLOW_ROOT}')
from core.willow_store import WillowStore
from core.providers import build_litellm_config
store = WillowStore()
config = build_litellm_config(store)
with open('${CONFIG_FILE}', 'w') as f:
    yaml.dump(config, f)
print('  Config written to ${CONFIG_FILE}')
"
        litellm --config "${CONFIG_FILE}" --port 4000 &
        echo "  LiteLLM gateway running at http://localhost:4000"
        echo "  PID: $!"
        echo $! > "${HOME}/.willow/litellm.pid"
        ;;

    litellm-stop)
        PID_FILE="${HOME}/.willow/litellm.pid"
        if [[ -f "${PID_FILE}" ]]; then
            kill "$(cat "${PID_FILE}")" 2>/dev/null && echo "  LiteLLM stopped" || echo "  Already stopped"
            rm -f "${PID_FILE}"
        else
            pkill -f "litellm --config" 2>/dev/null && echo "  LiteLLM stopped" || echo "  Not running"
        fi
        ;;

    providers)
        _sub="${2:-list}"
        case "${_sub}" in
            list)
                "${WILLOW_PYTHON}" -c "
import sys
sys.path.insert(0, '${WILLOW_ROOT}')
from core.willow_store import WillowStore
from core.providers import get_providers, _mask_key
store = WillowStore()
providers = get_providers(store)
print('  Providers:')
for p in providers:
    status = '✓ ON ' if p['enabled'] else '✗ OFF'
    local = ' (local)' if p.get('local') else ''
    key_info = ''
    if not p.get('local') and p.get('api_key'):
        key_info = f' key={_mask_key(p[\"api_key\"])}'
    print(f'    [{status}] {p[\"name\"]}{local}{key_info}')
"
                ;;
            enable)
                PROVIDER="${3:-}"
                API_KEY="${4:-}"
                [[ -z "${PROVIDER}" ]] && echo "Usage: willow.sh providers enable <name> [api_key]" && exit 1
                "${WILLOW_PYTHON}" -c "
import sys
sys.path.insert(0, '${WILLOW_ROOT}')
from core.willow_store import WillowStore
from core.providers import enable_provider
store = WillowStore()
enable_provider(store, '${PROVIDER}', api_key='${API_KEY}' or None)
print(f'  Enabled: ${PROVIDER}')
"
                ;;
            disable)
                PROVIDER="${3:-}"
                [[ -z "${PROVIDER}" ]] && echo "Usage: willow.sh providers disable <name>" && exit 1
                "${WILLOW_PYTHON}" -c "
import sys
sys.path.insert(0, '${WILLOW_ROOT}')
from core.willow_store import WillowStore
from core.providers import disable_provider
store = WillowStore()
disable_provider(store, '${PROVIDER}')
print(f'  Disabled: ${PROVIDER}')
"
                ;;
            *)
                echo "Usage: willow.sh providers [list|enable <name> [key]|disable <name>]"
                ;;
        esac
        ;;

    *)
        echo "Usage: willow.sh [start|status|metabolic|update|export|purge <project>|backup|restore <path>|nuke|ledger [project]|valhalla|verify|start-all|stop-all|status-all|restart|check-updates|grove add <addr> <pubkey>|litellm-start|litellm-stop|providers [list|enable <name> [key]|disable <name>]]"
        exit 1
        ;;
esac
