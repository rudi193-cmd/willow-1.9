#!/usr/bin/env python3
"""
boot.py — Willow onboarding TUI.
b17: BOOT1  ΔΣ=42

Runs after seed.py. Presents the FRANK experience, collects API keys,
writes them to the Fernet vault, then launches the dashboard.

  python3 boot.py
"""
import curses
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── Boot config ───────────────────────────────────────────────────────────────
BOOT_CONFIG = Path.home() / ".willow" / "willow-boot.json"
BOOT_LOG    = Path("/tmp/willow-boot-debug.log")


def _blog(msg: str):
    try:
        with BOOT_LOG.open("a") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
    except Exception:
        pass


# ── Typewriter timing ─────────────────────────────────────────────────────────
CHAR_DELAY = 0.007
LINE_DELAY = 0.08
PAGE_PAUSE = 0.4

# ── Amber phosphor color indices ──────────────────────────────────────────────
_CA_AMBER  = 1
_CA_DIM    = 2
_CA_GREEN  = 3
_CA_RED    = 4
_CA_BRIGHT = 5
_CA_BOX    = 6


def _init_boot_colors():
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

def _safe(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    try:
        win.addstr(y, x, text[:max(0, w - x - 1)], attr)
    except curses.error:
        pass


def _typewrite(win, y, x, text, attr=0, delay=CHAR_DELAY):
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


def _typewrite_lines(win, start_y, x, lines, attr=0, delay=CHAR_DELAY):
    y = start_y
    h, _ = win.getmaxyx()
    for line in lines:
        if y >= h - 1:
            break
        _typewrite(win, y, x, line, attr, delay)
        y += 1
        time.sleep(LINE_DELAY)
    return y


def _draw_box(win, y, x, h, w, attr=0):
    try:
        win.attron(attr)
        win.addstr(y,         x, "┌" + "─" * (w - 2) + "┐")
        win.addstr(y + h - 1, x, "└" + "─" * (w - 2) + "┘")
        for row in range(1, h - 1):
            win.addstr(y + row, x,         "│")
            win.addstr(y + row, x + w - 1, "│")
        win.attroff(attr)
    except curses.error:
        pass


def _wait_key(win, prompt="  Press any key to continue...", y=None):
    h, w = win.getmaxyx()
    if y is None:
        y = h - 2
    time.sleep(PAGE_PAUSE)
    _safe(win, y, 2, prompt, curses.color_pair(_CA_DIM))
    win.refresh()
    win.nodelay(False)
    k = win.getch()
    win.nodelay(True)
    return k


def _fill_bg(win):
    win.bkgd(' ', curses.color_pair(_CA_AMBER))
    win.erase()


# ── Heimdallr ASCII art ───────────────────────────────────────────────────────
_HEIMDALLR_ART = [
    r"          )  (          ",
    r"         (    )         ",
    r"        ) \  / (        ",
    r"       /  (())  \       ",
    r"      | ·  \/  · |      ",
    r"      |   (  )   |      ",
    r"       \   \/   /       ",
    r"        \  /\  /        ",
    r"    ====/ /  \ \====    ",
    r"        | |  | |        ",
    r"       /| |  | |\       ",
    r"      /_|_|  |_|_\      ",
    r"    ~~~~~  \/  ~~~~~    ",
]

_WILLOW_WORDMARK = [
    r" ██╗    ██╗██╗██╗      ██╗      ██████╗ ██╗    ██╗",
    r" ██║    ██║██║██║      ██║     ██╔═══██╗██║    ██║",
    r" ██║ █╗ ██║██║██║      ██║     ██║   ██║██║ █╗ ██║",
    r" ██║███╗██║██║██║      ██║     ██║   ██║██║███╗██║",
    r" ╚███╔███╔╝██║███████╗ ███████╗╚██████╔╝╚███╔███╔╝",
    r"  ╚══╝╚══╝ ╚═╝╚══════╝ ╚══════╝ ╚═════╝  ╚══╝╚══╝",
]


# ── Environment detection ─────────────────────────────────────────────────────

def check_environment() -> dict:
    results = {}

    try:
        import psycopg2
        dsn = os.environ.get("WILLOW_DB_URL", "")
        if dsn:
            conn = psycopg2.connect(dsn, connect_timeout=3)
        else:
            conn = psycopg2.connect(
                dbname=os.environ.get("WILLOW_PG_DB", "willow"),
                user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
                connect_timeout=3,
            )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM public.knowledge")
        count = cur.fetchone()[0]
        conn.close()
        results["LOAM / POSTGRES"] = ("ok", f"{count:,} atoms")
    except Exception as e:
        results["LOAM / POSTGRES"] = ("missing", str(e)[:40])

    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        ygg = sorted([m for m in models if "yggdrasil" in m.lower()], reverse=True)
        ver = ygg[0].split(":")[-1] if ygg else "no yggdrasil"
        results["OLLAMA"] = ("ok", f"{len(models)} models · yggdrasil:{ver}")
    except Exception:
        results["OLLAMA"] = ("missing", "unreachable")

    safe_root = os.environ.get("WILLOW_SAFE_ROOT",
                str(Path.home() / "SAFE" / "Applications"))
    if Path(safe_root).is_dir():
        apps = [d for d in Path(safe_root).iterdir() if d.is_dir()]
        results["SAFE"] = ("ok", f"{len(apps)} manifests at {safe_root}")
    else:
        results["SAFE"] = ("missing", safe_root)

    store_root = Path(os.environ.get("WILLOW_STORE_ROOT",
                      str(Path.home() / ".willow" / "store")))
    if store_root.exists():
        collections = list(store_root.rglob("store.db"))
        results["SOIL"] = ("ok", f"{len(collections)} collections")
    else:
        results["SOIL"] = ("missing", "store not initialised")

    mcp_file = Path.cwd() / ".mcp.json"
    if mcp_file.exists():
        try:
            data = json.loads(mcp_file.read_text())
            n = len(data.get("mcpServers", {}))
            results["MCP"] = ("ok", f"{n} servers")
        except Exception:
            results["MCP"] = ("warn", "config unreadable")
    else:
        results["MCP"] = ("missing", "no .mcp.json")

    fp = _load_boot_config().get("pgp_fingerprint", "")
    if fp:
        results["GPG IDENTITY"] = ("ok", f"{fp[:16]}...")
    else:
        results["GPG IDENTITY"] = ("missing", "no key registered")

    return results


# ── Boot config helpers ───────────────────────────────────────────────────────

def _load_boot_config() -> dict:
    if BOOT_CONFIG.exists():
        try:
            return json.loads(BOOT_CONFIG.read_text())
        except Exception:
            pass
    return {}


def _save_boot_config(cfg: dict) -> None:
    BOOT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    BOOT_CONFIG.write_text(json.dumps(cfg, indent=2, default=str))


def needs_boot() -> bool:
    return not _load_boot_config().get("completed", False)


# ── GPG helpers ───────────────────────────────────────────────────────────────

def _gpg(args: list, input_text: str = "") -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["gpg", "--batch", "--yes"] + args,
            input=input_text.encode() if input_text else None,
            capture_output=True,
            timeout=30,
        )
        return result.returncode, result.stdout.decode(), result.stderr.decode()
    except Exception as e:
        return 1, "", str(e)


def gpg_list_keys() -> list[dict]:
    rc, out, _ = _gpg(["--list-secret-keys", "--with-colons", "--with-fingerprint"])
    keys = []
    current = {}
    for line in out.splitlines():
        parts = line.split(":")
        if parts[0] == "sec":
            current = {"fingerprint": "", "uid": "",
                       "created": parts[5] if len(parts) > 5 else ""}
        elif parts[0] == "fpr" and current is not None:
            current["fingerprint"] = parts[9] if len(parts) > 9 else ""
        elif parts[0] == "uid" and current is not None:
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
    keys = gpg_list_keys()
    for k in keys:
        if email in k.get("uid", ""):
            return k["fingerprint"]
    return ""


def gpg_authenticate(fingerprint: str, passphrase: str) -> bool:
    nonce_file = Path("/tmp") / f"willow-auth-{uuid.uuid4().hex[:8]}"
    nonce_file.write_text(str(uuid.uuid4()))
    try:
        rc, _, _ = _gpg([
            "--sign", "--armor",
            "--local-user", fingerprint,
            "--passphrase-fd", "0",
            "--pinentry-mode", "loopback",
            str(nonce_file),
        ], passphrase)
        return rc == 0
    finally:
        nonce_file.unlink(missing_ok=True)
        Path(str(nonce_file) + ".asc").unlink(missing_ok=True)


def gpg_agent_has_key(fingerprint: str) -> bool:
    nonce_file = Path("/tmp") / f"willow-agent-{uuid.uuid4().hex[:8]}"
    nonce_file.write_text(str(uuid.uuid4()))
    try:
        rc, _, _ = _gpg([
            "--sign", "--armor",
            "--local-user", fingerprint,
            "--pinentry-mode", "loopback",
            str(nonce_file),
        ])
        return rc == 0
    finally:
        nonce_file.unlink(missing_ok=True)
        Path(str(nonce_file) + ".asc").unlink(missing_ok=True)


# ── Vault helpers ─────────────────────────────────────────────────────────────

def _vault_init() -> bool:
    try:
        from cryptography.fernet import Fernet
        key_path   = Path.home() / ".willow" / ".master.key"
        vault_path = Path.home() / ".willow" / "vault.db"
        if not key_path.exists():
            key = Fernet.generate_key()
            key_path.write_bytes(key)
            key_path.chmod(0o600)
        conn = sqlite3.connect(str(vault_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS credentials
            (name TEXT PRIMARY KEY, env_key TEXT, value_enc BLOB)""")
        conn.commit()
        conn.close()
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
        conn.execute(
            "INSERT OR REPLACE INTO credentials (name, env_key, value_enc) VALUES (?,?,?)",
            (name, env_key, enc),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _vault_has_key(name: str) -> bool:
    try:
        from cryptography.fernet import Fernet
        key_path   = Path.home() / ".willow" / ".master.key"
        vault_path = Path.home() / ".willow" / "vault.db"
        if not vault_path.exists() or not key_path.exists():
            return False
        f    = Fernet(key_path.read_bytes().strip())
        conn = sqlite3.connect(str(vault_path))
        row  = conn.execute(
            "SELECT value_enc FROM credentials WHERE name=?", (name,)
        ).fetchone()
        conn.close()
        return bool(row and f.decrypt(row[0]))
    except Exception:
        return False


def _test_api_key(api_key: str, provider: str = "groq") -> bool:
    endpoints = {
        "groq":      ("https://api.groq.com/openai/v1/chat/completions",   "llama-3.3-70b-versatile"),
        "cerebras":  ("https://api.cerebras.ai/v1/chat/completions",        "llama3.1-8b"),
        "sambanova": ("https://api.sambanova.ai/v1/chat/completions",       "Meta-Llama-3.3-70B-Instruct"),
    }
    url, model = endpoints.get(provider, endpoints["groq"])
    try:
        import urllib.request
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status == 200
    except Exception:
        return False


# ── Execute helpers (callable from seed.py or direct run) ────────────────────

def _exec_0() -> None:
    """Step 0 — no-op on Linux (WSL2 set up by install.ps1)."""
    pass


def _exec_1() -> None:
    """Step 1 — verify/install dependencies."""
    from seed import ensure_deps
    ensure_deps()


def _exec_2() -> None:
    """Step 2 — check Postgres connection."""
    import psycopg2
    try:
        conn = psycopg2.connect(
            dbname=os.environ.get("WILLOW_PG_DB", "willow"),
            user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
        )
        conn.close()
    except Exception:
        pass


def _exec_3() -> None:
    """Step 3 — GPG key (handled interactively by page_pgp_create)."""
    pass


def _exec_4() -> None:
    """Step 4 — create SAFE folder."""
    from seed import ensure_safe_dir
    ensure_safe_dir()


def _exec_5() -> None:
    """Step 5 — create encrypted vault (handled by vault_action='init')."""
    pass


def _exec_7() -> None:
    """Step 7 — launch dashboard."""
    candidates = [
        Path(__file__).parent.parent / "willow-dashboard" / "dashboard.py",
        Path(__file__).parent / "willow-dashboard" / "dashboard.py",
        Path(__file__).parent / "apps" / "dashboard.py",
    ]
    env_override = os.environ.get("WILLOW_DASHBOARD_PATH", "")
    if env_override:
        candidates.insert(0, Path(env_override))
    for path in candidates:
        if path.exists():
            os.execv(sys.executable, [sys.executable, str(path)])


# ── Corporate training video assets ──────────────────────────────────────────

_CORP_SUNRISE = [
    r"    *    .    *    .    *    .    *    .    *   ",
    r"  .    *    .    *    .    *    .    *    .    *",
    r"                                               ",
    r"              \ | /                            ",
    r"           ----*----                           ",
    r"              / | \                            ",
    r"                                               ",
    r"  ─────────────────────────────────────────── ",
    r" ╱   ~     ~     ~     ~     ~     ~     ~   ╲",
    r"║══════════════════════════════════════════════║",
    r"║══════════════════════════════════════════════║",
]

_CORP_HANDSHAKE = [
    r"                                               ",
    r"    \o/                          \o/           ",
    r"     |                            |            ",
    r"    /|\                          /|\           ",
    r"     |                            |            ",
    r"     |       ┌───────────┐        |            ",
    r"     └───────┤  ≡ ≡ ≡ ≡ ├────────┘            ",
    r"             │  ≡ ≡ ≡ ≡ │                     ",
    r"             └───────────┘                     ",
    r"                                               ",
    r"                                               ",
]

_CORP_MOUNTAIN = [
    r"                        ★                     ",
    r"                       /|\                    ",
    r"                      / | \                   ",
    r"                     /  |  \                  ",
    r"                    / * * * \                 ",
    r"                   /    |    \                ",
    r"                  /  ·  |  ·  \               ",
    r"                 /       |       \             ",
    r"                /    ·   |   ·    \            ",
    r"               /         |         \           ",
    r"              /___________\___________\        ",
]

_CORP_LIGHTBULB = [
    r"          . * . . * . . * . . * .             ",
    r"        *       ┌─────────┐       *           ",
    r"       .       ╱           ╲       .          ",
    r"      *       │  ─────────  │       *         ",
    r"      .       │ │  ~ ~ ~  │ │       .         ",
    r"      *       │ │  ~ ~ ~  │ │       *         ",
    r"      .       │  ─────────  │       .         ",
    r"       *       ╲           ╱       *          ",
    r"        .       └─────────┘       .           ",
    r"       *           │   │           *          ",
    r"        .        ──┘   └──        .           ",
    r"          * .       └───┘     . *             ",
]

_CORP_GLOBE = [
    r"                                               ",
    r"              .───────────.                   ",
    r"            ╱   .─────.    ╲                  ",
    r"           │   ╱ ───── ╲    │                 ",
    r"           │  │  ─────  │   │                 ",
    r"           │  │  ─────  │   │                 ",
    r"           │   ╲ ───── ╱    │                 ",
    r"            ╲    '─────'   ╱                  ",
    r"              '───────────'                   ",
    r"         ─────────────────────────            ",
    r"                                               ",
]

_CORP_SCREENS = [
    {
        "art": _CORP_SUNRISE,
        "slogan": "OUR PEOPLE ARE OUR GREATEST ASSET",
        "dept": "Human Resources Division · Willow Systems Industries",
        "mission": [
            "In 2026, most software sends your data to companies",
            "you have never heard of.",
        ],
    },
    {
        "art": _CORP_HANDSHAKE,
        "slogan": "SYNERGIZING FOR A BETTER TOMORROW",
        "dept": "Team Development & Workplace Excellence",
        "mission": [
            "Your conversations train their models.",
            "Your files index their search.",
            "Your habits build their profiles.",
        ],
    },
    {
        "art": _CORP_MOUNTAIN,
        "slogan": "REACHING NEW HEIGHTS. TOGETHER.",
        "dept": "Leadership & Strategic Growth Initiative",
        "mission": [
            "Willow doesn't do that.",
        ],
    },
    {
        "art": _CORP_LIGHTBULB,
        "slogan": "INNOVATION IS IN OUR DNA",
        "dept": "Office of Innovation & Forward Thinking",
        "mission": [
            "Willow is a personal AI system that runs on your machine.",
            "Your knowledge lives at ~/SAFE/.",
            "Your vault lives at ~/.willow/.",
            "Delete the repo. Your data survives.",
        ],
    },
    {
        "art": _CORP_GLOBE,
        "slogan": "CONNECTED. COMMITTED. COMPLIANT.",
        "dept": "Global Operations & Regulatory Alignment",
        "mission": [
            "No account required.",
            "No cloud required.",
            "No surveillance required.",
            "",
            "This is your system.",
            "FRANK will now explain how it works.",
        ],
    },
]

# ── CRT monitor frame ─────────────────────────────────────────────────────────

_CRT_TOP    = "╔══════════════════════════════════════════════════╗"
_CRT_BOT    = "╚══════════════════════════════════════════════════╝"
_CRT_SIDE_L = "║  "
_CRT_SIDE_R = "  ║"
_CRT_NECK   = "  ╚══════════════════════════════════════════════╝  "
_CRT_BASE   = "  ┌────────────────────────────────────────────────┐  "
_CRT_BASE2  = "  └────────────────────────────────────────────────┘  "
_CRT_W      = 52  # inner width

_BOOT_LINES = [
    ("WILLOW BIOS v4.2",                 "OK"),
    ("Memory Check",                      "OK"),
    ("Storage Interface",                 "OK"),
    ("GPG Security Module",               "OK"),
    ("Loading FRANK.EXE",                 "LOADING"),
]


def page_computer_boot(win):
    """ASCII CRT monitor with BIOS boot sequence."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD

    crt_x  = max(0, (w - len(_CRT_TOP)) // 2)
    crt_y  = max(1, (h - 20) // 2)

    # Draw monitor shell
    _safe(win, crt_y, crt_x, _CRT_TOP, dim)
    screen_h = 10
    for row in range(screen_h):
        _safe(win, crt_y + 1 + row, crt_x, _CRT_SIDE_L, dim)
        _safe(win, crt_y + 1 + row, crt_x + len(_CRT_TOP) - len(_CRT_SIDE_R), _CRT_SIDE_R, dim)
    _safe(win, crt_y + 1 + screen_h, crt_x, _CRT_BOT, dim)
    _safe(win, crt_y + 2 + screen_h, crt_x + 2, _CRT_NECK[2:], dim)
    _safe(win, crt_y + 3 + screen_h, crt_x, _CRT_BASE, dim)
    _safe(win, crt_y + 4 + screen_h, crt_x, _CRT_BASE2, dim)
    win.refresh()
    time.sleep(0.4)

    # BIOS header inside screen
    inner_x = crt_x + 4
    sy = crt_y + 2
    _typewrite(win, sy, inner_x, "WILLOW SYSTEMS INDUSTRIES", bright, delay=0.015)
    sy += 1
    _safe(win, sy, inner_x, "─" * (_CRT_W - 4), dim)
    sy += 1
    win.refresh()
    time.sleep(0.2)

    # Boot lines
    for label, status in _BOOT_LINES:
        dots = "." * max(2, 36 - len(label))
        _safe(win, sy, inner_x, label, dim)
        time.sleep(0.18)
        stat_x = inner_x + len(label) + len(dots) + 1
        if status == "OK":
            _safe(win, sy, inner_x + len(label), dots, dim)
            _safe(win, sy, stat_x, status, green)
        else:
            _safe(win, sy, inner_x + len(label), dots, dim)
            _safe(win, sy, stat_x, status, amber)
        win.refresh()
        time.sleep(0.3)
        sy += 1

    # Progress bar
    sy += 1
    bar_len = _CRT_W - 8
    _safe(win, sy, inner_x, "[", dim)
    _safe(win, sy, inner_x + bar_len + 1, "]", dim)
    for i in range(bar_len):
        _safe(win, sy, inner_x + 1 + i, "█", amber)
        win.refresh()
        time.sleep(0.03)

    sy += 1
    _safe(win, sy, inner_x, "FRANK.EXE ................... READY", green)
    win.refresh()
    time.sleep(0.5)

    _safe(win, crt_y + screen_h - 1, inner_x,
          "PRESS ANY KEY TO BEGIN", curses.color_pair(_CA_DIM))
    win.refresh()

    win.nodelay(False)
    win.getch()
    win.nodelay(True)


def page_training_video(win):
    """Corporate onboarding training video + Willow mission statement."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD

    # ── Splash screen ──────────────────────────────────────────────────────────
    _fill_bg(win)
    title_y = max(2, h // 2 - 4)
    _typewrite(win, title_y,     2, "WILLOW SYSTEMS INDUSTRIES", bright, delay=0.03)
    _typewrite(win, title_y + 2, 2, "CORPORATE ONBOARDING", amber, delay=0.025)
    win.refresh()
    time.sleep(0.6)

    # Loading dots
    loading_y = title_y + 4
    _safe(win, loading_y, 2, "LOADING", dim)
    for i in range(12):
        _safe(win, loading_y, 9 + i, ".", amber)
        win.refresh()
        time.sleep(0.18)

    time.sleep(0.4)
    _fill_bg(win)
    _typewrite(win, h // 2 - 1, max(2, (w - 22) // 2),
               "Welcome.", bright, delay=0.06)
    _safe(win, h // 2 + 1, max(2, (w - 22) // 2),
          "[ start scene ]", dim)
    win.refresh()
    time.sleep(2.0)

    # ── Corporate feel-good screens + interleaved mission text ────────────────
    _PUNCH = {"Willow doesn't do that.",
              "This is your system.",
              "FRANK will now explain how it works."}

    for screen in _CORP_SCREENS:
        # Card
        _fill_bg(win)
        art   = screen["art"]
        art_y = max(1, (h - len(art) - 5) // 2)
        art_x = max(2, (w - len(art[0])) // 2)
        for i, line in enumerate(art):
            _safe(win, art_y + i, art_x, line, dim)
        win.refresh()
        time.sleep(0.3)

        slogan   = screen["slogan"]
        dept     = screen["dept"]
        slogan_y = art_y + len(art) + 1
        _typewrite(win, slogan_y,     max(2, (w - len(slogan)) // 2),
                   slogan, amber, delay=0.018)
        _safe(win, slogan_y + 1, max(2, (w - len(dept)) // 2), dept, dim)
        win.refresh()

        # Drain buffered input, then 5-second hold — any key advances
        win.nodelay(True)
        while win.getch() != -1:
            pass
        start = time.monotonic()
        while time.monotonic() - start < 5.0:
            if win.getch() != -1:
                break
            time.sleep(0.05)

        # Mission chunk
        mission = screen.get("mission", [])
        if mission:
            _fill_bg(win)
            text_x = max(2, (w - 56) // 2)
            my = max(1, (h - len(mission)) // 2)
            for line in mission:
                if my >= h - 2:
                    break
                if not line:
                    my += 1
                    continue
                attr = amber if line in _PUNCH else dim
                delay = 0.03 if line in _PUNCH else 0.014
                _typewrite(win, my, text_x, line, attr, delay=delay)
                my += 1
                win.refresh()
                time.sleep(0.08)

            time.sleep(5.0)

    _safe(win, h - 2, 2, "  Press any key to continue...", dim)
    win.refresh()
    win.nodelay(False)
    win.getch()
    win.nodelay(True)


# ── Pages ─────────────────────────────────────────────────────────────────────

def page_boot_check(win) -> dict:
    """Page 0 — environment probe. Shown to all users on every launch."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)    | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD

    _typewrite(win, 1, 2, "WILLOW", bright, delay=0.012)
    _safe(win, 2, 2, "─" * min(60, w - 4), dim)
    time.sleep(0.2)

    env = check_environment()
    y = 4
    col_name = 4
    col_dots = 26
    col_stat = col_dots + 6

    _typewrite(win, y, 2, "CHECKING ENVIRONMENT...", dim, delay=0.008)
    y += 2
    win.refresh()

    for name, (status, detail) in env.items():
        dots = "." * max(2, col_dots - col_name - len(name))
        _safe(win, y, col_name, name, amber)
        _safe(win, y, col_name + len(name) + 1, dots, dim)
        time.sleep(0.12)
        if status == "ok":
            _safe(win, y, col_stat, f"[ {detail} ]"[:w - col_stat - 2], green)
        else:
            _safe(win, y, col_stat,
                  f"[ {status.upper()} — {detail} ]"[:w - col_stat - 2], red)
        win.refresh()
        y += 1

    y += 1
    all_ok = all(s == "ok" for s, _ in env.values())
    gpg_ok = env.get("GPG IDENTITY", ("missing",))[0] == "ok"
    _safe(win, y, 2, "─" * min(60, w - 4), dim)
    y += 1

    if all_ok:
        _typewrite(win, y, 2, "ALL SYSTEMS NOMINAL", green, delay=0.01)
    elif gpg_ok:
        _typewrite(win, y, 2, "PARTIAL — SOME SERVICES UNAVAILABLE", amber, delay=0.01)
    else:
        _typewrite(win, y, 2, "STANDALONE MODE", amber, delay=0.01)

    win.refresh()
    return env


def page_welcome(win):
    """Page 1 — Heimdallr hero. New users only."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD

    art_x = 4
    art_w = max(len(l) for l in _HEIMDALLR_ART)
    for i, line in enumerate(_HEIMDALLR_ART):
        _safe(win, 2 + i, art_x, line, amber)
    win.refresh()
    time.sleep(0.3)

    wm_x = art_x + art_w + 4
    wm_w = max(len(l) for l in _WILLOW_WORDMARK)
    if wm_x + wm_w < w - 2:
        for i, line in enumerate(_WILLOW_WORDMARK):
            _safe(win, 4 + i, wm_x, line[:w - wm_x - 2], bright)
        text_y = 2 + len(_HEIMDALLR_ART) + 2
    else:
        _safe(win, 4, art_x, "W I L L O W", bright)
        text_y = 7

    win.refresh()
    time.sleep(0.4)

    intro = [
        "",
        "A personal terminal workspace.",
        "Built on your machine.",
        "Answerable only to you.",
        "",
        "I am HEIMDALLR.",
        "I watch the bridge between",
        "what you know and what you're building.",
        "",
        "Before we begin — a few things.",
    ]

    # Scroll lines up from near the bottom of the screen
    bottom_y = h - 4
    shown = []
    for line in intro:
        shown.append(line)
        n = len(shown)
        # Clear text area
        for row in range(max(text_y + 2, bottom_y - n + 1), min(h - 1, bottom_y + 1)):
            _safe(win, row, art_x, " " * max(0, w - art_x - 2), 0)
        # Redraw previous lines at shifted positions (no typewrite)
        for i, sline in enumerate(shown[:-1]):
            y = bottom_y - (n - 1 - i)
            if text_y + 2 <= y < h - 1:
                _safe(win, y, art_x, sline, dim)
        # Typewrite the new line at the bottom
        if line and bottom_y < h - 1:
            _typewrite(win, bottom_y, art_x, line, dim, delay=0.015)
        win.refresh()
        time.sleep(0.07)

    _wait_key(win)


def page_covenant(win):
    """Page 2 — data privacy covenant. New users only."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD

    _typewrite(win, 1, 2, "WHAT THIS SYSTEM KNOWS ABOUT YOU", bright, delay=0.01)
    _safe(win, 2, 2, "─" * min(60, w - 4), dim)
    time.sleep(0.2)

    lines = [
        "",
        "  This system can track a lot.",
        "  Your projects. Your notes. Your habits.",
        "  Your conversations. Your work history.",
        "",
        "  That is the whole point.",
        "",
        "  But here is what makes this different:",
        "",
    ]
    y = _typewrite_lines(win, 3, 2, lines, dim)

    covenants = [
        ("  Everything lives here.",    "On this machine. Nowhere else."),
        ("  Nothing phones home.",       "No telemetry. No analytics. No cloud."),
        ("  You choose what to track.",  "Every data type requires your consent."),
        ("  You own the data.",          "Delete it, export it, or ignore it."),
    ]
    for title, sub in covenants:
        if y >= h - 4:
            break
        _typewrite(win, y, 2, title, amber)
        y += 1
        _safe(win, y, 4, sub, dim)
        y += 2
        win.refresh()
        time.sleep(0.1)

    _wait_key(win)


def page_legal(win) -> bool:
    """Page 3 — MIT + §1.1. Returns True if agreed."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    dim    = curses.color_pair(_CA_DIM)
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)

    box_h, box_w = min(18, h - 4), min(62, w - 4)
    box_x = max(2, (w - box_w) // 2)
    box_y = 2
    _draw_box(win, box_y, box_x, box_h, box_w, curses.color_pair(_CA_BOX))

    content_x = box_x + 3
    y = box_y + 1
    _typewrite(win, y, content_x, "TERMS OF USE", bright, delay=0.01)
    y += 1
    _safe(win, y, content_x, "─" * (box_w - 6), dim)
    y += 2

    terms = [
        ("This software is free.", dim),
        ("Use it. Learn from it. Build with it.", dim),
        ("", dim),
        ("If you make money with it —", amber),
        ("that is a conversation worth having.", amber),
        ("", dim),
        ("Personal use:     always free.", dim),
        ("Commercial use:   written consent required.", dim),
        ("                  rudi193@gmail.com", dim),
        ("", dim),
        ("MIT License · Copyright 2026 Sean Campbell", dim),
        ("§ 1.1 Commercial Consent Clause", dim),
    ]
    for text, attr in terms:
        if y >= box_y + box_h - 3:
            break
        if text:
            _typewrite(win, y, content_x, text, attr, delay=0.004)
        y += 1
        win.refresh()

    prompt_y = box_y + box_h - 2
    _safe(win, prompt_y, content_x, "[ Y ] I understand and agree", green)
    _safe(win, prompt_y, content_x + 32, "[ Q ] Quit", red)
    win.refresh()

    win.nodelay(False)
    while True:
        k = win.getch()
        if k in (ord('y'), ord('Y')):
            win.nodelay(True)
            return True
        if k in (ord('q'), ord('Q'), 27):
            win.nodelay(True)
            return False


def page_path_select(win) -> str:
    """Page 4 — Professional / Casual / Novice. Returns path string."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD

    _typewrite(win, 1, 2, "HOW DO YOU WORK?", bright, delay=0.01)
    _safe(win, 2, 2, "─" * min(60, w - 4), dim)
    time.sleep(0.2)

    paths = [
        ("1", "PROFESSIONAL",
         "I know what I'm doing. Show me everything.",
         "Full config. All cards. Technical detail.", "professional"),
        ("2", "CASUAL",
         "Guide me through it. Plain English is fine.",
         "Guided setup. Curated card set. Simple language.", "casual"),
        ("3", "NEW HERE",
         "I'm new to this kind of tool. Take it slow.",
         "Step by step. Explain as we go. Minimal config.", "novice"),
    ]

    y = 4
    for key, title, desc, sub, _ in paths:
        _safe(win, y, 4, f"[ {key} ]", amber)
        _safe(win, y, 10, title, bright)
        y += 1
        _safe(win, y, 10, desc, dim)
        y += 1
        _safe(win, y, 10, sub, dim)
        y += 2
        win.refresh()
        time.sleep(0.05)

    win.nodelay(False)
    while True:
        k = win.getch()
        for key, title, desc, sub, path in paths:
            if k == ord(key):
                _safe(win, h - 2, 2, f"  Path: {title}", green)
                win.refresh()
                time.sleep(0.4)
                win.nodelay(True)
                return path


def page_pgp_create(win) -> str:
    """GPG key creation for new users. Returns fingerprint."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)

    _typewrite(win, 1, 2, "CREATING YOUR IDENTITY", bright, delay=0.01)
    _safe(win, 2, 2, "─" * min(60, w - 4), dim)
    time.sleep(0.2)

    intro = [
        "",
        "  A GPG key pair will be generated on this machine.",
        "  Your private key never leaves here.",
        "  Your fingerprint identifies you to the Willow system.",
        "",
    ]
    y = _typewrite_lines(win, 2, 2, intro, dim)
    win.refresh()

    def _get_input(prompt_y, label):
        _safe(win, prompt_y, 4, label, amber)
        curses.curs_set(1)
        curses.echo()
        win.nodelay(False)
        _safe(win, prompt_y, 4 + len(label) + 1, " " * 40, dim)
        win.move(prompt_y, 4 + len(label) + 1)
        val = win.getstr(40).decode().strip()
        curses.noecho()
        curses.curs_set(0)
        return val

    def _get_password(prompt_y, label):
        _safe(win, prompt_y, 4, label, amber)
        curses.curs_set(1)
        win.nodelay(False)
        win.keypad(True)
        _safe(win, prompt_y, 4 + len(label) + 1, " " * 40, dim)
        win.move(prompt_y, 4 + len(label) + 1)
        pwd = ""
        cx = 4 + len(label) + 1
        while True:
            k = win.getch()
            if k in (curses.KEY_ENTER, 10, 13):
                break
            elif k in (curses.KEY_BACKSPACE, 127):
                if pwd:
                    pwd = pwd[:-1]
                    cx -= 1
                    _safe(win, prompt_y, cx, " ", dim)
                    win.move(prompt_y, cx)
            elif 32 <= k <= 126:
                pwd += chr(k)
                _safe(win, prompt_y, cx, "*", amber)
                cx += 1
                win.move(prompt_y, cx)
            win.refresh()
        curses.curs_set(0)
        return pwd

    while True:
        name       = _get_input(y,     "Name ............. ")
        email      = _get_input(y + 1, "Email ............ ")
        passphrase = _get_password(y + 2, "Passphrase ....... ")
        confirm    = _get_password(y + 3, "Confirm .......... ")

        if passphrase != confirm:
            _safe(win, y + 5, 4, "Passphrases do not match. Try again.", red)
            win.refresh()
            time.sleep(1.5)
            _safe(win, y + 5, 4, " " * 40, dim)
            continue

        if len(passphrase) < 8:
            _safe(win, y + 5, 4, "Passphrase too short (min 8 chars).", red)
            win.refresh()
            time.sleep(1.5)
            _safe(win, y + 5, 4, " " * 50, dim)
            continue

        break

    _safe(win, y + 5, 4, "Generating key pair...", dim)
    win.refresh()

    fingerprint = gpg_create_key(name, email, passphrase)

    if fingerprint:
        _safe(win, y + 6, 4, "Key created.", green)
        _safe(win, y + 7, 4, f"Fingerprint: {fingerprint[:32]}...", dim)
        win.refresh()
        time.sleep(1.0)
        from seed import write_fingerprint_to_profile
        write_fingerprint_to_profile(fingerprint)
    else:
        _safe(win, y + 6, 4, "Key generation failed. Check gpg is installed.", red)
        win.refresh()
        time.sleep(2.0)

    win.nodelay(True)
    return fingerprint


def page_pgp_auth(win, fingerprint: str, agent_name: str) -> bool:
    """Returning user auth. Returns True if authenticated."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    bright = curses.color_pair(_CA_BRIGHT) | curses.A_BOLD
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)

    _typewrite(win, 1, 2, f"WELCOME BACK, {agent_name.upper()}", bright, delay=0.01)
    _safe(win, 2, 2, "─" * min(60, w - 4), dim)
    _safe(win, 4, 4, f"Fingerprint: {fingerprint[:32]}...", dim)
    win.refresh()
    time.sleep(0.2)

    _safe(win, 5, 4, "Checking GPG agent...", dim)
    win.refresh()
    if gpg_agent_has_key(fingerprint):
        _safe(win, 5, 4, "✓  AUTHENTICATED VIA GPG AGENT          ", green)
        win.refresh()
        time.sleep(0.8)
        return True

    _safe(win, 5, 4, "Enter passphrase to unlock.             ", dim)

    def _get_password(prompt_y):
        _safe(win, prompt_y, 4, "Passphrase ....... ", amber)
        curses.curs_set(1)
        win.nodelay(False)
        win.keypad(True)
        pwd = ""
        cx = 4 + 19
        win.move(prompt_y, cx)
        while True:
            k = win.getch()
            if k in (curses.KEY_ENTER, 10, 13):
                break
            elif k in (curses.KEY_BACKSPACE, 127):
                if pwd:
                    pwd = pwd[:-1]
                    cx -= 1
                    _safe(win, prompt_y, cx, " ", dim)
                    win.move(prompt_y, cx)
            elif k in (ord('q'), ord('Q'), 27):
                curses.curs_set(0)
                return None
            elif 32 <= k <= 126:
                pwd += chr(k)
                _safe(win, prompt_y, cx, "*", amber)
                cx += 1
                win.move(prompt_y, cx)
            win.refresh()
        curses.curs_set(0)
        return pwd

    attempts = 0
    while attempts < 3:
        passphrase = _get_password(7)
        if passphrase is None:
            win.nodelay(True)
            return False
        _safe(win, 9, 4, "Verifying...", dim)
        win.refresh()
        if gpg_authenticate(fingerprint, passphrase):
            _safe(win, 9, 4, "✓  AUTHENTICATED                        ", green)
            win.refresh()
            time.sleep(0.6)
            win.nodelay(True)
            return True
        else:
            attempts += 1
            remaining = 3 - attempts
            msg = f"Incorrect. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
            _safe(win, 9, 4, msg, red)
            win.refresh()
            time.sleep(1.0)
            _safe(win, 9, 4, " " * 50, dim)
            _safe(win, 7, 4, "Passphrase ....... " + " " * 30, dim)

    win.nodelay(True)
    return False


# ── FRANK step definitions ────────────────────────────────────────────────────

_FRANK_TITLE_CARD = [
    "┌─────────────────────────────────────┐",
    "│  FRANK                              │",
    "│  Head Agent                         │",
    "│  Willow Compliance & Onboarding     │",
    "└─────────────────────────────────────┘",
]

_FRANK_STEPS = [
    {
        "rune": "ᚷᛁᚾᚾᚢᚾᚷᚨᚷᚨᛈ", "name": "GINNUNGAGAP",
        "bot": "Good morning. You have selected: soup.",
        "correction": (
            "That is not what it says. These runes spell GINNUNGAGAP. "
            "The primordial void. Please correct your translation matrix."
        ),
        "norse": [
            "Before the world: the void. Not darkness — the absence of anything to be dark.",
            "Ice breathed down from the north. Fire breathed up from the south.",
            "They met in the middle. Something happened.",
        ],
        "compliance": [
            "Initializing virtual Linux environment.",
            "FRANK notes the Ginnungagap precondition assessment has been pending since before time.",
            "A completion estimate was filed. It was absorbed by the void. Technically a response.",
        ],
        "plain": [
            "WSL2: a small Linux computer that lives inside your Windows computer.",
            "On Linux, this step is already done. You are already here.",
            "Your Windows files are untouched. Think of it as a studio apartment with its own kitchen.",
        ],
        "install": [
            ("WSL2",         "Linux environment inside Windows"),
            ("Ubuntu 22.04", "the Linux that runs inside WSL2"),
        ],
        "post_beat": "Ginnungagap assessment: COMPLETE. Filed: now. Acknowledged: [pending]. It fades.",
        "vault_action": None,
    },
    {
        "rune": "ᚤᚷᚷᛞᚱᚨᛊᛁᛚᛚ", "name": "YGGDRASIL",
        "bot": "Congratulations on your new refrigerator.",
        "correction": (
            "YGGDRASILL. The world tree. Not a refrigerator. "
            "We have discussed this. There are no refrigerators in the Prose Edda."
        ),
        "norse": [
            "The world tree grows through all nine realms.",
            "Its roots reach Asgard above, Mimir's well below, and the frost realm beyond.",
            "An eagle lives in its branches. A dragon gnaws its roots.",
            "They have hated each other since the beginning.",
            "A squirrel named Ratatoskr carries messages between them.",
            "The messages make everything worse.",
        ],
        "compliance": [
            "Verifying system dependencies.",
            "The Ratatoskr communication protocol has been flagged in four previous audits.",
            "The squirrel has not acknowledged these findings. This is considered normal operations.",
        ],
        "plain": [
            "We are checking that Python, PostgreSQL, and GPG exist on your machine.",
            "If anything is missing, we will install it.",
            "You will be asked before each one. Nothing installs without your agreement.",
        ],
        "install": [
            ("python3.11+",  "the language Willow is written in"),
            ("postgresql",   "your personal database (filing cabinet)"),
            ("gpg",          "cryptographic key generation"),
            ("pip",          "Python package manager"),
        ],
        "post_beat": "A small golden-brown shape waddles across the terminal. It is glistening. FRANK has logged it.",
        "vault_action": None,
    },
    {
        "rune": "ᛗᛁᛗᛁᚱᛊ ᛒᚱᚢᚾᚾᚱ", "name": "MIMIR'S WELL",
        "bot": "Your table is ready. Party of one.",
        "correction": (
            "MIMIR'S BRUNNR. The Well of Wisdom. Not a restaurant. "
            "Although — and FRANK acknowledges this — the seating situation "
            "at Mimir's Well is also party of one. FRANK can see where the confusion arose. "
            "It is still wrong."
        ),
        "norse": [
            "Mimir's Well sits beneath the second root of Yggdrasil.",
            "It contains all the wisdom in the universe.",
            "Odin wanted a drink. Mimir said the price was one eye.",
            "Odin removed his eye, handed it over, and drank.",
            "He never got it back. Mimir keeps it at the bottom of the well.",
            "He has not been asked about this.",
        ],
        "compliance": [
            "Connecting to your local memory store.",
            "FRANK submitted a Freedom of Information request for 'all of it.' Denied: too broad.",
            "Odin's eye: logged as lost property. Two reminders sent. Eye unclaimed.",
        ],
        "plain": [
            "We are starting your personal database.",
            "This database lives entirely on your computer. It never calls home.",
            "It stores your conversations, documents, knowledge.",
            "No company has access to it. Not even us.",
        ],
        "install": [
            ("postgresql",    "local database (~50MB on disk)"),
            ("willow schema", "the tables Willow uses"),
        ],
        "post_beat": "Lost property: one (1) eye, divine grade, c. 1000 BCE. Contact: FRANK, ext. [missing]. Always missing.",
        "vault_action": None,
    },
    {
        "rune": "ᚨᚾᛊᚢᛉ", "name": "ANSUZ",
        "bot": "This symbol means: free WiFi available.",
        "correction": (
            "ANSUZ. Odin's rune. Divine communication. Wisdom obtained at considerable personal cost. "
            "It does not mean free WiFi. "
            "Odin hung from a tree for nine days. There was no WiFi. This is part of why he was there."
        ),
        "norse": [
            "Odin hung from Yggdrasil for nine days.",
            "He had stabbed himself with his own spear. He did not eat. He did not drink.",
            "Below him was nothing. He stared into nothing until something stared back.",
            "On the ninth day, the runes appeared. He grabbed them and fell.",
            "He did not explain where he had been.",
        ],
        "compliance": [
            "Generating your cryptographic identity. Estimated time: 30 seconds.",
            "Odin's comparable operation: nine days, one self-inflicted spear wound, sensory deprivation.",
            "FRANK submitted three efficiency proposals. Found nailed to a tree. This is considered receipt.",
        ],
        "plain": [
            "We are creating a key that is mathematically unique to you.",
            "Large enough that guessing it would take longer than the universe has existed.",
            "Files you sign with it cannot be secretly changed — if tampered, the signature breaks.",
            "This is how the gate recognises you.",
        ],
        "install": [
            ("gnupg 2.4+",       "key generation (~2MB)"),
            ("4096-bit RSA key",  "your identity (~30sec)"),
        ],
        "post_beat": "Squeakdog transit logged. Direction: east. Authorization: unclear. Filed under: ambient.",
        "vault_action": None,
    },
    {
        "rune": "ᚨᛊᚷᚨᚱᛞᚱ", "name": "ASGARD",
        "bot": "mild sauce",
        "correction": (
            "It says ASGARD. Home of the gods. Realm of Odin, Thor, Freya, and — FRANK stops. "
            "Is this intentional? FRANK has been working with you since before the current universe "
            "and there are patterns here that FRANK finds concerning. Mild sauce. "
            "FRANK would like you to explain mild sauce.\n"
            "BOT: mild sauce\n"
            "...We are moving on."
        ),
        "norse": [
            "The gods needed a hall. They hired a frost giant.",
            "He said he could build it in one winter if they gave him the sun, the moon, and Freya.",
            "The gods said no. He started anyway, and he was going to finish in time.",
            "Loki turned into a mare to distract his horse. The giant died. The hall was built.",
            "Loki was a horse for a while. This is considered a success story in the primary sources.",
        ],
        "compliance": [
            "Creating your secure application directory.",
            "The original Asgard construction contract: seventeen unresolved amendments.",
            "None settled in eleven thousand years. Loki declined the calendar invite. Without comment.",
        ],
        "plain": [
            "We are creating a folder called SAFE on your computer.",
            "Applications are not allowed to enter without a signed pass — called a manifest.",
            "No manifest, no entry. Revoke any app at any time by deleting its folder.",
            "This is the gate Heimdallr holds.",
        ],
        "install": [
            ("~/SAFE/Applications/", "your sovereign data folder"),
            ("manifests",            "signed passes for each application"),
        ],
        "post_beat": "Asgard construction review: RESCHEDULED (FINAL). Date: today. FRANK has highlighted it.",
        "vault_action": None,
    },
    {
        "rune": "ᚨᚾᛞᚢᚨᚱᛁ", "name": "ANDVARI",
        "bot": "[Papyrus]  garage sale",
        "correction": (
            "ANDVARI. The dwarf. The gold. The curse. The fish. "
            "FRANK has explained this. In multiple formats. Including a laminated reference card "
            "which FRANK is fairly certain you were given at orientation. "
            "Do you still have that card. Do not tell FRANK you do not still have that card.\n"
            "Also. The font. Papyrus is not a backup font. Papyrus is not any font. "
            "FRANK did not authorize Papyrus. These are Elder Futhark runes. 2nd century. "
            "Papyrus is from Microsoft Office 1994. "
            "The gap between these two things is FRANK's entire problem with you in one font choice.\n"
            "FRANK is going to take a moment.\n"
            "[pause]\n"
            "FRANK has taken a moment. We are continuing."
        ),
        "norse": [
            "Andvari was a dwarf who lived in a waterfall disguised as a fish and hoarded gold.",
            "Loki caught him and took everything — every coin.",
            "As Andvari handed over the last piece, he cursed it:",
            "the gold would destroy every person who owned it. Every. Single. One.",
            "Loki passed this information along to the next owners. He found this extremely funny.",
        ],
        "compliance": [
            "Encrypting your credential vault.",
            "Unlike Andvari's gold, this vault does not carry a destruction curse. FRANK verified this.",
            "Loki disclosed the curse in writing before transfer. Which satisfies the notification requirement.",
        ],
        "plain": [
            "We are creating an encrypted vault for your API keys.",
            "Your keys are never stored in plain text — scrambled using AES-128 encryption.",
            "The vault is unlocked by your GPG key, which only you have.",
            "If someone steals your laptop, they cannot read your keys without your passphrase.",
        ],
        "install": [
            ("cryptography",       "Python encryption library (~5MB)"),
            ("~/.willow_creds.db", "your encrypted credential store"),
        ],
        "post_beat": "Andvari curse assessment: NEGATIVE. Certification on file. Counter-signature from Loki: [ignored]. Expected.",
        "vault_action": "init",
    },
]

_FRANK_STEP_7 = {
    "rune": "ᚤᚷᚷᛞᚱᚨᛊᛁᛚᛚ ᛊᛏᛖᚾᛞᚱ", "name": "YGGDRASIL STANDS",
    "bot": "Final translation: have a nice day :)",
    "correction": (
        "...That one is actually fine.\n"
        "[beat]\n"
        "Do not tell anyone FRANK said that."
    ),
    "norse": [
        "The nine realms hang from Yggdrasil like fruit.",
        "Asgard above. Midgard in the middle.",
        "The rest arranged in ways that stopped making geometric sense around 300 CE.",
        "The tree holds all of it. It has always held all of it.",
        "It will hold all of it until Ragnarok — after which, it will hold it again.",
    ],
    "compliance": [
        "Onboarding complete. You have been registered in the system.",
        "You have been assigned a realm. It is Midgard. This is where humans go.",
        "The acceptable use policy has been attached to the world tree. FRANK will be here.",
    ],
    "plain": [
        "Setup is complete. Your database is running. Your key exists.",
        "Your vault is sealed. Your AI is connected. Your dashboard is ready.",
        "Everything that follows belongs to you.",
    ],
    "install": [],
    "post_beat": (
        "The terminal clears. The dashboard opens. "
        "Somewhere in the distance, something that may or may not be "
        "a headless rotisserie chicken rotates slowly in satisfaction. "
        "FRANK has filed a completion report. It has been acknowledged. "
        "This has never happened before. FRANK has noted it."
    ),
    "vault_action": None,
}


# ── FRANK pages ───────────────────────────────────────────────────────────────

def page_frank_step(win, step: dict) -> str:
    """Render one FRANK step. Returns 'continue' or 'quit'."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)
    bar    = "━" * min(w - 4, 46)
    y      = 1

    _typewrite(win, y, 2, step["rune"], amber, delay=0.025)
    _safe(win, y, 2 + len(step["rune"]) + 2, f"— {step['name']}", dim)
    y += 1
    _safe(win, y, 2, bar, dim)
    y += 2

    if h >= 32 and step.get("bot"):
        _safe(win, y, 2, f'BOT: "{step["bot"]}"', dim)
        y += 1
        for line in step.get("correction", "").split("\n")[:4]:
            if y >= h - 14:
                break
            _typewrite(win, y, 2, f"FRANK: {line}", amber, delay=0.004)
            y += 1
        y += 1

    for line in step.get("norse", []):
        if y >= h - 10:
            break
        _typewrite(win, y, 2, line, dim, delay=0.004)
        y += 1
    y += 1

    for line in step.get("compliance", [])[:3]:
        if y >= h - 7:
            break
        _safe(win, y, 2, line, curses.color_pair(_CA_AMBER))
        y += 1
    y += 1

    for line in step.get("plain", []):
        if y >= h - 4:
            break
        _safe(win, y, 2, line, dim)
        y += 1
    y += 1

    for pkg, desc in step.get("install", [])[:3]:
        if y >= h - 3:
            break
        _safe(win, y, 4, f"{pkg:<24} {desc}", green)
        y += 1

    footer_y = min(h - 2, y + 1)
    _safe(win, footer_y - 1, 2, bar, dim)
    _safe(win, footer_y, 2, "  [ENTER] continue   [Q] quit", dim)
    win.refresh()

    win.nodelay(False)
    while True:
        k = win.getch()
        if k in (curses.KEY_ENTER, 10, 13, ord(' ')):
            break
        if k in (ord('q'), ord('Q'), 27):
            win.nodelay(True)
            return "quit"

    if step.get("post_beat"):
        _fill_bg(win)
        beat = step["post_beat"]
        # Wrap long post_beat text across lines
        words = beat.split()
        lines = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > w - 8:
                lines.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            lines.append(current)
        start_y = max(1, (h - len(lines)) // 2)
        for i, line in enumerate(lines):
            bx = max(2, (w - len(line)) // 2)
            _typewrite(win, start_y + i, bx, line, curses.color_pair(_CA_DIM), delay=0.005)
        win.refresh()
        time.sleep(1.8)

    win.nodelay(True)
    return "continue"


def page_frank_huginn(win) -> str:
    """Step 6 — HUGINN & MUNINN. API key collection. Returns 'continue' or 'quit'."""
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER)  | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)
    green  = curses.color_pair(_CA_GREEN)  | curses.A_BOLD
    red    = curses.color_pair(_CA_RED)
    bar    = "━" * min(w - 4, 46)
    y      = 1

    _typewrite(win, y, 2, "ᚺᚢᚷᛁᚾᚾ ᛟᚲ ᛗᚢᚾᛁᚾᚾ", amber, delay=0.025)
    _safe(win, y, 28, "— HUGINN & MUNINN", dim)
    y += 1
    _safe(win, y, 2, bar, dim)
    y += 2

    if h >= 30:
        _safe(win, y, 2,
              'BOT: "These ancient symbols foretell: a two-for-one deal on pasta."', dim)
        y += 1
        frank_lines = [
            "FRANK: These are the names of Odin's ravens. Huginn. Muninn. Thought and Memory.",
            "FRANK: Fourteen performance reviews. The runes do not say pasta. They have never said pasta.",
            "FRANK: FRANK is rambling. FRANK is aware. This is not professional. FRANK apologizes.",
        ]
        for line in frank_lines:
            if y >= h - 14:
                break
            _typewrite(win, y, 2, line, amber, delay=0.004)
            y += 1
        y += 1

    norse = [
        "Every morning Odin sends two ravens across the nine realms:",
        "Huginn (Thought) and Muninn (Memory).",
        "They fly out at dawn and return at dinner with everything they saw and heard.",
        "Odin worries more about Muninn.",
        "Thought you can reconstruct. Memory, once gone, does not come back.",
    ]
    for line in norse:
        if y >= h - 10:
            break
        _typewrite(win, y, 2, line, dim, delay=0.004)
        y += 1
    y += 1

    plain = [
        "Groq gives free access to large language models — fast chips, no cost to you.",
        "Create a free account at groq.com and paste your API key below.",
        "The key is tested live before saving. Nobody else sees it.",
    ]
    for line in plain:
        if y >= h - 6:
            break
        _safe(win, y, 2, line, dim)
        y += 1
    y += 1

    if _vault_has_key("GROQ_API_KEY"):
        _safe(win, y, 2, "✓  Groq API key already in vault.", green)
        _safe(win, y + 2, 2, bar, dim)
        _safe(win, y + 3, 2, "  [ENTER] continue", dim)
        win.refresh()
        win.nodelay(False)
        win.getch()
        win.nodelay(True)
        return "continue"

    input_y = min(y, h - 5)
    _safe(win, input_y, 2, "Groq API key: ", amber)
    win.refresh()
    curses.curs_set(1)
    curses.echo()
    win.nodelay(False)
    win.move(input_y, 16)
    raw_key = win.getstr(80).decode().strip()
    curses.noecho()
    curses.curs_set(0)

    if not raw_key:
        _safe(win, input_y + 1, 2, "Skipped — add later from the dashboard.", dim)
        win.refresh()
        time.sleep(1.5)
        win.nodelay(True)
        return "continue"

    _safe(win, input_y + 1, 2, "Testing...                              ", dim)
    win.refresh()

    if _test_api_key(raw_key, "groq"):
        _vault_write("GROQ_API_KEY", "GROQ_API_KEY", raw_key)
        _safe(win, input_y + 1, 2,
              "✓  Huginn dispatched. Key saved to vault.         ", green)
        win.refresh()
        time.sleep(0.8)

        opt_y = min(input_y + 3, h - 4)
        if opt_y < h - 2:
            _safe(win, opt_y, 2, "Add Cerebras? [Y/N]  (free tier, fast)", dim)
            win.refresh()
            win.nodelay(False)
            k = win.getch()
            win.nodelay(True)
            if k in (ord('y'), ord('Y')):
                _safe(win, opt_y, 2, "Cerebras API key: " + " " * 20, dim)
                win.refresh()
                curses.curs_set(1)
                curses.echo()
                win.nodelay(False)
                win.move(opt_y, 20)
                cb_key = win.getstr(80).decode().strip()
                curses.noecho()
                curses.curs_set(0)
                if cb_key:
                    _safe(win, opt_y + 1, 2, "Testing...", dim)
                    win.refresh()
                    if _test_api_key(cb_key, "cerebras"):
                        _vault_write("CEREBRAS_API_KEY", "CEREBRAS_API_KEY", cb_key)
                        _safe(win, opt_y + 1, 2,
                              "✓  Cerebras saved.                       ", green)
                    else:
                        _safe(win, opt_y + 1, 2,
                              "Key rejected. Add later from dashboard.  ", red)
                    win.refresh()
                    time.sleep(0.8)
    else:
        _safe(win, input_y + 1, 2,
              "Key rejected — check it at groq.com/keys. Add later from dashboard.", red)
        win.refresh()
        time.sleep(2.0)

    _safe(win, h - 2, 2, "  [any key] continue", dim)
    win.refresh()
    win.nodelay(False)
    win.getch()
    win.nodelay(True)
    return "continue"


# ── FRANK onboarding ──────────────────────────────────────────────────────────

def frank_onboarding(win) -> bool:
    """Run the full FRANK onboarding. Returns True if completed."""
    _blog("frank_onboarding: start")
    _fill_bg(win)
    h, w   = win.getmaxyx()
    amber  = curses.color_pair(_CA_AMBER) | curses.A_BOLD
    dim    = curses.color_pair(_CA_DIM)

    # Title card
    card_x = max(2, (w - 41) // 2)
    card_y = max(1, (h - len(_FRANK_TITLE_CARD) - 3) // 2)
    for i, line in enumerate(_FRANK_TITLE_CARD):
        _typewrite(win, card_y + i, card_x, line, amber, delay=0.008)
    _typewrite(
        win, card_y + len(_FRANK_TITLE_CARD) + 1, card_x,
        "FRANK was here before the world tree. He will be here after. He has a ledger.",
        dim, delay=0.005,
    )
    win.refresh()
    time.sleep(1.0)
    _wait_key(win)

    for step in _FRANK_STEPS:
        _blog(f"frank_onboarding: step {step['name']}")
        result = page_frank_step(win, step)
        if result == "quit":
            return False
        if step.get("vault_action") == "init":
            _blog("frank_onboarding: vault init")
            _fill_bg(win)
            _safe(win, h // 2, 4, "Initialising vault...", dim)
            win.refresh()
            time.sleep(0.3)
            vault_ok = _vault_init()
            msg = ("✓  Vault ready."
                   if vault_ok else "⚠  Vault init failed — add keys later from dashboard.")
            _safe(win, h // 2 + 1, 4, msg,
                  curses.color_pair(_CA_GREEN) if vault_ok else curses.color_pair(_CA_RED))
            win.refresh()
            time.sleep(0.9)

    _blog("frank_onboarding: step HUGINN")
    if page_frank_huginn(win) == "quit":
        return False

    _blog("frank_onboarding: step YGGDRASIL STANDS")
    if page_frank_step(win, _FRANK_STEP_7) == "quit":
        return False

    _blog("frank_onboarding: complete")
    return True


# ── Main boot orchestrator ────────────────────────────────────────────────────

def run_boot(stdscr):
    """Full boot sequence. Returns completed boot config dict."""
    _blog("run_boot: start")
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.nodelay(True)
    stdscr.timeout(50)

    _init_boot_colors()
    stdscr.bkgd(' ', curses.color_pair(_CA_AMBER))

    cfg    = _load_boot_config()
    is_new = not cfg.get("completed", False)
    _blog(f"run_boot: is_new={is_new}")

    _blog("run_boot: page_boot_check")
    env = page_boot_check(stdscr)

    if is_new:
        _wait_key(stdscr)

        _blog("run_boot: page_computer_boot")
        page_computer_boot(stdscr)
        _blog("run_boot: page_training_video")
        page_training_video(stdscr)

        _blog("run_boot: page_welcome")
        page_welcome(stdscr)
        _blog("run_boot: page_covenant")
        page_covenant(stdscr)

        _blog("run_boot: page_legal")
        if not page_legal(stdscr):
            _blog("run_boot: quit at legal")
            return None

        _blog("run_boot: page_path_select")
        path = page_path_select(stdscr)
        _blog(f"run_boot: path={path}")

        _blog("run_boot: page_pgp_create")
        fingerprint = page_pgp_create(stdscr)
        _blog(f"run_boot: fingerprint={'ok' if fingerprint else 'EMPTY'}")

        frank_onboarding(stdscr)

        cfg = {
            "completed":      True,
            "first_run_at":   datetime.now().isoformat(),
            "path":           path,
            "pgp_fingerprint": fingerprint,
            "agreed_license":  True,
            "agreed_covenant": True,
            "agent_name":     os.environ.get("WILLOW_AGENT_NAME", "heimdallr"),
        }
        _save_boot_config(cfg)
        _blog("run_boot: config saved")

        if fingerprint:
            os.environ["WILLOW_PGP_FINGERPRINT"] = fingerprint

    else:
        fingerprint = cfg.get("pgp_fingerprint", "")
        agent_name  = cfg.get("agent_name",
                              os.environ.get("WILLOW_AGENT_NAME", "heimdallr"))
        _blog(f"run_boot: returning user={agent_name}")

        if fingerprint:
            _blog("run_boot: page_pgp_auth")
            if not page_pgp_auth(stdscr, fingerprint, agent_name):
                return None
            os.environ["WILLOW_PGP_FINGERPRINT"] = fingerprint
        else:
            h, _ = stdscr.getmaxyx()
            _safe(stdscr, h - 3, 2,
                  "No identity found. Creating key...", curses.color_pair(_CA_AMBER))
            stdscr.refresh()
            time.sleep(1.0)
            fingerprint = page_pgp_create(stdscr)
            cfg["pgp_fingerprint"] = fingerprint
            cfg["last_boot_at"] = datetime.now().isoformat()
            _save_boot_config(cfg)
            if fingerprint:
                os.environ["WILLOW_PGP_FINGERPRINT"] = fingerprint

        cfg["last_boot_at"] = datetime.now().isoformat()
        _save_boot_config(cfg)

        h, w = stdscr.getmaxyx()
        _safe(stdscr, h - 2, 2, "  Loading dashboard...", curses.color_pair(_CA_GREEN))
        stdscr.refresh()
        time.sleep(0.6)

    _blog("run_boot: complete")
    return cfg


def boot() -> dict | None:
    """Entry point. Run the boot sequence. Returns config or None if aborted."""
    import traceback
    BOOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    _blog(f"boot: starting — python {sys.version.split()[0]}")
    result = {}
    try:
        def _run(stdscr):
            nonlocal result
            result = run_boot(stdscr)
        curses.wrapper(_run)
    except Exception as e:
        _blog(f"CRASH: {type(e).__name__}: {e}")
        _blog(traceback.format_exc())
        raise
    _blog(f"boot: done — result={'ok' if result else 'None'}")
    return result


if __name__ == "__main__":
    cfg = boot()
    if cfg:
        print(f"Boot complete. Path: {cfg.get('path')}  FP: {cfg.get('pgp_fingerprint','none')[:16]}")
        print(f"Log: {BOOT_LOG}")
    else:
        print(f"Boot aborted. Log: {BOOT_LOG}")
