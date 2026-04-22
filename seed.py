#!/usr/bin/env python3
"""
seed.py — Sleipnir: 8-step idempotent install.
b17: SLP19  ΔΣ=42

Eight legs. Handles eight things that used to live in eight places.
Idempotent: run twice, nothing breaks. Run after reinstall: still works.

  python3 seed.py                  — full install
  python3 seed.py --skip-pg        — skip Postgres (already set up)
  python3 seed.py --skip-socket    — skip systemd socket install
  python3 seed.py --skip-gpg       — skip GPG key generation
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


def step_1_dirs() -> None:
    """Create ~/.willow/ structure and ~/SAFE/Applications/."""
    home = Path.home()
    for sub in (".willow", ".willow/store", ".willow/secrets", ".willow/logs"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    (home / "SAFE" / "Applications").mkdir(parents=True, exist_ok=True)


def step_2_deps() -> None:
    """Install Python dependencies from requirements.txt."""
    req = WILLOW_ROOT / "requirements.txt"
    if not req.exists():
        return
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req), "-q"],
            check=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req), "-q",
             "--break-system-packages"],
            check=True,
        )


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


def step_5_schema(skip_pg: bool = False) -> None:
    """Initialize Postgres schema via pg_bridge."""
    if skip_pg:
        return
    sys.path.insert(0, str(WILLOW_ROOT))
    import importlib
    import core.pg_bridge as pgb
    importlib.reload(pgb)
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


def step_7_cmb(skip_pg: bool = False) -> None:
    """Write CMB atom — first session anchor, never composted."""
    if skip_pg:
        return
    import datetime
    sys.path.insert(0, str(WILLOW_ROOT))
    import importlib
    import core.pg_bridge as pgb
    importlib.reload(pgb)
    bridge = pgb.PgBridge()
    bridge.cmb_put("cmb_origin", {
        "event": "system_birth",
        "version": VERSION,
        "willow_root": str(WILLOW_ROOT),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "note": "The initial conditions. Snorri Sturluson would approve.",
    })
    print("  CMB atom: written (never composted)")


def step_8_version_pin() -> None:
    """Write ~/.willow/version — Sleipnir won't re-run after this."""
    version_path = Path.home() / ".willow" / "version"
    version_path.write_text(VERSION + "\n")


def sleipnir(
    skip_pg: bool = False,
    skip_socket: bool = False,
    skip_gpg: bool = False,
) -> None:
    """Run all 8 steps. Idempotent."""
    print()
    print(f"  Willow {VERSION} — Sleipnir running")
    print(f"  System: {WILLOW_ROOT}")
    print(f"  User data: ~/.willow/  (yours — delete it and you're gone)")
    print()

    steps = [
        ("Directories",      lambda: step_1_dirs()),
        ("Dependencies",     lambda: step_2_deps()),
        ("GPG key",          lambda: (None if skip_gpg else step_3_gpg())),
        ("Vault",            lambda: step_4_vault()),
        ("Postgres schema",  lambda: step_5_schema(skip_pg)),
        ("Metabolic socket", lambda: step_6_socket(skip_socket)),
        ("CMB atom",         lambda: step_7_cmb(skip_pg)),
        ("Version pin",      lambda: step_8_version_pin()),
    ]

    for label, fn in steps:
        print(f"  {label}...", end=" ", flush=True)
        fn()
        print("done")

    print()
    print("  Ready. Run boot.py for the full onboarding experience.")
    print()


def main():
    parser = argparse.ArgumentParser(description="Sleipnir — Willow 1.9 install")
    parser.add_argument("--skip-pg", action="store_true")
    parser.add_argument("--skip-socket", action="store_true")
    parser.add_argument("--skip-gpg", action="store_true")
    args = parser.parse_args()
    sleipnir(skip_pg=args.skip_pg, skip_socket=args.skip_socket,
             skip_gpg=args.skip_gpg)


if __name__ == "__main__":
    main()
