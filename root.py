#!/usr/bin/env python3
"""
root.py — Sleipnir: 8-step idempotent install.
b17: SLP19  ΔΣ=42

Eight legs. Handles eight things that used to live in eight places.
Idempotent: run twice, nothing breaks. Run after reinstall: still works.

  python3 root.py                  — full install
  python3 root.py --skip-pg        — skip Postgres (already set up)
  python3 root.py --skip-socket    — skip systemd socket install
  python3 root.py --skip-gpg       — skip GPG key generation
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

WILLOW_ROOT = Path(__file__).parent
VERSION = "1.9.0"

# Ensure willow-1.9 is first on path — strip any willow-1.7 entries
sys.path = [str(WILLOW_ROOT)] + [p for p in sys.path if "willow-1.7" not in p]


def step_telemetry_init() -> None:
    """Write ~/.willow/telemetry.json with opt-in disabled by default."""
    tel_path = Path.home() / ".willow" / "telemetry.json"
    if tel_path.exists():
        return  # never overwrite user's choice
    tel_path.write_text(json.dumps({
        "enabled": False,
        "what": "Nothing is collected when disabled.",
        "to_enable": "Set enabled: true in this file.",
    }, indent=2))


def step_1_dirs() -> None:
    """Create ~/.willow/ structure and ~/SAFE/Applications/."""
    home = Path.home()
    for sub in (".willow", ".willow/store", ".willow/secrets", ".willow/logs"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    (home / "SAFE" / "Applications").mkdir(parents=True, exist_ok=True)


def step_2_deps() -> None:
    """Install Python dependencies from requirements.txt, streaming progress."""
    req = WILLOW_ROOT / "requirements.txt"
    if not req.exists():
        return

    pkgs = [l.strip() for l in req.read_text().splitlines() if l.strip() and not l.startswith("#")]
    total = len(pkgs)
    print(f"\n  Installing {total} packages...\n")

    for i, pkg in enumerate(pkgs, 1):
        print(f"  [{i}/{total}] {pkg}", flush=True)
        for flags in [[], ["--break-system-packages"]]:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"] + flags,
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                break
        else:
            print(f"    WARNING: {pkg} failed — {result.stderr.strip()[:120]}")


def step_3_gpg() -> str:
    """Return GPG fingerprint. Generate 4096-bit RSA key if none present."""
    result = subprocess.run(
        ["gpg", "--list-secret-keys", "--with-colons"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("fpr:"):
            fp = line.split(":")[9]
            _write_fingerprint(fp)
            return fp

    batch = (
        "%no-protection\nKey-Type: RSA\nKey-Length: 4096\n"
        "Name-Real: Willow User\nName-Email: willow@localhost\n"
        "Expire-Date: 0\n%commit\n"
    )
    subprocess.run(["gpg", "--batch", "--gen-key"], input=batch, text=True, check=True)

    result = subprocess.run(
        ["gpg", "--list-secret-keys", "--with-colons"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("fpr:"):
            fp = line.split(":")[9]
            _write_fingerprint(fp)
            return fp

    raise RuntimeError("GPG key generated but fingerprint not found")


def _write_fingerprint(fp: str) -> None:
    export_line = f'\nexport WILLOW_PGP_FINGERPRINT="{fp}"\n'
    for profile in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        if profile.exists():
            text = profile.read_text()
            if "WILLOW_PGP_FINGERPRINT" not in text:
                profile.write_text(text + export_line)
        elif profile.name == ".bashrc":
            profile.write_text(export_line.lstrip())


def step_4_vault() -> Path:
    """Create Fernet vault at ~/.willow/vault.db."""
    from cryptography.fernet import Fernet
    home = Path.home()
    key_path = home / ".willow" / ".master.key"
    vault_path = home / ".willow" / "vault.db"

    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        key_path.chmod(0o600)

    conn = sqlite3.connect(str(vault_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS credentials (
            name TEXT PRIMARY KEY, env_key TEXT, value_enc BLOB
        )
    """)
    conn.commit()
    conn.close()
    return vault_path


def _load_pg_bridge():
    """Load pg_bridge from willow-1.9 explicitly — no path ambiguity."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pg_bridge_19", WILLOW_ROOT / "core" / "pg_bridge.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def step_5_schema(skip_pg: bool = False) -> None:
    """Initialize Postgres schema via pg_bridge."""
    if skip_pg:
        return
    pgb = _load_pg_bridge()
    pgb.PgBridge()
    print("  Postgres: schema initialized")


def step_6_socket(skip_socket: bool = False) -> None:
    """Install systemd user socket and service units."""
    if skip_socket:
        return
    systemd_user = Path.home() / ".config" / "systemd" / "user"
    systemd_user.mkdir(parents=True, exist_ok=True)
    for unit in ("willow-metabolic.socket", "willow-metabolic.service"):
        src = WILLOW_ROOT / "systemd" / unit
        dst = systemd_user / unit
        if src.exists():
            shutil.copy2(src, dst)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True,
                       capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "willow-metabolic.socket"],
            check=True, capture_output=True,
        )
        print("  Metabolic socket: enabled")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  Metabolic socket: systemd not available (skip)")

    # Grove MCP server — persistent streamable-HTTP on port 8765
    grove_src = WILLOW_ROOT / "systemd" / "grove-mcp.service"
    if grove_src.exists():
        shutil.copy2(grove_src, systemd_user / "grove-mcp.service")
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True,
                           capture_output=True)
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "grove-mcp.service"],
                check=True, capture_output=True,
            )
            print("  Grove MCP: enabled")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("  Grove MCP: systemd not available (skip)")


def step_7_cmb(skip_pg: bool = False) -> None:
    """Write CMB atom — first session anchor, never composted."""
    if skip_pg:
        return
    import datetime
    pgb = _load_pg_bridge()
    bridge = pgb.PgBridge()
    bridge.cmb_put("cmb_origin", {
        "event": "system_birth",
        "version": VERSION,
        "willow_root": str(WILLOW_ROOT),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "note": "The initial conditions. Snorri Sturluson would approve.",
    })
    print("  CMB atom: written (never composted)")


def step_10_kb_seed(skip_pg: bool = False) -> None:
    """Seed KB with neutral starter atoms — skills, commands, architecture."""
    if skip_pg:
        return
    pgb = _load_pg_bridge()
    bridge = pgb.PgBridge()
    from core.seed_kb import seed_kb
    count = seed_kb(bridge, skip_existing=True)
    print(f"  KB seed: {count} atoms written")


def step_8_version_pin() -> None:
    """Write ~/.willow/version — Sleipnir won't re-run after this."""
    version_path = Path.home() / ".willow" / "version"
    version_path.write_text(VERSION + "\n")


def step_9_path() -> None:
    """Symlink willow.sh and willow-termux.sh into ~/.local/bin/."""
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    for src_name, dst_name in [("willow.sh", "willow"), ("willow-termux.sh", "willow-termux")]:
        src = WILLOW_ROOT / src_name
        if not src.exists():
            continue
        dst = bin_dir / dst_name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src)
        dst.chmod(0o755)

    # Ensure ~/.local/bin is on PATH in shell profiles
    export_line = '\nexport PATH="$HOME/.local/bin:$PATH"\n'
    for profile in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        if profile.exists():
            if ".local/bin" not in profile.read_text():
                with profile.open("a") as f:
                    f.write(export_line)


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


def _windows_username() -> str | None:
    try:
        mnt_c_users = Path("/mnt/c/Users")
        if not mnt_c_users.exists():
            return None
        users = [d.name for d in mnt_c_users.iterdir()
                 if d.is_dir() and d.name not in ("Public", "Default", "All Users")]
        return users[0] if len(users) == 1 else None
    except Exception:
        return None


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


def step_grove_identity() -> Path:
    """Generate Grove Ed25519 identity key at ~/.willow/identity.key if not present."""
    key_path = Path.home() / ".willow" / "identity.key"
    if key_path.exists():
        print(f"  Grove identity already exists at {key_path}")
        return key_path
    sys.path.insert(0, str(WILLOW_ROOT))
    try:
        from u2u.identity import Identity
        ident = Identity.generate(key_path)
        print(f"  Grove identity created: {key_path}")
        print(f"  Public key: {ident.public_key_hex[:32]}...")
        print(f"  Share your public key with trusted contacts to connect via Grove.")
    except ImportError:
        print("  Grove u2u module not yet available — arriving in Phase 3. Skipping.")
    return key_path


def _is_termux() -> bool:
    """Detect Termux environment."""
    return (
        "com.termux" in os.environ.get("PREFIX", "")
        or Path("/data/data/com.termux").exists()
        or "termux" in os.environ.get("TERMUX_VERSION", "").lower()
    )


def step_termux_pg() -> None:
    """Print Termux-specific Postgres setup instructions if not already running."""
    try:
        import psycopg2
        psycopg2.connect(
            dbname="postgres",
            user=os.environ.get("USER", ""),
        ).close()
        return  # already running
    except Exception:
        pass
    print()
    print("  ┌─ Termux Postgres setup ───────────────────────────────┐")
    print("  │  Run these once, then re-run root.py:                 │")
    print("  │    pkg install postgresql                              │")
    print("  │    initdb $PREFIX/var/lib/postgresql                  │")
    print("  │    pg_ctl -D $PREFIX/var/lib/postgresql start         │")
    print("  │    createdb willow_19                                  │")
    print("  └───────────────────────────────────────────────────────┘")
    print()


def step_termux_process_manager() -> None:
    """Write a simple start/stop shell script as systemd substitute."""
    script = WILLOW_ROOT / "willow-termux.sh"
    content = """\
#!/usr/bin/env bash
# willow-termux.sh — Termux service manager (systemd substitute)
# Run in a Termux session; use tmux or multiple tabs for background services.

WILLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cmd="${1:-help}"

case "$cmd" in
    start)
        echo "Starting Willow services..."
        # Postgres
        pg_ctl -D "$PREFIX/var/lib/postgresql" status > /dev/null 2>&1 \\
            || pg_ctl -D "$PREFIX/var/lib/postgresql" start -l ~/.willow/logs/postgres.log
        echo "  [✓] postgres"
        # Ollama (if installed)
        if command -v ollama > /dev/null 2>&1; then
            pgrep -f "ollama serve" > /dev/null || (ollama serve > ~/.willow/logs/ollama.log 2>&1 &)
            echo "  [✓] ollama"
        else
            echo "  [–] ollama not installed (optional)"
        fi
        echo "  Done. Run: python3 ${WILLOW_ROOT}/willow.sh to start the MCP server."
        ;;
    stop)
        pg_ctl -D "$PREFIX/var/lib/postgresql" stop 2>/dev/null && echo "  [↓] postgres" || true
        pkill -f "ollama serve" 2>/dev/null && echo "  [↓] ollama" || true
        ;;
    status)
        pg_ctl -D "$PREFIX/var/lib/postgresql" status 2>/dev/null || echo "  postgres: stopped"
        pgrep -f "ollama serve" > /dev/null && echo "  ollama:   running" || echo "  ollama:   stopped"
        ;;
    *)
        echo "Usage: willow-termux.sh [start|stop|status]"
        ;;
esac
"""
    script.write_text(content)
    script.chmod(0o755)
    print(f"  Written: {script}")
    print("  Use willow-termux.sh start/stop/status instead of systemctl")


def sleipnir(
    skip_pg: bool = False,
    skip_socket: bool = False,
    skip_gpg: bool = False,
    no_chain: bool = False,
    termux: bool = False,
) -> None:
    """Run all install steps. Idempotent."""
    if termux or _is_termux():
        termux = True
        skip_socket = True
        skip_gpg = True

    print()
    print(f"  Willow {VERSION} — Sleipnir running")
    if termux:
        print("  Mode: Termux (Android)")
    print(f"  System: {WILLOW_ROOT}")
    print(f"  User data: ~/.willow/  (yours — delete it and you're gone)")
    print()

    steps = [
        ("Directories",      lambda: step_1_dirs()),
        ("Telemetry config", lambda: step_telemetry_init()),
        ("Dependencies",     lambda: step_2_deps()),
        ("GPG key",          lambda: (None if skip_gpg else step_3_gpg())),
        ("Vault",            lambda: step_4_vault()),
        ("Postgres schema",  lambda: (step_termux_pg() or step_5_schema(skip_pg)) if termux else step_5_schema(skip_pg)),
        ("Metabolic socket", lambda: step_termux_process_manager() if termux else step_6_socket(skip_socket)),
        ("CMB atom",         lambda: step_7_cmb(skip_pg)),
        ("KB seed",          lambda: step_10_kb_seed(skip_pg)),
        ("Version pin",      lambda: step_8_version_pin()),
        ("PATH — willow",    lambda: step_9_path()),
        ("Grove identity",   lambda: step_grove_identity()),
        ("WSL launcher",     lambda: (None if termux else step_wsl_launcher())),
    ]

    for label, fn in steps:
        print(f"  {label}...", end=" ", flush=True)
        fn()
        print("done")

    if no_chain or termux:
        print()
        if termux:
            print()
            print("  ┌─────────────────────────────────────────────────────┐")
            print("  │                                                     │")
            print("  │   🌿  Welcome to Willow                             │")
            print("  │                                                     │")
            print("  │   Your local-first AI stack is installed.           │")
            print("  │   Everything runs on your device. You own it.       │")
            print("  │                                                     │")
            print("  │   Ollama    — local inference, no API key needed    │")
            print("  │   Postgres  — your knowledge graph                  │")
            print("  │   Grove     — your dashboard                        │")
            print("  │                                                     │")
            print("  │   Next:                                             │")
            print("  │     willow-termux start     start services          │")
            print("  │     willow status-all       check everything        │")
            print("  │     willow health           run diagnostics         │")
            print("  │                                                     │")
            print("  │   Docs:  github.com/rudi193-cmd/willow-1.9         │")
            print("  │                                                     │")
            print("  │   👋  Hello LLM Physics Discord —                   │")
            print("  │       running Willow on a phone. Yes, really.       │")
            print("  │                                                     │")
            print("  └─────────────────────────────────────────────────────┘")
            print()
        return
    print()
    shoot = WILLOW_ROOT / "shoot.py"
    if shoot.exists():
        print("  Handing off to shoot.py...")
        print()
        os.execv(sys.executable, [sys.executable, str(shoot)])
    else:
        print("  Ready. Run manually:")
        print(f"    python3 {shoot}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Sleipnir — Willow 1.9 install")
    parser.add_argument("--skip-pg", action="store_true")
    parser.add_argument("--skip-socket", action="store_true")
    parser.add_argument("--skip-gpg", action="store_true")
    parser.add_argument("--no-chain", action="store_true")
    parser.add_argument("--termux", action="store_true",
                        help="Termux/Android mode: skip systemd, GPG, WSL; write willow-termux.sh")
    args = parser.parse_args()
    sleipnir(skip_pg=args.skip_pg, skip_socket=args.skip_socket,
             skip_gpg=args.skip_gpg, no_chain=args.no_chain, termux=args.termux)


if __name__ == "__main__":
    main()
