"""
fleet.py — Grove FleetManager
b17: FLEET1  ΔΣ=42

Spawns fleet services on Grove open, terminates them on close.
Restart policy: backoff + alert callback on 3rd failure (once per service).
Per-service restart_policy: "always" (default) | "on_failure" (skip clean rc=0 exits).
"""
import logging
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

_LOG_LOCK = threading.Lock()

_REPO_ROOT   = Path(__file__).parent
_VENV_DEV    = _REPO_ROOT / ".venv-dev" / "bin" / "python3"
_VENV_PYTHON = Path.home() / ".willow-venv" / "bin" / "python3"
_SYS_PYTHON  = "/usr/bin/python3"
_AGENTS_BIN  = Path.home() / "agents" / "hanuman" / "bin"
_GROVE_DIR   = Path(__file__).parent
_PY          = str(_VENV_DEV) if _VENV_DEV.exists() else (str(_VENV_PYTHON) if _VENV_PYTHON.exists() else _SYS_PYTHON)
_LOG_FILE    = Path.home() / ".willow" / "fleet.log"
_PID_FILE    = Path.home() / ".willow" / "grove.pid"

_log = logging.getLogger("fleet")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(_LOG_FILE)
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s fleet: %(message)s"))
    _log.addHandler(_fh)
    _log.propagate = False

# corpus_watcher is intentionally excluded from the automatic fleet.
# Governance note in corpus-watcher.py: "Must be started by human action only."
# It watches ~/  via inotify and is resource-heavy. Enable via Grove Settings.
_SERVICES: dict[str, dict] = {
    "grove_serve": {
        "cmd": [_PY, str(_GROVE_DIR / "grove_serve.py"), "--host", "127.0.0.1", "--port", "7777"],
        "cwd": str(_GROVE_DIR),
        "env": {"WILLOW_PG_DB": "willow_19", "WILLOW_PG_USER": os.environ.get("USER", "")},
        "port": 7777,                    # GAP 1: checked before spawn
        "restart_policy": "always",
    },
    "journal_responder": {
        "cmd": [_SYS_PYTHON, str(_AGENTS_BIN / "journal_responder.py")],
        "cwd": str(_AGENTS_BIN),
        "env": {"JANE_MODEL": "yggdrasil:v9"},
        "restart_policy": "on_failure",  # GAP 2: clean rc=0 exit = work done, don't respawn
    },
    "journal_watcher": {
        "cmd": [_SYS_PYTHON, str(_AGENTS_BIN / "journal_watcher.py")],
        "cwd": str(_AGENTS_BIN),
        "env": {},
        "restart_policy": "always",
    },
}

_MAX_SILENT_RESTARTS = 2      # Alert after 3 failures (once per service)
_CIRCUIT_BREAKER_THRESHOLD = 10  # Stop retrying after this many failures (GAP 1: prevent infinite crash loops)
_BACKOFF_BASE_SECS   = 5
_BACKOFF_MAX_SECS    = 120


def _port_in_use(port: int) -> bool:
    """Return True if something is already bound to port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def already_running() -> bool:
    """Return True if another Grove instance owns the PID file."""
    try:
        pid = int(_PID_FILE.read_text().strip())
        # Check if that PID is actually alive
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def _write_pid() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def _clear_pid() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


class FleetManager:
    """Owns the lifecycle of all Grove fleet services."""

    def __init__(self, on_alert: Callable[[str, int], None] | None = None) -> None:
        self._on_alert       = on_alert
        self._procs:         dict[str, subprocess.Popen] = {}
        self._failures:      dict[str, int]              = {}
        self._next_retry_at: dict[str, float]            = {}  # GAP 1: backoff timestamps
        self._alerted:       set[str]                    = set()
        self._running        = False
        self._monitor        = threading.Thread(target=self._watch_loop, daemon=True)

    def start(self) -> None:
        _write_pid()
        self._running = True
        for name, cfg in _SERVICES.items():
            self._failures[name] = 0
            self._next_retry_at[name] = 0.0
            self._spawn(name, cfg)
        self._monitor.start()
        with _LOG_LOCK:
            _log.info("FleetManager started. Services: %s", list(_SERVICES))

    def stop(self) -> None:
        self._running = False
        for name, proc in list(self._procs.items()):
            try:
                proc.terminate()
                proc.wait(timeout=5)
                _log.info("Stopped %s (PID %d)", name, proc.pid)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._procs.clear()
        _clear_pid()
        _log.info("FleetManager stopped.")

    def status(self) -> dict[str, str]:
        result = {}
        for name in _SERVICES:
            proc = self._procs.get(name)
            if proc is None:
                result[name] = "stopped"
            elif proc.poll() is None:
                result[name] = "running"
            else:
                result[name] = f"dead (rc={proc.returncode})"
        return result

    def _spawn(self, name: str, cfg: dict) -> None:
        # GAP 1: circuit breaker — stop trying if too many failures
        if self._failures.get(name, 0) >= _CIRCUIT_BREAKER_THRESHOLD:
            _log.error(
                "Circuit breaker open for %s — %d failures. Manual restart required.",
                name, self._failures[name],
            )
            return

        # GAP 1: refuse to spawn if the service's port is already bound
        port = cfg.get("port")
        if port and _port_in_use(port):
            _log.warning(
                "Skipping spawn of %s — port %d already in use (prior instance still running?)",
                name, port,
            )
            return

        env = {**os.environ, **cfg.get("env", {})}
        log_fh = open(_LOG_FILE, "a")
        try:
            proc = subprocess.Popen(
                cfg["cmd"],
                cwd=cfg.get("cwd"),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout for unified logging
            )
            self._procs[name] = proc
            with _LOG_LOCK:
                _log.info("Spawned %s PID %d", name, proc.pid)
        except Exception as exc:
            _log.error("Failed to spawn %s: %s", name, exc)
            self._failures[name] = self._failures.get(name, 0) + 1

    def _watch_loop(self) -> None:
        while self._running:
            time.sleep(5)
            now = time.time()
            for name, cfg in _SERVICES.items():
                if not self._running:
                    break
                proc = self._procs.get(name)
                if proc is None or proc.poll() is not None:
                    rc = proc.returncode if proc is not None else None

                    # If proc was never spawned because the port is externally occupied,
                    # the service is running fine — don't count it as a failure.
                    port = cfg.get("port")
                    if proc is None and port and _port_in_use(port):
                        self._failures[name] = 0
                        continue

                    # GAP 2: respect restart_policy — don't respawn clean exits
                    policy = cfg.get("restart_policy", "always")
                    if policy == "on_failure" and rc == 0:
                        self._failures[name] = 0
                        with _LOG_LOCK:
                            _log.info("%s exited cleanly (rc=0) — not respawning (restart_policy=on_failure)", name)
                        continue

                    self._failures[name] = self._failures.get(name, 0) + 1
                    count = self._failures[name]
                    # GAP 7: log the actual exit code so we know WHY it died
                    with _LOG_LOCK:
                        _log.warning("%s exited (rc=%s, failure #%d)", name, rc, count)

                    # GAP 1: backoff — skip if we're not due for a retry yet
                    if now < self._next_retry_at.get(name, 0.0):
                        continue

                    if count <= _MAX_SILENT_RESTARTS:
                        self._spawn(name, cfg)
                    elif name not in self._alerted and self._on_alert:
                        self._alerted.add(name)
                        self._on_alert(name, count)

                    # GAP 1: set next retry time with exponential backoff
                    delay = min(_BACKOFF_BASE_SECS * (2 ** (count - 1)), _BACKOFF_MAX_SECS)
                    self._next_retry_at[name] = now + delay
                    if count > 1:
                        with _LOG_LOCK:
                            _log.info("%s backoff: next retry in %.0fs (failure #%d)", name, delay, count)
