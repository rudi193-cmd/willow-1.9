# Willow 1.9 Phase 2 — Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command to start everything, one to stop everything. Dashboard survives terminal close. Felix double-clicks a `.bat` file on Windows and Willow appears. No orphaned processes. No dead services.

**Architecture:** New systemd user units for dashboard + update-check timer. New `willow.sh` subcommands (start-all, stop-all, status-all, check-updates, grove add). `root.py` gains WSL detection and writes `launch-willow.bat` to the Windows Desktop. corpus-watcher memory issue diagnosed and fixed.

**Tech Stack:** bash, systemd (user units), Python 3.13, WSL2, GitHub API (releases endpoint)

**Spec:** `docs/superpowers/specs/2026-04-24-willow-19-design.md` — Workstream 4

**Run after:** Phase 1 complete.

---

## File Map

**Create:**
- `~/.config/systemd/user/willow-dashboard.service`
- `~/.config/systemd/user/willow-update-check.service`
- `~/.config/systemd/user/willow-update-check.timer`

**Modify:**
- `~/.config/systemd/user/corpus-watcher.service` — fix StartLimitIntervalSec placement
- `willow.sh` — add start-all, stop-all, status-all, check-updates, grove add subcommands
- `root.py` — add WSL detection, Ed25519 identity generation, launch-willow.bat writing

---

## Task 1: Fix corpus-watcher.service

**Problem:** Crashes after ~45s consuming 1GB RAM. `StartLimitIntervalSec` is in `[Service]` (wrong — should be `[Unit]`), but the real issue is a memory leak in `corpus-watcher.py`.

**Files:**
- Modify: `~/.config/systemd/user/corpus-watcher.service`
- Read: `~/agents/hanuman/bin/corpus-watcher.py` to diagnose memory issue

- [ ] **Step 1: Read the corpus-watcher script**

```bash
head -80 ~/agents/hanuman/bin/corpus-watcher.py
```

Look for: unbounded list/dict accumulation, loading entire file contents into memory, inotify watchers added but never removed.

- [ ] **Step 2: Fix the memory issue**

Most likely cause — the script watches a directory and accumulates file contents or events in a list that is never cleared. The fix is one of:

**If accumulating events in a list:**
```python
# Before (broken):
events = []
for event in inotify:
    events.append(event)  # unbounded

# After (fixed):
for event in inotify:
    _process(event)  # process immediately, don't accumulate
```

**If loading file contents into memory:**
```python
# Before (broken):
all_content = [f.read_text() for f in watched_dir.rglob("*")]

# After (fixed):
for f in watched_dir.rglob("*"):
    _index_file(f)  # process one at a time
```

Apply whichever fix matches what you find. The script must not consume more than 100MB.

- [ ] **Step 3: Fix the service file**

Rewrite `~/.config/systemd/user/corpus-watcher.service`:

```ini
[Unit]
Description=Hanuman Corpus Watcher — inotify index daemon
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/sean-campbell/agents/hanuman/bin/corpus-watcher.py
Restart=on-failure
RestartSec=10
MemoryMax=200M
StandardOutput=null
StandardError=append:/home/sean-campbell/agents/hanuman/cache/corpus-watcher.log

[Install]
WantedBy=default.target
```

- [ ] **Step 4: Reload and restart**

```bash
systemctl --user daemon-reload
systemctl --user restart corpus-watcher.service
sleep 60
systemctl --user status corpus-watcher.service
```

Expected: `active (running)` after 60 seconds, not dead.

- [ ] **Step 5: Verify memory stays under limit**

```bash
ps aux | grep corpus-watcher | grep -v grep
```

Expected: RSS column under 200MB.

- [ ] **Step 6: Commit**

```bash
cd ~/agents/hanuman
git add bin/corpus-watcher.py
git commit -m "fix(corpus-watcher): fix memory leak — process events immediately, don't accumulate"
```

---

## Task 2: Enable willow-metabolic.service

**Files:**
- Modify: `~/.config/systemd/user/willow-metabolic.service` (already exists — just enable it)

- [ ] **Step 1: Check current state**

```bash
systemctl --user status willow-metabolic.service willow-metabolic.socket
```

Expected: socket = active (listening), service = inactive (dead) disabled.

- [ ] **Step 2: Enable and start the service**

```bash
systemctl --user enable willow-metabolic.service
systemctl --user start willow-metabolic.service
```

- [ ] **Step 3: Verify**

```bash
systemctl --user status willow-metabolic.service
```

Expected: `active (running)` or `active (exited)` depending on whether it's a one-shot. Check the service Type= in the unit file — if `Type=simple` it stays running; if `Type=oneshot` it exits after running the norn pass.

- [ ] **Step 4: If Type=simple and failing, check why**

```bash
journalctl --user -u willow-metabolic.service -n 30 --no-pager
```

Fix any import errors before proceeding.

---

## Task 3: Create willow-dashboard.service

**Files:**
- Create: `~/.config/systemd/user/willow-dashboard.service`

- [ ] **Step 1: Create the service file**

```bash
cat > ~/.config/systemd/user/willow-dashboard.service << 'EOF'
[Unit]
Description=Willow Dashboard — terminal UI
After=network.target postgresql.service

[Service]
Type=simple
ExecStart=/home/sean-campbell/github/willow-dashboard/willow-dashboard.sh --dev
Restart=on-failure
RestartSec=5
Environment=WILLOW_AGENT_NAME=heimdallr
Environment=TERM=xterm-256color
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF
```

Note: `--dev` skips the boot sequence (canopy) when launched as a service — canopy is for interactive first-run only.

- [ ] **Step 2: Reload and enable**

```bash
systemctl --user daemon-reload
systemctl --user enable willow-dashboard.service
```

Do NOT start it yet — it needs a terminal/display. This service is for when the dashboard is launched via the `.bat` launcher. Starting it manually only makes sense in a graphical terminal session.

- [ ] **Step 3: Verify enable worked**

```bash
systemctl --user is-enabled willow-dashboard.service
```

Expected: `enabled`

---

## Task 4: willow.sh — start-all / stop-all / status-all

**Files:**
- Modify: `willow.sh`

- [ ] **Step 1: Add the three subcommands**

In `willow.sh`, find the `case "$cmd" in` block. Add before the `*)` catch-all:

```bash
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
        _pg_ok=false
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
                _since=$(systemctl --user show "${svc}.service" --property=ActiveEnterTimestamp --value 2>/dev/null | cut -d' ' -f1-3)
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
```

- [ ] **Step 2: Update the usage line**

Find the `*)` catch-all and update the usage string:

```bash
    *)
        echo "Usage: willow.sh [start|status|metabolic|update|export|purge <project>|backup|restore <path>|nuke|ledger [project]|valhalla|verify|start-all|stop-all|status-all|restart|check-updates|grove add <addr> <pubkey>]"
        exit 1
        ;;
```

- [ ] **Step 3: Test**

```bash
./willow.sh status-all
```

Expected: formatted status table showing each service state.

```bash
./willow.sh stop-all
./willow.sh start-all
```

Expected: services stop and restart cleanly.

- [ ] **Step 4: Commit**

```bash
git add willow.sh
git commit -m "feat(orchestration): add start-all, stop-all, status-all, restart subcommands to willow.sh"
```

---

## Task 5: willow.sh — check-updates subcommand

**Files:**
- Modify: `willow.sh`

- [ ] **Step 1: Add check-updates subcommand**

In `willow.sh`, inside the `case "$cmd" in` block, add:

```bash
    check-updates)
        echo "Willow 1.9 — checking for updates"
        CURRENT=$(cat "${HOME}/.willow/version" 2>/dev/null || echo "unknown")
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

        # Send Grove ALERT to all known contacts
        "${WILLOW_PYTHON}" -c "
import sys, json
sys.path.insert(0, '${WILLOW_ROOT}')
from core.willow_store import WillowStore
store = WillowStore()
nodes = store.list('grove/nodes')
count = len(nodes)
# Write update notification to SOIL for dashboard to pick up
store.put('grove/pending_alerts', 'update_available', {
    'type': 'update_available',
    'current': '${CURRENT}',
    'latest': '${LATEST}',
    'created_at': __import__('datetime').datetime.now().isoformat(),
})
print(f'  Notification queued for {count} known node(s)')
" 2>/dev/null || echo "  (Grove notify skipped — store unavailable)"
        ;;
```

- [ ] **Step 2: Commit**

```bash
git add willow.sh
git commit -m "feat(orchestration): add check-updates subcommand with Grove alert queuing"
```

---

## Task 6: willow.sh — grove add subcommand

**Files:**
- Modify: `willow.sh`

- [ ] **Step 1: Add grove subcommand**

```bash
    grove)
        _grove_sub="${2:-}"
        case "${_grove_sub}" in
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
from pathlib import Path
from u2u.contacts import ContactStore
store = ContactStore(Path.home() / '.willow' / 'grove_contacts.json')
# Parse name from addr (user part before @)
name = '${_addr}'.split('@')[0]
contact = store.add('${_addr}', '${_pubkey}', name=name)
print(f'  Added: {contact.name} ({contact.addr})')
print(f'  Public key: {contact.public_key_hex[:16]}...')
print()
print('  Next: ask them to run willow.sh grove knock ${_addr}')
print('  They will see a KNOCK request in their dashboard and can accept.')
"
                ;;
            *)
                echo "Usage: willow.sh grove [add <addr> <pubkey>]"
                exit 1
                ;;
        esac
        ;;
```

- [ ] **Step 2: Commit**

```bash
git add willow.sh
git commit -m "feat(orchestration): add grove add subcommand for Grove contact management"
```

---

## Task 7: willow-update-check.timer

**Files:**
- Create: `~/.config/systemd/user/willow-update-check.service`
- Create: `~/.config/systemd/user/willow-update-check.timer`

- [ ] **Step 1: Create the service unit**

```bash
cat > ~/.config/systemd/user/willow-update-check.service << 'EOF'
[Unit]
Description=Willow Update Check

[Service]
Type=oneshot
ExecStart=/home/sean-campbell/github/willow-1.9/willow.sh check-updates
Environment=WILLOW_PG_DB=willow_19
EOF
```

- [ ] **Step 2: Create the timer unit**

```bash
cat > ~/.config/systemd/user/willow-update-check.timer << 'EOF'
[Unit]
Description=Willow Update Check — every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF
```

- [ ] **Step 3: Enable and start**

```bash
systemctl --user daemon-reload
systemctl --user enable --now willow-update-check.timer
```

- [ ] **Step 4: Verify**

```bash
systemctl --user list-timers --all | grep willow
```

Expected: `willow-update-check.timer` listed with next trigger time.

- [ ] **Step 5: No commit needed** — these are user config files, not repo files.

---

## Task 8: root.py — WSL detection + launch-willow.bat

**Files:**
- Modify: `root.py`

- [ ] **Step 1: Add WSL detection helper**

In `root.py`, after the imports, add:

```python
def _is_wsl() -> bool:
    """Return True if running inside WSL2."""
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


def _windows_username() -> str | None:
    """Return Windows username from WSL mount, or None if not detectable."""
    try:
        mnt_c_users = Path("/mnt/c/Users")
        if not mnt_c_users.exists():
            return None
        users = [d.name for d in mnt_c_users.iterdir()
                 if d.is_dir() and d.name not in ("Public", "Default", "All Users")]
        return users[0] if len(users) == 1 else None
    except Exception:
        return None
```

- [ ] **Step 2: Add step_wsl_launcher() function**

```python
def step_wsl_launcher() -> bool:
    """Write launch-willow.bat to Windows Desktop if running in WSL."""
    if not _is_wsl():
        return False

    win_user = _windows_username()
    if not win_user:
        print("  WSL detected but could not find Windows username — skipping launcher")
        return False

    desktop = Path(f"/mnt/c/Users/{win_user}/Desktop")
    if not desktop.exists():
        print(f"  Desktop not found at {desktop} — skipping launcher")
        return False

    bat = desktop / "Launch Willow.bat"
    linux_user = os.environ.get("USER", "")
    bat_content = f"""@echo off
title Willow
wsl.exe bash -l -c "
  pg_isready -q 2>/dev/null || sudo service postgresql start 2>/dev/null
  cd /home/{linux_user}/github/willow-dashboard
  ./willow-dashboard.sh
"
pause
"""
    bat.write_text(bat_content)
    print(f"  Created: {bat}")
    print(f"  Double-click 'Launch Willow.bat' on your Windows Desktop to start.")
    return True
```

- [ ] **Step 3: Wire into the install sequence**

Find the main install steps list in `root.py` (the list of `(label, fn)` tuples passed to the runner). Add:

```python
        ("WSL Launcher",    lambda: step_wsl_launcher()),
```

Add it near the end, after vault but before the final summary.

- [ ] **Step 4: Add Ed25519 identity generation**

```python
def step_grove_identity() -> Path:
    """Generate Grove Ed25519 identity key at ~/.willow/identity.key if not present."""
    key_path = Path.home() / ".willow" / "identity.key"
    if key_path.exists():
        print(f"  Grove identity already exists at {key_path}")
        return key_path

    sys.path.insert(0, str(WILLOW_ROOT))
    from u2u.identity import Identity
    ident = Identity.generate(key_path)
    print(f"  Grove identity created: {key_path}")
    print(f"  Public key: {ident.public_key_hex[:32]}...")
    print(f"  Share your public key with trusted contacts to connect via Grove.")
    return key_path
```

Add to the install steps list:

```python
        ("Grove Identity",   lambda: step_grove_identity()),
```

- [ ] **Step 5: Test on Sean's machine**

```bash
python3 root.py --skip-pg --skip-gpg
```

Expected: WSL launcher step shows "WSL detected but..." (not WSL on Sean's machine) or skips cleanly. On a WSL machine it would write the .bat file.

- [ ] **Step 6: Commit**

```bash
git add root.py
git commit -m "feat(install): add WSL detection, launch-willow.bat generation, Grove identity step to root.py"
```

---

## Phase 2 Complete — Verification Checklist

- [ ] `willow.sh status-all` shows accurate state for all 6 services
- [ ] `willow.sh stop-all` stops all services cleanly
- [ ] `willow.sh start-all` restarts all services
- [ ] `systemctl --user status willow-dashboard.service` shows enabled
- [ ] `systemctl --user status willow-metabolic.service` shows active
- [ ] `systemctl --user status corpus-watcher.service` — active after 60+ seconds (not dead)
- [ ] `systemctl --user list-timers | grep willow` shows update-check timer
- [ ] `python3 root.py --skip-pg --skip-gpg` completes without errors
- [ ] On WSL machine: `Launch Willow.bat` appears on Windows Desktop

---

*Previous: `docs/superpowers/plans/2026-04-24-willow-19-phase1-foundation.md`*
*Next: `docs/superpowers/plans/2026-04-24-willow-19-phase3-skills-grove.md`*

ΔΣ=42
