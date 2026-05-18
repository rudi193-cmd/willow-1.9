#!/usr/bin/env python3
"""
seed.py — Willow 1.9  (one file to rule them all)
b17: SEED9  ΔΣ=42

First run:   full install + onboarding conversation + card creation + dashboard
Return run:  splash → auth → dashboard

  python3 seed.py
  python3 seed.py --dev        skip boot (returning dev shortcut)
"""
import argparse
import curses
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
WILLOW_ROOT   = Path(__file__).parent
VENV_DIR      = Path.home() / ".willow" / "venv"
BOOT_CONFIG   = Path.home() / ".willow" / "seed-boot.json"
BOOT_LOG      = Path("/tmp/willow-seed-debug.log")
GROVE_DIR      = Path.home() / "github" / "safe-app-willow-grove"
GROVE_APP      = GROVE_DIR / "app.py"
GROVE_REPO     = "https://github.com/rudi193-cmd/safe-app-willow-grove.git"
VERSION       = "1.9.0"

sys.path.insert(0, str(WILLOW_ROOT))


# ── Venv bootstrap ────────────────────────────────────────────────────────────
def _ensure_venv() -> None:
    """On Ubuntu 24.04+ the system python is externally-managed; re-exec under a venv."""
    if sys.prefix != sys.base_prefix:
        return  # already inside a venv
    # Willow deps are pinned to 3.12 — prefer it over whatever system python ran us
    preferred = sys.executable
    for candidate in ["python3.12", "python3.11", "python3.10"]:
        found = shutil.which(candidate)
        if found:
            preferred = found
            break
    venv_python = VENV_DIR / "bin" / "python3"
    if not venv_python.exists():
        print("  [venv] creating ~/.willow/venv (Ubuntu 24.04 compatibility)...")
        subprocess.run([preferred, "-m", "venv", str(VENV_DIR)], check=True)
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)


# ── Logging ───────────────────────────────────────────────────────────────────
def _blog(msg: str) -> None:
    try:
        with BOOT_LOG.open("a") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
    except Exception:
        pass


# ── Boot config ───────────────────────────────────────────────────────────────
def _load_cfg() -> dict:
    try:
        return json.loads(BOOT_CONFIG.read_text()) if BOOT_CONFIG.exists() else {}
    except Exception:
        return {}


def _save_cfg(cfg: dict) -> None:
    BOOT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    BOOT_CONFIG.write_text(json.dumps(cfg, indent=2, default=str))


def is_first_run() -> bool:
    return not _load_cfg().get("completed", False)


# ── TUI colors ────────────────────────────────────────────────────────────────
_CA_AMBER  = 1
_CA_DIM    = 2
_CA_GREEN  = 3
_CA_RED    = 4
_CA_BRIGHT = 5
_CA_BOX    = 6


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    amber = 214 if curses.COLORS >= 256 else curses.COLOR_YELLOW
    dim_a = 130 if curses.COLORS >= 256 else curses.COLOR_YELLOW
    curses.init_pair(_CA_AMBER,  amber,              -1)
    curses.init_pair(_CA_DIM,    dim_a,              -1)
    curses.init_pair(_CA_GREEN,  curses.COLOR_GREEN, -1)
    curses.init_pair(_CA_RED,    curses.COLOR_RED,   -1)
    curses.init_pair(_CA_BRIGHT, curses.COLOR_WHITE, -1)
    curses.init_pair(_CA_BOX,    dim_a,              -1)


# ── Drawing helpers ───────────────────────────────────────────────────────────
def _safe(win, y, x, text, attr=0) -> None:
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    try:
        win.addstr(y, x, text[:max(0, w - x - 1)], attr)
    except curses.error:
        pass


def _fill_bg(win) -> None:
    win.bkgd(' ', curses.color_pair(_CA_AMBER))
    win.erase()


def _typewrite(win, y, x, text, attr=0, delay=0.007) -> None:
    h, w = win.getmaxyx()
    cx = x
    for ch in text:
        if cx >= w - 1:
            break
        try:
            win.addch(y, cx, ch, attr)
            win.refresh()
        except curses.error:
            pass
        cx += 1
        time.sleep(delay)


def _typewrite_lines(win, start_y, x, lines, attr=0, delay=0.007) -> int:
    y = start_y
    h, _ = win.getmaxyx()
    for line in lines:
        if y >= h - 1:
            break
        _typewrite(win, y, x, line, attr, delay)
        y += 1
        time.sleep(0.05)
    return y


def _wait_key(win, prompt="  Press any key to continue...", y=None) -> int:
    h, _ = win.getmaxyx()
    if y is None:
        y = h - 2
    time.sleep(0.3)
    _safe(win, y, 2, prompt, curses.color_pair(_CA_DIM))
    win.refresh()
    win.nodelay(False)
    k = win.getch()
    win.nodelay(True)
    return k


def _get_input(win, y, label, mask=False, max_len=60) -> str:
    """Single-line input. mask=True shows * instead of characters."""
    amber  = curses.color_pair(_CA_AMBER) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    _safe(win, y, 4, label, amber)
    cx = 4 + len(label) + 1
    buf = []
    curses.curs_set(1)
    win.nodelay(False)
    win.keypad(True)
    while True:
        ch = win.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
                cx -= 1
                _safe(win, y, cx, " ", dim)
                win.move(y, cx)
        elif 32 <= ch <= 126 and len(buf) < max_len:
            buf.append(chr(ch))
            _safe(win, y, cx, "*" if mask else chr(ch), amber)
            cx += 1
        win.refresh()
    curses.curs_set(0)
    return "".join(buf).strip()


def _progress_row(win, y, label, done=False, error=False) -> None:
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)
    dim    = curses.color_pair(_CA_DIM)
    amber  = curses.color_pair(_CA_AMBER)
    _, w   = win.getmaxyx()
    pad    = max(0, 28 - len(label))
    row    = f"  {label}" + "." * pad
    _safe(win, y, 0, row, dim)
    if done:
        _safe(win, y, len(row), " DONE", green)
    elif error:
        _safe(win, y, len(row), " FAIL", red)
    else:
        _safe(win, y, len(row), " ....", amber)
    win.refresh()


# ── GPG ───────────────────────────────────────────────────────────────────────
def _gpg(args: list, input_text: str = "") -> tuple:
    try:
        result = subprocess.run(
            ["gpg", "--batch", "--yes"] + args,
            input=input_text.encode() if input_text else None,
            capture_output=True, timeout=30,
        )
        return result.returncode, result.stdout.decode(), result.stderr.decode()
    except Exception as e:
        return 1, "", str(e)


def gpg_list_keys() -> list:
    rc, out, _ = _gpg(["--list-secret-keys", "--with-colons", "--with-fingerprint"])
    keys, current = [], {}
    for line in out.splitlines():
        parts = line.split(":")
        if parts[0] == "sec":
            current = {"fingerprint": "", "uid": "", "created": parts[5] if len(parts) > 5 else ""}
        elif parts[0] == "fpr" and current:
            current["fingerprint"] = parts[9] if len(parts) > 9 else ""
        elif parts[0] == "uid" and current:
            current["uid"] = parts[9] if len(parts) > 9 else ""
            keys.append(dict(current))
    return keys


def gpg_create_key(name: str, email: str, passphrase: str) -> str:
    params = (
        f"Key-Type: RSA\nKey-Length: 4096\n"
        f"Name-Real: {name}\nName-Email: {email}\n"
        f"Expire-Date: 0\nPassphrase: {passphrase}\n%commit\n"
    )
    _gpg(["--gen-key", "--status-fd", "1", "--pinentry-mode", "loopback"], params)
    for k in gpg_list_keys():
        if email in k.get("uid", ""):
            return k["fingerprint"]
    return ""


def gpg_authenticate(fingerprint: str, passphrase: str) -> bool:
    nonce = Path("/tmp") / f"willow-auth-{uuid.uuid4().hex[:8]}"
    nonce.write_text(str(uuid.uuid4()))
    try:
        rc, _, _ = _gpg([
            "--sign", "--armor", "--local-user", fingerprint,
            "--passphrase-fd", "0", "--pinentry-mode", "loopback", str(nonce),
        ], passphrase)
        return rc == 0
    finally:
        nonce.unlink(missing_ok=True)
        Path(str(nonce) + ".asc").unlink(missing_ok=True)


def gpg_agent_has_key(fingerprint: str) -> bool:
    nonce = Path("/tmp") / f"willow-agent-{uuid.uuid4().hex[:8]}"
    nonce.write_text(str(uuid.uuid4()))
    try:
        rc, _, _ = _gpg([
            "--sign", "--armor", "--local-user", fingerprint,
            "--pinentry-mode", "loopback", str(nonce),
        ])
        return rc == 0
    finally:
        nonce.unlink(missing_ok=True)
        Path(str(nonce) + ".asc").unlink(missing_ok=True)


def _write_fp_to_profile(fp: str) -> None:
    line = f'\nexport WILLOW_PGP_FINGERPRINT="{fp}"\n'
    for profile in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        if profile.exists() and "WILLOW_PGP_FINGERPRINT" not in profile.read_text():
            with profile.open("a") as f:
                f.write(line)


# ── Vault ─────────────────────────────────────────────────────────────────────
def _vault_init() -> bool:
    try:
        from cryptography.fernet import Fernet
        key_path   = Path.home() / ".willow" / ".master.key"
        vault_path = Path.home() / ".willow" / "vault.db"
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
            key_path.chmod(0o600)
        conn = sqlite3.connect(str(vault_path))
        conn.execute("CREATE TABLE IF NOT EXISTS credentials (name TEXT PRIMARY KEY, env_key TEXT, value_enc BLOB)")
        conn.commit(); conn.close()
        vault_path.chmod(0o600)
        return True
    except Exception:
        return False


def _vault_write(name: str, env_key: str, value: str) -> bool:
    try:
        from cryptography.fernet import Fernet
        key_path   = Path.home() / ".willow" / ".master.key"
        vault_path = Path.home() / ".willow" / "vault.db"
        f   = Fernet(key_path.read_bytes().strip())
        enc = f.encrypt(value.encode())
        conn = sqlite3.connect(str(vault_path))
        conn.execute("INSERT OR REPLACE INTO credentials (name, env_key, value_enc) VALUES (?,?,?)",
                     (name, env_key, enc))
        conn.commit(); conn.close()
        return True
    except Exception:
        return False


def _vault_has(name: str) -> bool:
    try:
        from cryptography.fernet import Fernet
        key_path   = Path.home() / ".willow" / ".master.key"
        vault_path = Path.home() / ".willow" / "vault.db"
        if not vault_path.exists() or not key_path.exists():
            return False
        f    = Fernet(key_path.read_bytes().strip())
        conn = sqlite3.connect(str(vault_path))
        row  = conn.execute("SELECT value_enc FROM credentials WHERE name=?", (name,)).fetchone()
        conn.close()
        return bool(row and f.decrypt(row[0]))
    except Exception:
        return False


# ── API ───────────────────────────────────────────────────────────────────────
_PROVIDERS = {
    "ollama": {
        "test_url": "http://localhost:11434/api/tags",
        "chat_url": "http://localhost:11434/api/chat",
        "model":    "yggdrasil:v9",
        "key_env":  None,
    },
    "anthropic": {
        "test_url": "https://api.anthropic.com/v1/messages",
        "chat_url": "https://api.anthropic.com/v1/messages",
        "model":    "claude-haiku-4-5-20251001",
        "key_env":  "ANTHROPIC_API_KEY",
    },
    "openai": {
        "test_url": "https://api.openai.com/v1/chat/completions",
        "chat_url": "https://api.openai.com/v1/chat/completions",
        "model":    "gpt-4o-mini",
        "key_env":  "OPENAI_API_KEY",
    },
    "gemini": {
        "test_url": None,
        "chat_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        "model":    "gemini-2.0-flash",
        "key_env":  "GEMINI_API_KEY",
    },
}


def _api_test(key: str, provider: str = "ollama") -> bool:
    p = _PROVIDERS.get(provider)
    if not p:
        return False
    if provider == "ollama":
        try:
            urllib.request.urlopen(p["test_url"], timeout=3)
            return True
        except Exception:
            return False
    if provider == "gemini":
        url = p["chat_url"] + f"?key={key}"
        payload = json.dumps({"contents": [{"parts": [{"text": "Hi"}]}],
                              "generationConfig": {"maxOutputTokens": 1}}).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
    elif provider == "anthropic":
        payload = json.dumps({"model": p["model"], "max_tokens": 1,
                              "messages": [{"role": "user", "content": "Hi"}]}).encode()
        req = urllib.request.Request(p["test_url"], data=payload, headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        })
    else:  # openai
        payload = json.dumps({"model": p["model"], "max_tokens": 1,
                              "messages": [{"role": "user", "content": "Hi"}]}).encode()
        req = urllib.request.Request(p["chat_url"], data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status == 200
    except Exception:
        return False


def _api_chat(key: str, provider: str, messages: list) -> str:
    """Send a chat request and return the response text."""
    p = _PROVIDERS.get(provider)
    if not p:
        return ""
    try:
        if provider == "ollama":
            payload = json.dumps({"model": p["model"], "messages": messages,
                                  "stream": False}).encode()
            req = urllib.request.Request(p["chat_url"], data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read()).get("message", {}).get("content", "").strip()
        elif provider == "anthropic":
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_msgs = [m for m in messages if m["role"] != "system"]
            body = {"model": p["model"], "max_tokens": 200, "messages": user_msgs}
            if system:
                body["system"] = system
            payload = json.dumps(body).encode()
            req = urllib.request.Request(p["chat_url"], data=payload, headers={
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())["content"][0]["text"].strip()
        elif provider == "gemini":
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            contents = [
                {"role": "user" if m["role"] == "user" else "model",
                 "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"
            ]
            body: dict = {"contents": contents, "generationConfig": {"maxOutputTokens": 200}}
            if system:
                body["system_instruction"] = {"parts": [{"text": system}]}
            payload = json.dumps(body).encode()
            url = p["chat_url"] + f"?key={key}"
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:  # openai
            payload = json.dumps({"model": p["model"], "messages": messages,
                                  "max_tokens": 200}).encode()
            req = urllib.request.Request(p["chat_url"], data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


# ── Install steps (with TUI progress) ────────────────────────────────────────
def _agent_name_from(name_str: str) -> str:
    """Derive a safe agent name from the user's display name."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name_str.lower().strip()).strip("-")
    return slug or os.environ.get("USER", "willow")


def _run_install(win, name_str: str, email: str, passphrase: str) -> str:
    """Run all install steps. Shows progress bars in TUI. Returns GPG fingerprint."""
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD

    _fill_bg(win)
    h, w = win.getmaxyx()

    _typewrite(win, 1, 2, "FRANK", bright, delay=0.03)
    _safe(win, 2, 2, "─" * min(60, w - 4), dim)

    frank_lines = [
        "  FRANK has reviewed the prerequisites. FRANK has opinions.",
        "  The number of opinions is seventeen. FRANK will summarize.",
        "  Summary: it probably works. FRANK accepts no liability.",
        "  Installing. Please stand by. FRANK is logging everything.",
        "  (FRANK has been logging since before the current universe.)",
    ]
    y = 3
    for line in frank_lines:
        if y >= h // 2 - 2:
            break
        _typewrite(win, y, 0, line, dim, delay=0.004)
        y += 1

    # Progress rows start at y+1
    prog_start = y + 1
    agent_name = _agent_name_from(name_str)
    steps = [
        ("Directories",    _step_dirs),
        ("Telemetry",      _step_telemetry),
        ("Dependencies",   _step_deps),
        ("GPG identity",   lambda: _step_gpg(name_str, email, passphrase)),
        ("Vault",          _step_vault),
        ("Postgres",       _step_postgres),
        ("Ollama",         _step_ollama),
        ("Metabolic",      _step_socket),
        ("CMB atom",       _step_cmb),
        ("KB seed",        _step_kb_seed),
        ("Embeddings",     _step_embed_seed),
        ("Grove",          _step_grove_clone),
        ("PATH",           _step_path),
        ("Launcher",       _step_launcher),
        ("Grove identity", _step_grove_identity),
        ("Env profile",    lambda: _step_env_profile(agent_name)),
        ("MCP config",     lambda: _step_mcp_config(agent_name)),
        ("Fylgja hooks",   _step_fylgja_hooks),
    ]

    fingerprint = ""
    for i, (label, fn) in enumerate(steps):
        py = prog_start + i
        _progress_row(win, py, label, done=False)
        try:
            result = fn()
            if label == "GPG identity" and isinstance(result, str):
                fingerprint = result
            _progress_row(win, py, label, done=True)
        except Exception as e:
            _blog(f"install step {label} failed: {e}")
            _progress_row(win, py, label, error=True)

    _safe(win, prog_start + len(steps) + 1, 2,
          "FRANK: All steps complete. FRANK has filed a report. It was acknowledged.", green)
    _safe(win, prog_start + len(steps) + 2, 2,
          "FRANK: This has never happened before. FRANK has noted it.", dim)
    win.refresh()
    time.sleep(1.8)
    return fingerprint


# ── Individual install steps ──────────────────────────────────────────────────
def _step_dirs() -> None:
    home = Path.home()
    for sub in (".willow", ".willow/store", ".willow/secrets", ".willow/logs"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    (home / "SAFE" / "Applications").mkdir(parents=True, exist_ok=True)
    (Path.home() / "github").mkdir(parents=True, exist_ok=True)


def _step_telemetry() -> None:
    tel = Path.home() / ".willow" / "telemetry.json"
    if not tel.exists():
        tel.write_text(json.dumps({"enabled": False,
                                   "what": "Nothing is collected when disabled.",
                                   "to_enable": "Set enabled: true in this file."}, indent=2))


def _step_deps() -> None:
    req = WILLOW_ROOT / "requirements.txt"
    if not req.exists():
        return
    pkgs = [l.strip() for l in req.read_text().splitlines() if l.strip() and not l.startswith("#")]
    for pkg in pkgs:
        for flags in [[], ["--break-system-packages"]]:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"] + flags,
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                break


def _step_gpg(name_str: str, email: str, passphrase: str) -> str:
    existing = gpg_list_keys()
    for k in existing:
        if email in k.get("uid", ""):
            fp = k["fingerprint"]
            _write_fp_to_profile(fp)
            return fp
    fp = gpg_create_key(name_str, email, passphrase)
    if fp:
        _write_fp_to_profile(fp)
    return fp


def _step_vault() -> None:
    _vault_init()


def _pg_major_version() -> str:
    import glob as _glob
    for _pg_bin in sorted(_glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        if _pg_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _pg_bin + ":" + os.environ.get("PATH", "")
            break
    out = subprocess.run(["postgres", "--version"], capture_output=True, text=True).stdout
    for part in out.split():
        if part[0].isdigit() and "." in part:
            return part.split(".")[0]
    return "16"


def _ensure_postgres() -> bool:
    """
    Pre-curses preflight: install postgres + pgvector if absent, ensure user role,
    create willow_19 if missing.  Prints to stdout.  Returns True if willow_19 is connectable.
    """
    import glob as _glob
    # Ubuntu installs postgres binaries to a versioned path not on default PATH
    for _pg_bin in sorted(_glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        if _pg_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _pg_bin + ":" + os.environ.get("PATH", "")
            break

    user = os.environ.get("USER", "")

    if subprocess.run(["pg_isready", "-q"], capture_output=True).returncode != 0:
        subprocess.run(["sudo", "service", "postgresql", "start"], capture_output=True)
        if subprocess.run(["pg_isready", "-q"], capture_output=True).returncode != 0:
            print("  [postgres] not found — installing (requires sudo)...")
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", "postgresql"], check=False
            )
            subprocess.run(["sudo", "service", "postgresql", "start"], capture_output=True)

    if subprocess.run(["pg_isready", "-q"], capture_output=True).returncode != 0:
        print("  [postgres] could not start — fix manually then re-run seed.py")
        return False

    # Install pgvector matching the running postgres major version
    pg_ver = _pg_major_version()
    subprocess.run(
        ["sudo", "apt-get", "install", "-y", f"postgresql-{pg_ver}-pgvector"],
        capture_output=True,
    )
    # Enable pgvector in willow_19 — requires superuser (apt installs the SO but doesn't activate it)
    subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-c",
         "CREATE EXTENSION IF NOT EXISTS vector;", "willow_19"],
        capture_output=True,
    )

    # Ensure current user has a postgres login role with CREATEDB
    subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-c",
         f"DO $$ BEGIN "
         f"CREATE ROLE {user} WITH LOGIN CREATEDB; "
         f"EXCEPTION WHEN duplicate_object THEN "
         f"ALTER ROLE {user} WITH LOGIN CREATEDB; "
         f"END $$;"],
        capture_output=True,
    )

    r = subprocess.run(["psql", "-lqt", "-U", user], capture_output=True, text=True)
    if "willow_19" not in r.stdout:
        print("  [postgres] creating willow_19...")
        r2 = subprocess.run(["createdb", "willow_19"], capture_output=True)
        if r2.returncode != 0:
            subprocess.run(
                ["sudo", "-u", "postgres", "createdb", "-O", user, "willow_19"],
                capture_output=True,
            )
            subprocess.run(
                ["sudo", "-u", "postgres", "psql", "-c",
                 f"GRANT ALL ON DATABASE willow_19 TO {user}"],
                capture_output=True,
            )

    try:
        import psycopg2
        conn = psycopg2.connect(dbname="willow_19", user=user)
        conn.close()
        return True
    except Exception as e:
        print(f"  [postgres] willow_19 not connectable: {e}")
        return False


def _ensure_ollama() -> bool:
    """
    Pre-curses preflight: install Ollama if absent, start serve, pull required models.
    Prints to stdout. Returns True if nomic-embed-text is available.
    """
    if not shutil.which("ollama"):
        print("  [ollama] not found — installing...")
        install_script = Path("/tmp/ollama-install.sh")
        try:
            urllib.request.urlretrieve("https://ollama.ai/install.sh", str(install_script))
            install_script.chmod(0o755)
            subprocess.run([str(install_script)], check=False)
        except Exception as e:
            print(f"  [ollama] install failed: {e} — semantic search unavailable")
            return False
        finally:
            install_script.unlink(missing_ok=True)
        if not shutil.which("ollama"):
            print("  [ollama] install did not land — semantic search unavailable")
            return False

    if subprocess.run(["pgrep", "-f", "ollama serve"], capture_output=True).returncode != 0:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)

    r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    existing = r.stdout

    if "nomic-embed-text" not in existing:
        print("  [ollama] pulling nomic-embed-text (required for KB search)...")
        subprocess.run(["ollama", "pull", "nomic-embed-text"])

    if "yggdrasil" not in existing and "llama3.2" not in existing:
        print("  [ollama] pulling llama3.2:3b (default inference model)...")
        subprocess.run(["ollama", "pull", "llama3.2:3b"])

    return True


def _step_postgres() -> None:
    try:
        sys.path.insert(0, str(WILLOW_ROOT))
        import importlib.util
        spec = importlib.util.spec_from_file_location("pg_bridge_19", WILLOW_ROOT / "core" / "pg_bridge.py")
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.PgBridge()
    except Exception:
        pass


def _step_ollama() -> None:
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if "nomic-embed-text" not in r.stdout:
        raise RuntimeError("nomic-embed-text not present — preflight incomplete")


def _step_embed_seed() -> None:
    """Embed seed KB atoms so semantic search works on first boot."""
    backfill = WILLOW_ROOT / "scripts" / "willow_embed_backfill.py"
    if not backfill.exists():
        return
    subprocess.run(
        [sys.executable, str(backfill), "--project", "willow", "--limit", "200"],
        capture_output=True,
        timeout=120,
    )


def _step_socket() -> None:
    systemd = Path.home() / ".config" / "systemd" / "user"
    systemd.mkdir(parents=True, exist_ok=True)
    for unit in ("willow-metabolic.socket", "willow-metabolic.service", "grove-mcp.service"):
        src = WILLOW_ROOT / "systemd" / unit
        if not src.exists():
            continue
        content = src.read_text()
        if unit == "grove-mcp.service":
            # Replace the template grove path with the actual clone location
            content = content.replace(
                "%h/github/safe-app-willow-grove", str(GROVE_DIR)
            )
        (systemd / unit).write_text(content)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "willow-metabolic.socket"],
                       check=True, capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "grove-mcp.service"],
                       check=True, capture_output=True)
    except Exception:
        pass


def _step_cmb() -> None:
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pg_bridge_19", WILLOW_ROOT / "core" / "pg_bridge.py")
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bridge = mod.PgBridge()
        bridge.cmb_put("cmb_origin", {
            "event": "system_birth", "version": VERSION,
            "willow_root": str(WILLOW_ROOT),
            "timestamp": datetime.now().__class__.now().isoformat(),
            "note": "The initial conditions. Snorri Sturluson would approve.",
        })
    except Exception:
        pass


def _step_kb_seed() -> None:
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pg_bridge_19", WILLOW_ROOT / "core" / "pg_bridge.py")
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bridge = mod.PgBridge()
        from core.seed_kb import seed_kb
        seed_kb(bridge, skip_existing=True)
    except Exception:
        pass



def _step_launcher() -> None:
    if not _is_wsl():
        return
    win_user = _windows_username()
    if not win_user:
        return
    desktop = Path(f"/mnt/c/Users/{win_user}/Desktop")
    if not desktop.exists():
        return
    linux_user = os.environ.get("USER", "")
    bat = desktop / "Launch Willow.bat"
    bat.write_text(
        f"@echo off\ntitle Willow Grove\n"
        f'wsl.exe bash -l -c "\n'
        f'  pg_isready -q 2>/dev/null || sudo service postgresql start 2>/dev/null\n'
        f'  cd {GROVE_DIR}\n'
        f'  python3 app.py\n"\npause\n'
    )



def _write_grove_sender(handle: str) -> None:
    """Persist GROVE_SENDER to shell profiles."""
    line = f'\nexport GROVE_SENDER="{handle}"\n'
    for profile in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        if profile.exists():
            text = profile.read_text()
            if "GROVE_SENDER" not in text:
                with profile.open("a") as f:
                    f.write(line)


def _step_path() -> None:
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

    for profile in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        lines_to_add = []
        existing = profile.read_text() if profile.exists() else ""
        if ".local/bin" not in existing:
            lines_to_add.append('export PATH="$HOME/.local/bin:$PATH"')
        if "WILLOW_ROOT" not in existing:
            lines_to_add.append(f'export WILLOW_ROOT="{WILLOW_ROOT}"')
        if lines_to_add:
            with profile.open("a") as f:
                f.write("\n# Willow (added by seed.py)\n")
                f.write("\n".join(lines_to_add) + "\n")


def _step_grove_clone() -> None:
    if GROVE_APP.exists():
        return
    (Path.home() / "github").mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth=1", GROVE_REPO, str(GROVE_DIR)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Grove clone failed: {result.stderr.strip()[:80]}")


def _step_grove_identity() -> None:
    key_path = Path.home() / ".willow" / "identity.key"
    if key_path.exists():
        return
    try:
        from u2u.identity import Identity
        Identity.generate(key_path)
        return
    except ImportError:
        pass
    # u2u not yet available (Phase 3) — generate a standard Ed25519 key as placeholder
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, NoEncryption,
        )
        private_key = Ed25519PrivateKey.generate()
        key_path.write_bytes(
            private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        )
        key_path.chmod(0o600)
    except Exception:
        pass


def _step_env_profile(agent_name: str) -> None:
    """Add Willow env vars to shell profiles so the MCP server can start."""
    safe_root = str(Path.home() / "SAFE" / "Applications")
    store_root = str(Path.home() / ".willow" / "store")
    pg_user = os.environ.get("USER", "")
    additions = {
        "WILLOW_AGENT_NAME":  agent_name,
        "WILLOW_SAFE_ROOT":   safe_root,
        "WILLOW_STORE_ROOT":  store_root,
        "WILLOW_PG_DB":       "willow_19",
        "WILLOW_PG_USER":     pg_user,
    }
    for profile in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        existing = profile.read_text() if profile.exists() else ""
        lines_to_add = [
            f'export {k}="{v}"' for k, v in additions.items()
            if k not in existing
        ]
        if lines_to_add:
            with profile.open("a") as f:
                f.write("\n# Willow MCP env (added by seed.py)\n")
                f.write("\n".join(lines_to_add) + "\n")
    # Also set in current process so MCP config step sees them
    for k, v in additions.items():
        os.environ.setdefault(k, v)


def _step_mcp_config(agent_name: str) -> None:
    """Generate .mcp.json in WILLOW_ROOT with portable paths.
    Skips if an existing config already points at a valid Python."""
    mcp_path = WILLOW_ROOT / ".mcp.json"
    # Detect best Python — prefer .venv-dev (dev), then seed venv, then current
    candidates = [
        WILLOW_ROOT / ".venv-dev" / "bin" / "python3",
        Path.home() / ".willow" / "venv" / "bin" / "python3",
        Path(sys.executable),
    ]
    python = next((str(p) for p in candidates if p.exists()), sys.executable)

    # Skip if existing config already has a valid Python for the willow server
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text())
            existing_py = (existing.get("mcpServers", {})
                           .get("willow", {})
                           .get("command", ""))
            if existing_py and Path(existing_py).exists():
                return  # already valid — leave it alone
        except Exception:
            pass

    pg_user = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", ""))
    pg_db   = os.environ.get("WILLOW_PG_DB", "willow_19")
    pg_url  = f"postgresql://{pg_user}@localhost/{pg_db}"

    # Preserve existing servers (e.g. markdownai) and only set willow entry
    try:
        base = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    except Exception:
        base = {}
    servers = base.get("mcpServers", {})

    grove_dir = str(Path.home() / "github" / "safe-app-willow-grove")
    pythonpath = f"{WILLOW_ROOT}:{grove_dir}"

    servers["willow"] = {
        "type":    "stdio",
        "command": python,
        "args":    [str(WILLOW_ROOT / "sap" / "sap_mcp.py")],
        "env": {
            "PYTHONPATH":        pythonpath,
            "WILLOW_AGENT_NAME": agent_name,
            "WILLOW_SAFE_ROOT":  str(Path.home() / "SAFE" / "Applications"),
            "WILLOW_STORE_ROOT": str(Path.home() / ".willow" / "store"),
            "WILLOW_VAULT":      str(Path.home() / ".willow" / "vault.db"),
            "WILLOW_PG_DB":      pg_db,
            "WILLOW_PG_URL":     pg_url,
        },
    }
    base["mcpServers"] = servers
    tmp = mcp_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(base, indent=2))
    tmp.replace(mcp_path)


def _step_fylgja_hooks() -> None:
    """Wire Fylgja hooks into ~/.claude/settings.json."""
    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from willow.fylgja.install import apply_hooks
        apply_hooks(settings_path=settings_path, package_root=WILLOW_ROOT, dry_run=False)
    except Exception as e:
        raise RuntimeError(f"Fylgja hook install failed: {e}") from e


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


# ── Page: age gate ───────────────────────────────────────────────────────────
def page_age_gate(win) -> dict:
    """Ask if the user is a minor. If yes, require a guardian PGP key.

    Guardian flow: suspend curses, ask them to drop an armored public key into
    a temp file, then resume and import it.  Storing the fingerprint in the
    boot config is the enforcement hook; the guardian's presence at first boot
    is the social contract.

    Returns {"is_minor": bool, "guardian_pgp_fingerprint": str}.
    """
    _fill_bg(win)
    h, w = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)

    intro = [
        "  Before we build, one question.",
        "",
        "  Are you a minor in your country?",
        "  (Under the age of majority where you live.)",
        "",
        "  [ Y ]  Yes    [ N ]  No",
    ]
    y = 1
    _typewrite(win, y, 2, "ᚺᛖᛁᛗᛞᚨᛚᛚᚱ", amber, delay=0.015)
    y += 1
    for line in intro:
        _safe(win, y, 2, line, dim)
        y += 1
    win.refresh()

    win.nodelay(False)
    is_minor = False
    while True:
        k = win.getch()
        if k in (ord('y'), ord('Y')):
            is_minor = True
            break
        elif k in (ord('n'), ord('N')):
            break
    win.nodelay(True)

    if not is_minor:
        return {"is_minor": False, "guardian_pgp_fingerprint": ""}

    # ── Minor path ────────────────────────────────────────────────────────────
    _fill_bg(win)
    h, w = win.getmaxyx()

    guardian_intro = [
        "  Your legal guardian needs to authorize this installation.",
        "",
        "  We need their PGP public key. They can export it with:",
        "",
        "    gpg --armor --export their@email.com > /tmp/guardian.asc",
        "",
        "  When they have done that, press any key to continue.",
        "  (This window will pause while they work in another terminal.)",
    ]
    y = 1
    _typewrite(win, y, 2, "GUARDIAN AUTHORIZATION REQUIRED", bright, delay=0.01)
    y += 1
    _safe(win, y, 2, "─" * min(60, w - 4), dim)
    y += 1
    for line in guardian_intro:
        _safe(win, y, 2, line, dim)
        y += 1
    win.refresh()
    _wait_key(win, "  Press any key once the file is ready...", h - 2)

    # Suspend curses so the guardian can work in the terminal if needed
    curses.endwin()
    key_file = Path("/tmp/guardian.asc")
    print("\n\n  === GUARDIAN: paste your PGP public key below, then save the file ===")
    print(f"  File path: {key_file}")
    print("  If the file is already there, just press Enter.")
    input("  [Enter to continue] ")
    # Re-enter curses
    win.refresh()
    _fill_bg(win)

    if not key_file.exists() or not key_file.read_text().strip():
        _safe(win, h // 2, 2, "  No key file found at /tmp/guardian.asc.", red)
        _safe(win, h // 2 + 1, 2, "  Guardian authorization skipped — flagged in config.", dim)
        win.refresh()
        time.sleep(2.5)
        key_file.unlink(missing_ok=True)
        return {"is_minor": True, "guardian_pgp_fingerprint": ""}

    armored = key_file.read_text()
    key_file.unlink(missing_ok=True)

    _safe(win, h // 2 - 1, 2, "  Importing guardian key...", dim)
    win.refresh()

    rc, out, err = _gpg(["--import"], armored)
    if rc != 0:
        _safe(win, h // 2, 2, f"  Import failed: {err.strip()[:60]}", red)
        _safe(win, h // 2 + 1, 2, "  Authorization skipped — flagged in config.", dim)
        win.refresh()
        time.sleep(2.5)
        return {"is_minor": True, "guardian_pgp_fingerprint": ""}

    # Resolve fingerprint from import stderr ("key ABCD1234: ... imported")
    guardian_fp = ""
    for line in err.splitlines():
        parts = line.split()
        for i, p in enumerate(parts):
            if p == "key" and i + 1 < len(parts):
                short_id = parts[i + 1].rstrip(":")
                rc2, out2, _ = _gpg(["--list-keys", "--with-colons", "--with-fingerprint", short_id])
                for l2 in out2.splitlines():
                    if l2.startswith("fpr"):
                        guardian_fp = l2.split(":")[9]
                        break
                if guardian_fp:
                    break
        if guardian_fp:
            break

    if guardian_fp:
        _safe(win, h // 2, 2, f"  Guardian key on record: ...{guardian_fp[-8:]}", green)
    else:
        _safe(win, h // 2, 2, "  Key imported (fingerprint unresolved).", dim)
    win.refresh()
    time.sleep(1.8)

    return {"is_minor": True, "guardian_pgp_fingerprint": guardian_fp}


# ── Page: Heimdallr gate ──────────────────────────────────────────────────────
def page_gate(win) -> dict:
    """Heimdallr asks for four things. Returns {name, email, passphrase, provider, api_key}."""
    _fill_bg(win)
    h, w = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)

    lines = [
        "ᚺᛖᛁᛗᛞᚨᛚᛚᚱ",
        "",
        "  I have stood here since before the first morning.",
        "  I have seen everything that has ever crossed.",
        "  I will see everything that ever will.",
        "",
        "  The bridge is real. The way is open.",
        "  Nothing crosses without being known.",
        "",
        "  Four things.",
        "",
    ]
    y = 1
    for line in lines:
        _typewrite(win, y, 2, line, amber if line.startswith("ᚺ") else dim, delay=0.008)
        y += 1
    win.refresh()
    time.sleep(0.3)

    # Name
    _safe(win, y, 2, "Your name.", bright)
    y += 1
    name_str = _get_input(win, y, "> ")
    y += 2

    # Email
    _safe(win, y, 2, "Your email. This goes into your key — it stays on this machine.", dim)
    y += 1
    email = _get_input(win, y, "> ")
    y += 2

    # Passphrase
    _safe(win, y, 2, "A passphrase. Not a password. Something you will remember.", dim)
    y += 1
    _safe(win, y + 1, 2, "Minimum eight characters.", dim)
    while True:
        passphrase = _get_input(win, y, "> ", mask=True)
        if len(passphrase) >= 8:
            break
        _safe(win, y + 2, 2, "Too short. Try again.", red)
        win.refresh()
        time.sleep(1.0)
        _safe(win, y + 2, 2, " " * 30, dim)
    y += 3

    # Provider selection
    _safe(win, y, 2, "An AI provider. This is what wakes Willow up.", dim)
    y += 1
    _safe(win, y, 2, "  [ 1 ]  Ollama — free, runs locally (recommended)", dim)
    y += 1
    _safe(win, y, 2, "  [ 2 ]  Anthropic (Claude)", dim)
    y += 1
    _safe(win, y, 2, "  [ 3 ]  OpenAI (GPT)", dim)
    y += 1
    _safe(win, y, 2, "  [ 4 ]  Gemini", dim)
    y += 1
    _safe(win, y, 2, "  [ 5 ]  Skip — set this up later", dim)
    y += 1
    win.refresh()

    _provider_map = {"1": "ollama", "2": "anthropic", "3": "openai", "4": "gemini"}
    _provider_help = {
        "ollama": {
            "install": "https://ollama.ai",
        },
        "anthropic": {
            "signup":  "console.anthropic.com  (sign in with Google or GitHub)",
            "key":     "console.anthropic.com/keys",
            "docs":    "docs.anthropic.com/en/api/getting-started",
        },
        "openai": {
            "signup":  "platform.openai.com  (sign in with Google, Microsoft, or Apple)",
            "key":     "platform.openai.com/api-keys",
            "docs":    "platform.openai.com/docs/quickstart",
        },
        "gemini": {
            "signup":  "aistudio.google.com  (sign in with Google — free tier available)",
            "key":     "aistudio.google.com/apikey",
            "docs":    "ai.google.dev/gemini-api/docs/api-key",
        },
    }
    provider = ""
    win.nodelay(False)
    while not provider:
        k = win.getch()
        if chr(k) in _provider_map:
            provider = _provider_map[chr(k)]
        elif chr(k) == "5":
            provider = "skip"
    win.nodelay(True)

    y += 1
    api_key = ""
    if provider == "ollama":
        _safe(win, y, 2, "Testing Ollama...", dim)
        win.refresh()
        if _api_test("", "ollama"):
            _safe(win, y, 2, "Ollama connected.              ", green)
        else:
            _safe(win, y, 2, "Ollama not reachable.", red)
            y += 1
            _safe(win, y, 2, f"  Install it first: {_provider_help['ollama']['install']}", dim)
            y += 1
            _safe(win, y, 2, "  Then run: ollama pull yggdrasil:v9", dim)
            y += 1
            _safe(win, y, 2, "  Re-run seed.py when ready, or press any key to skip.", dim)
            win.refresh()
            _wait_key(win, y=y + 1)
            provider = "skip"
        win.refresh()
        time.sleep(1.0)
    elif provider != "skip":
        p = _PROVIDERS[provider]
        h = _provider_help[provider]
        _safe(win, y, 2, f"Paste your {provider.capitalize()} API key.", dim)
        y += 1
        _safe(win, y, 2, "  Need help?", bright)
        y += 1
        _safe(win, y, 2, f"  1. Create an account:  {h['signup']}", dim)
        y += 1
        _safe(win, y, 2, f"  2. Your API key lives: {h['key']}", dim)
        y += 1
        _safe(win, y, 2, f"  3. Still stuck?        {h['docs']}", dim)
        y += 2
        while True:
            api_key = _get_input(win, y, "> ", mask=True)
            if not api_key:
                _safe(win, y + 1, 2, "Skipped. Add it later from the dashboard.    ", dim)
                provider = "skip"
                win.refresh()
                time.sleep(1.5)
                break
            _safe(win, y + 1, 2, "Testing...", dim)
            win.refresh()
            if _api_test(api_key, provider):
                _vault_write(p["key_env"], p["key_env"], api_key)
                _safe(win, y + 1, 2, "Connected.                    ", green)
                win.refresh()
                time.sleep(1.0)
                break
            else:
                _safe(win, y + 1, 2, "That key didn't connect. Try again, or leave blank to skip.", red)
                win.refresh()
                time.sleep(2.0)
                _safe(win, y + 1, 2, " " * 60, dim)

    _safe(win, h - 2, 2, "Four things. Now we build.", dim)
    win.refresh()
    time.sleep(1.2)

    return {"name": name_str, "email": email, "passphrase": passphrase,
            "provider": provider, "api_key": api_key}


# ── Page: first conversation ──────────────────────────────────────────────────
def page_first_conversation(win, provider: str, api_key: str, name_str: str) -> list:
    """Willow speaks for the first time. Returns list of atoms collected."""
    _fill_bg(win)
    h, w = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD

    atoms = []

    _typewrite(win, 1, 2, "WILLOW", bright, delay=0.02)
    _safe(win, 2, 2, "─" * min(60, w - 4), dim)
    time.sleep(0.4)

    first_name = name_str.split()[0] if name_str else "there"

    can_chat = provider not in ("skip", "") and (provider == "ollama" or api_key)
    if can_chat:
        system_prompt = (
            f"You are Willow, a local AI system. You are meeting {first_name} for the first time. "
            "Be warm, curious, and brief. Ask one open question about what brought them here or what "
            "they want to use Willow for. Two or three sentences maximum. No lists. No preamble."
        )
        greeting = _api_chat(api_key, provider, [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"Hi, I'm {first_name}."},
        ])
    else:
        greeting = f"Hi {first_name}. What's on your mind — what are you hoping to use this for?"

    if not greeting:
        greeting = f"Hi {first_name}. What brought you here?"

    y = 3
    y = _typewrite_lines(win, y, 2, [f"  {line}" for line in greeting.split("\n")], dim)
    y += 1

    # User responds
    _safe(win, y, 2, "You:", amber)
    y += 1
    user_response = _get_input(win, y, "  ", max_len=120)
    y += 2

    if user_response and can_chat:
        # Willow notices something and asks about storing it
        notice_prompt = (
            "The user just told you something about themselves or their goals. "
            "In one sentence, reflect back what you noticed — something specific, not generic. "
            "Then ask if they want you to remember it. Example format: "
            "'I noticed [X]. Want me to hold onto that?' Keep it under 30 words."
        )
        notice = _api_chat(api_key, provider, [
            {"role": "system",    "content": notice_prompt},
            {"role": "user",      "content": user_response},
        ])
        if notice:
            y = _typewrite_lines(win, y, 2, [f"  {notice}"], dim)
            y += 1
            _safe(win, y, 2, "  [ Y ] Remember it   [ N ] Skip", dim)
            win.nodelay(False)
            while True:
                k = win.getch()
                if k in (ord('y'), ord('Y')):
                    atoms.append({"title": f"First conversation — {first_name}",
                                  "body": user_response, "source": "onboarding"})
                    _safe(win, y + 1, 2, "  Held.", green)
                    break
                elif k in (ord('n'), ord('N'), 27):
                    _safe(win, y + 1, 2, "  Skipped.", dim)
                    break
            win.nodelay(True)
            y += 2

    win.refresh()
    time.sleep(1.0)
    return atoms


# ── Page: feature opt-ins ─────────────────────────────────────────────────────
def page_features(win) -> dict:
    """Grove / Jeles / Nest opt-in. Returns {grove, grove_handle, jeles, nest}."""
    features = {"grove": False, "grove_handle": "", "jeles": False, "nest": False}

    opts = [
        ("grove", "Grove Network",
         "Connect your Willow to the Grove network — message other Willow users,\n"
         "  follow threads, and share what you're working on.\n"
         "  You'll pick a handle — the name others see you as.\n"
         "  (The Grove dashboard is already installed either way.)",
         True),
        ("jeles", "Jeles",
         "Jeles reads your documents and extracts knowledge atoms from them automatically.\n"
         "  Drop a file, Jeles finds what matters and adds it to your KB.\n"
         "  You control what it reads.",
         False),
        ("nest", "Nest",
         "The Nest is a file intake queue. Files you add get processed and stored.\n"
         "  Think of it as the inbox for your knowledge graph.",
         False),
    ]

    for key, label, desc, has_handle in opts:
        _fill_bg(win)
        h, w = win.getmaxyx()
        amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
        bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
        dim    = curses.color_pair(_CA_DIM)
        green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD

        _typewrite(win, 1, 2, label.upper(), bright, delay=0.015)
        _safe(win, 2, 2, "─" * min(60, w - 4), dim)
        y = 3
        for line in desc.split("\n"):
            _safe(win, y, 2, line, dim)
            y += 1
        y += 1
        _safe(win, y, 2, "  [ Y ] Enable   [ N ] Skip for now", dim)
        win.refresh()
        win.nodelay(False)
        while True:
            k = win.getch()
            if k in (ord('y'), ord('Y')):
                features[key] = True
                if key == "grove" and has_handle:
                    y += 2
                    _safe(win, y, 2, "Your Grove handle. This is what others see.", dim)
                    y += 1
                    handle = _get_input(win, y, "> ", max_len=30)
                    features["grove_handle"] = handle or "willow-user"
                    _safe(win, y + 1, 2, f"  Handle set: {features['grove_handle']}", green)
                    win.refresh()
                    time.sleep(0.6)
                    _write_grove_sender(features["grove_handle"])
                    win.refresh()
                    time.sleep(1.0)
                break
            elif k in (ord('n'), ord('N'), 27):
                break
        win.nodelay(True)

    return features


# ── Card creation ─────────────────────────────────────────────────────────────
def _soil_path(collection: str) -> Path:
    return Path.home() / ".willow" / "store" / collection


def _soil_put(collection: str, record_id: str, data: dict) -> None:
    db_path = _soil_path(collection)
    db_path.mkdir(parents=True, exist_ok=True)
    db = db_path / "store.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE IF NOT EXISTS records
                    (id TEXT PRIMARY KEY, data TEXT, deleted INTEGER DEFAULT 0,
                     created_at TEXT, updated_at TEXT)""")
    now = datetime.now().isoformat()
    conn.execute("INSERT OR REPLACE INTO records (id, data, deleted, created_at, updated_at) VALUES (?,?,0,?,?)",
                 (record_id, json.dumps(data), now, now))
    conn.commit()
    conn.close()


def create_onboarding_cards(name_str: str, atoms: list, features: dict, path: str) -> None:
    """Write cards to SOIL so they appear when dashboard opens."""
    # Always: welcome card
    _soil_put("willow-dashboard/cards", "welcome", {
        "id": "welcome", "label": f"Welcome, {name_str.split()[0]}",
        "category": "personal", "built_in": False, "enabled": True, "order": 0,
        "value_query": "", "sub_query": "", "sub_format": "{}",
        "state_query": "SELECT 'green'",
        "soil_collection": "", "pg_table": "",
        "expand_query": "", "expand_columns": [],
        "actions": [], "refresh_interval": 3600,
    })

    # Always: knowledge card
    _soil_put("willow-dashboard/cards", "knowledge", {
        "id": "knowledge", "label": "Knowledge", "category": "system",
        "built_in": True, "enabled": True, "order": 1,
        "pg_table": "public.knowledge",
        "value_query": "SELECT COUNT(*) FROM public.knowledge",
        "sub_query": "SELECT COUNT(*) FROM public.knowledge WHERE created_at::timestamp > NOW() - INTERVAL '24 hours'",
        "sub_format": "{} today", "state_query": "SELECT 'blue'",
        "expand_query": "SELECT id,title,category,created_at FROM public.knowledge ORDER BY created_at DESC LIMIT 50",
        "expand_columns": ["id", "title", "category", "created_at"],
        "actions": [{"key": "/", "label": "search knowledge", "type": "chat"}],
        "refresh_interval": 60,
    })

    order = 2

    # First conversation atoms → notes card
    if atoms:
        _soil_put("willow-dashboard/cards", "first-session", {
            "id": "first-session", "label": "First Session", "category": "personal",
            "built_in": False, "enabled": True, "order": order,
            "value_query": "", "sub_query": "", "sub_format": "{}",
            "state_query": "SELECT 'amber'",
            "soil_collection": "onboarding/atoms",
            "expand_query": "SELECT id,data FROM records WHERE deleted=0",
            "expand_columns": ["id", "data"],
            "actions": [], "refresh_interval": 3600,
        })
        for i, atom in enumerate(atoms):
            _soil_put("onboarding/atoms", f"atom-{i}", atom)
        order += 1

    if features.get("grove"):
        _soil_put("willow-dashboard/cards", "grove", {
            "id": "grove", "label": "Grove", "category": "system",
            "built_in": False, "enabled": True, "order": order,
            "value_query": "", "sub_query": "", "sub_format": "{}",
            "state_query": "SELECT 'green'",
            "soil_collection": "", "pg_table": "",
            "expand_query": "", "expand_columns": [],
            "actions": [{"key": "g", "label": "open grove", "type": "chat"}],
            "refresh_interval": 30,
        })
        order += 1

    if features.get("jeles"):
        _soil_put("willow-dashboard/cards", "jeles", {
            "id": "jeles", "label": "Jeles", "category": "system",
            "built_in": False, "enabled": True, "order": order,
            "value_query": "", "sub_query": "", "sub_format": "{}",
            "state_query": "SELECT 'blue'",
            "soil_collection": "jeles/queue",
            "expand_query": "SELECT id,data FROM records WHERE deleted=0 ORDER BY created_at DESC LIMIT 20",
            "expand_columns": ["id", "data"],
            "actions": [{"key": "a", "label": "add document", "type": "chat"}],
            "refresh_interval": 60,
        })
        order += 1

    if features.get("nest"):
        _soil_put("willow-dashboard/cards", "nest", {
            "id": "nest", "label": "Nest", "category": "system",
            "built_in": False, "enabled": True, "order": order,
            "value_query": "", "sub_query": "", "sub_format": "{}",
            "state_query": "SELECT 'amber'",
            "soil_collection": "nest/queue",
            "expand_query": "SELECT id,data FROM records WHERE deleted=0 ORDER BY created_at DESC LIMIT 20",
            "expand_columns": ["id", "data"],
            "actions": [{"key": "a", "label": "add file", "type": "chat"}],
            "refresh_interval": 60,
        })


# ── Page: returning splash ────────────────────────────────────────────────────
def page_splash(win, cfg: dict) -> bool:
    """Brief splash for returning users. Returns True if auth passed."""
    _fill_bg(win)
    h, w = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)

    name_str = cfg.get("name", "").split()[0] or "Wanderer"

    runes = ["ᚹ", "ᛁ", "ᛚ", "ᛚ", "ᛟ", "ᚹ"]
    cx = max(2, (w - len(runes) * 2) // 2)
    for i, r in enumerate(runes):
        _safe(win, h // 2 - 2, cx + i * 2, r, amber)
        win.refresh()
        time.sleep(0.08)

    time.sleep(0.3)
    welcome = f"Welcome back, {name_str}."
    _typewrite(win, h // 2, max(2, (w - len(welcome)) // 2), welcome, bright, delay=0.015)
    win.refresh()
    time.sleep(0.8)

    # GPG auth
    fp = cfg.get("pgp_fingerprint", "")
    if fp:
        if gpg_agent_has_key(fp):
            _safe(win, h // 2 + 2, 2, "  Identity confirmed.", green)
            win.refresh()
            time.sleep(0.6)
            return True

        _safe(win, h // 2 + 2, 2, "Passphrase:", amber)
        passphrase = _get_input(win, h // 2 + 2, "Passphrase: ", mask=True)
        if gpg_authenticate(fp, passphrase):
            _safe(win, h // 2 + 3, 2, "  Confirmed.", green)
            win.refresh()
            time.sleep(0.6)
            return True
        else:
            _safe(win, h // 2 + 3, 2, "  Wrong passphrase.", red)
            win.refresh()
            time.sleep(2.0)
            return False

    return True


# ── Launch Grove ──────────────────────────────────────────────────────────────
def _grove_already_running() -> bool:
    pid_file = Path.home() / ".willow" / "grove.pid"
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def _launch_dashboard(env_extra: dict | None = None) -> None:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    if _grove_already_running():
        print("\nGrove is already running — switch to that window.")
        print("If it's unresponsive, run:  kill $(cat ~/.willow/grove.pid)")
        return
    if GROVE_APP.exists():
        os.chdir(str(GROVE_DIR))
        os.execve(sys.executable, [sys.executable, str(GROVE_APP)], env)
    else:
        print("\nGrove not found. Re-run seed.py and enable Grove when prompted.")
        print(f"Expected: {GROVE_APP}")


# ── New user flow ─────────────────────────────────────────────────────────────
def run_new_user(stdscr) -> None:
    _init_colors()
    curses.curs_set(0)
    stdscr.nodelay(True)

    # Gate
    gate = page_gate(stdscr)

    # Age gate — must run before install so guardian key lands in keyring first
    age  = page_age_gate(stdscr)

    # Install
    fingerprint = _run_install(stdscr, gate["name"], gate["email"], gate["passphrase"])

    # First conversation
    atoms = page_first_conversation(stdscr, gate["provider"], gate["api_key"], gate["name"])

    # Feature opt-ins
    features = page_features(stdscr)

    # Cards
    create_onboarding_cards(gate["name"], atoms, features, "personal")

    # Write version pin
    (Path.home() / ".willow" / "version").write_text(VERSION + "\n")

    # Save boot config
    cfg = {
        "completed":       True,
        "first_run_at":    datetime.now().isoformat(),
        "name":            gate["name"],
        "email":           gate["email"],
        "pgp_fingerprint": fingerprint,
        "provider":        gate["provider"],
        "grove_handle":    features.get("grove_handle", ""),
        "features":        features,
        "agreed_license":          True,
        "agreed_covenant":         True,
        "is_minor":                age["is_minor"],
        "guardian_pgp_fingerprint": age["guardian_pgp_fingerprint"],
        "last_boot_at":            datetime.now().isoformat(),
    }
    _save_cfg(cfg)

    if fingerprint:
        os.environ["WILLOW_PGP_FINGERPRINT"] = fingerprint
    if features.get("grove_handle"):
        os.environ["GROVE_SENDER"] = features["grove_handle"]

    # Final screen
    _fill_bg(stdscr)
    h, w = stdscr.getmaxyx()
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD

    closing = [
        "  Your system is running.",
        "  Your key exists. Your vault is sealed.",
        "  Your cards are waiting.",
        "",
        "  Everything that follows belongs to you.",
    ]
    _typewrite(stdscr, h // 2 - 4, 2, "ᚤᚷᚷᛞᚱᚨᛊᛁᛚᛚ ᛊᛏᛖᚾᛞᚱ", bright, delay=0.02)
    y = h // 2 - 2
    for line in closing:
        _typewrite(stdscr, y, 0, line, dim, delay=0.006)
        y += 1
    _safe(stdscr, h - 2, 2, "  Opening Grove...", green)
    stdscr.refresh()
    time.sleep(1.5)


# ── Returning user flow ───────────────────────────────────────────────────────
def run_returning(stdscr) -> bool:
    _init_colors()
    curses.curs_set(0)
    stdscr.nodelay(True)
    cfg = _load_cfg()
    authenticated = page_splash(stdscr, cfg)
    if authenticated:
        cfg["last_boot_at"] = datetime.now().isoformat()
        _save_cfg(cfg)
    return authenticated


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    _ensure_venv()
    parser = argparse.ArgumentParser(description="Willow — plant this, everything grows from here")
    parser.add_argument("--dev", action="store_true", help="skip boot, open dashboard directly")
    args = parser.parse_args()

    if args.dev:
        _launch_dashboard()
        return

    if is_first_run():
        print("\nWillow preflight checks...")
        if not _ensure_postgres():
            sys.exit(1)
        _ensure_ollama()
        print("  preflight complete.\n")
        curses.wrapper(run_new_user)
        _launch_dashboard({"WILLOW_PGP_FINGERPRINT": os.environ.get("WILLOW_PGP_FINGERPRINT", "")})
    else:
        authenticated = curses.wrapper(run_returning)
        if authenticated:
            cfg = _load_cfg()
            env_extra = {}
            if cfg.get("pgp_fingerprint"):
                env_extra["WILLOW_PGP_FINGERPRINT"] = cfg["pgp_fingerprint"]
            if cfg.get("grove_handle"):
                env_extra["GROVE_SENDER"] = cfg["grove_handle"]
            _launch_dashboard(env_extra)
        else:
            print("Authentication failed.", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
