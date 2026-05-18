"""
kart_worker.py — Kart task queue consumer for willow-dashboard
b17: KRTDSH  ΔΣ=42

Ported from willow-1.7/kart_worker.py. Runs as a daemon thread inside
the dashboard process — no separate SAP gate check needed since the dashboard
is already an authorized context.

Polls public.tasks every 5s, claims and executes pending tasks via bwrap sandbox.
"""
import json
import logging
import os
import re
import resource as _resource
import shutil as _shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("kart_worker")

_BWRAP: str | None = _shutil.which("bwrap")

_ALLOW_NET_DIRECTIVE = "# allow_net"

_SHELL_STARTERS = (
    'cp ', 'rsync ', 'python3 ', 'python ',
    'mkdir ', 'chmod ', 'find ', 'grep ', 'curl ', 'echo ',
    'mv ', 'rm ', 'ls ', 'cat ', 'git ', 'bash ',
    'ollama ', 'jupyter ', 'kaggle ',
    str(Path.home()) + os.sep,
    '/usr/', '/opt/',
)


def _task_allows_network(task_text: str) -> bool:
    return any(line.strip() == _ALLOW_NET_DIRECTIVE for line in task_text.splitlines())


def _bwrap_prefix(allow_net: bool = False) -> list[str]:
    home = os.path.expanduser("~")
    sandbox_tmp = os.path.join(home, ".willow", "tmp")
    os.makedirs(sandbox_tmp, exist_ok=True)
    args = [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/etc", "/etc",
        "--dev", "/dev",
        "--proc", "/proc",
        "--bind", sandbox_tmp, "/tmp",
        "--unshare-pid",
        "--die-with-parent",
        "--bind", str(Path(__file__).parent.parent), str(Path(__file__).parent.parent),
    ]
    if not allow_net:
        args.insert(1, "--unshare-net")
    else:
        ssh_dir = os.path.join(home, ".ssh")
        if os.path.exists(ssh_dir):
            args += ["--ro-bind", ssh_dir, ssh_dir]
        netrc = os.path.join(home, ".netrc")
        if os.path.exists(netrc):
            args += ["--ro-bind", netrc, netrc]
    willow_store = os.path.join(home, ".willow")
    if os.path.exists(willow_store):
        args += ["--bind", willow_store, willow_store]
    pg_socket_dir = "/var/run/postgresql"
    if os.path.exists(pg_socket_dir):
        args += ["--bind", pg_socket_dir, pg_socket_dir]
    for path in ("/bin", "/lib", "/lib64", "/lib32", "/sbin"):
        if os.path.exists(path):
            args += ["--ro-bind", path, path]
    agents_dir = os.path.join(home, "agents")
    if os.path.exists(agents_dir):
        args += ["--bind", agents_dir, agents_dir]
    ashokoa = os.path.join(home, "Ashokoa")
    if os.path.exists(ashokoa):
        args += ["--ro-bind", ashokoa, ashokoa]
    desktop = os.path.join(home, "Desktop")
    if os.path.exists(desktop):
        args += ["--ro-bind", desktop, desktop]
    github_dir = os.path.join(home, "github")
    if os.path.exists(github_dir):
        args += ["--ro-bind", github_dir, github_dir]
    local_dir = os.path.join(home, ".local")
    if os.path.exists(local_dir):
        args += ["--ro-bind", local_dir, local_dir]
    kaggle_dir = os.path.join(home, ".kaggle")
    if os.path.exists(kaggle_dir):
        args += ["--ro-bind", kaggle_dir, kaggle_dir]
    if os.path.exists("/media/willow"):
        args += ["--bind", "/media/willow", "/media/willow"]
    willow_venv = os.path.join(home, ".willow-venv")
    if os.path.exists(willow_venv):
        args += ["--ro-bind", willow_venv, willow_venv]
    repo_venv = str(Path(__file__).parent / ".venv-dev")
    if os.path.exists(repo_venv) and repo_venv != willow_venv:
        args += ["--ro-bind", repo_venv, repo_venv]
    try:
        import psycopg2 as _pg2
        pg2_dir = os.path.dirname(_pg2.__file__)
        if os.path.exists(pg2_dir):
            args += ["--ro-bind", pg2_dir, pg2_dir]
        libs_dir = os.path.join(os.path.dirname(pg2_dir), "psycopg2_binary.libs")
        if os.path.exists(libs_dir):
            args += ["--ro-bind", libs_dir, libs_dir]
    except ImportError:
        pass
    import sysconfig
    user_site = sysconfig.get_path("purelib")
    if user_site and os.path.exists(user_site):
        args += ["--ro-bind", user_site, user_site]
    return args


def _resource_limits():
    _resource.setrlimit(_resource.RLIMIT_CPU, (1800, 1800))
    _resource.setrlimit(_resource.RLIMIT_AS,  (8 * 1024 ** 3, 8 * 1024 ** 3))
    _resource.setrlimit(_resource.RLIMIT_NOFILE, (1024, 1024))


def _spawn(cmd_type: str, cmd: str, env: dict, allow_net: bool = False) -> subprocess.Popen:
    prefix = _bwrap_prefix(allow_net=allow_net)
    if cmd_type == "python":
        proc = subprocess.Popen(
            prefix + ["python3", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, preexec_fn=_resource_limits,
        )
        proc.stdin.write(cmd)
        proc.stdin.close()
    elif cmd_type == "script":
        proc = subprocess.Popen(
            prefix + ["bash", "-s"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, preexec_fn=_resource_limits,
        )
        proc.stdin.write(cmd)
        proc.stdin.close()
    else:
        proc = subprocess.Popen(
            prefix + ["bash", "-c", cmd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, preexec_fn=_resource_limits,
        )
    return proc


_SHELL_METACHAR_RE = re.compile(r'[;&|$()\\`><]')


def _validate_shell_cmd(cmd: str) -> bool:
    if _SHELL_METACHAR_RE.search(cmd):
        return False
    cmd_lower = cmd.strip().lower()
    return any(cmd_lower.startswith(s) for s in _SHELL_STARTERS)


def execute_task(task_text: str) -> dict:
    outputs = []
    step = 0
    errors = []
    commands = []

    for lang, block in re.findall(r'```(bash|sh|python3?|python)?\n?(.*?)```', task_text, re.DOTALL):
        block = block.strip()
        if not block:
            continue
        is_python = lang in ("python", "python3")
        real_lines = [l for l in block.splitlines() if l.strip() and not l.strip().startswith('#')]
        if is_python:
            commands.append(('python', block))
        elif len(real_lines) == 1:
            commands.append(('shell', real_lines[0]))
        else:
            commands.append(('script', block))

    if not commands:
        for m in re.finditer(r'\(\d+\)\s+(.+?)(?=\s*\(\d+\)|$)', task_text, re.DOTALL):
            fragment = m.group(1).strip().rstrip('.')
            lower = fragment.lower()
            for starter in _SHELL_STARTERS:
                idx = lower.find(starter)
                if idx != -1:
                    cmd = fragment[idx:].split('. ')[0].strip()
                    if cmd not in [c[1] for c in commands]:
                        commands.append(('shell', cmd))
                    break

        for m in re.finditer(
            r'^\s*((?:cp|rsync|python3?|mkdir|chmod|find|grep|curl|mv|rm|git|ollama)\s+.+)$',
            task_text, re.MULTILINE
        ):
            cmd = m.group(1).strip()
            if cmd not in [c[1] for c in commands]:
                commands.append(('shell', cmd))

        if not commands:
            for starter in _SHELL_STARTERS:
                pos = 0
                lower = task_text.lower()
                while True:
                    idx = lower.find(starter, pos)
                    if idx == -1:
                        break
                    end = task_text.find('. ', idx)
                    cmd = task_text[idx:end if end != -1 else len(task_text)].strip().rstrip('.')
                    if cmd and cmd not in [c[1] for c in commands]:
                        commands.append(('shell', cmd))
                    pos = idx + len(starter)

    if not commands:
        return {"success": False, "error": "no executable commands found", "steps": 0}

    if not _BWRAP:
        return {"success": False, "error": "bwrap not found — install bubblewrap", "steps": 0}

    allow_net = _task_allows_network(task_text)

    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.path.expanduser("~"),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "PYTHONUNBUFFERED": "1",
    }
    for k, v in os.environ.items():
        if k.startswith(("WILLOW_", "POSTGRES", "PG", "OLLAMA_", "GIT_", "TWINE_", "PYPI_")):
            env[k] = v
    _repo_venv_bin = str(Path(__file__).parent / ".venv-dev" / "bin")
    _home_venv_bin = os.path.join(os.path.expanduser("~"), ".willow-venv", "bin")
    venv_bin = _repo_venv_bin if os.path.exists(_repo_venv_bin) else _home_venv_bin
    if os.path.exists(venv_bin) and venv_bin not in env["PATH"]:
        env["PATH"] = venv_bin + ":" + env["PATH"]
    if "GIT_AUTHOR_NAME" not in env:
        try:
            name = subprocess.check_output(["git", "config", "--global", "user.name"], text=True).strip()
            email = subprocess.check_output(["git", "config", "--global", "user.email"], text=True).strip()
            if name:
                env["GIT_AUTHOR_NAME"] = name
                env["GIT_COMMITTER_NAME"] = name
            if email:
                env["GIT_AUTHOR_EMAIL"] = email
                env["GIT_COMMITTER_EMAIL"] = email
        except Exception:
            pass

    for cmd_type, cmd in commands:
        step += 1
        label = cmd.splitlines()[0][:80] if cmd_type == 'script' else cmd
        try:
            if cmd_type not in ('script', 'python') and not _validate_shell_cmd(cmd):
                outputs.append(f"[kart] BLOCKED: {cmd[:80]}")
                errors.append(f"blocked: {cmd[:80]}")
                continue

            proc = _spawn(cmd_type, cmd, env, allow_net=allow_net)

            stdout_lines = []
            stderr_lines = []

            def _read_stderr(p, buf):
                for line in p.stderr:
                    buf.append(line.rstrip())

            t = threading.Thread(target=_read_stderr, args=(proc, stderr_lines), daemon=True)
            t.start()

            deadline = time.monotonic() + 1800
            for line in proc.stdout:
                line = line.rstrip()
                stdout_lines.append(line)
                if time.monotonic() > deadline:
                    proc.kill()
                    errors.append(f"{label} → timeout")
                    break

            proc.wait()
            t.join(timeout=5)

            output = "\n".join(stdout_lines).strip()
            err = "\n".join(stderr_lines).strip()
            outputs.append(f"$ {label}\n{output}" + (f"\nSTDERR: {err}" if err else ""))
            if proc.returncode not in (0, -9):
                errors.append(f"{label} → exit {proc.returncode}: {err}")
        except Exception as e:
            errors.append(f"{label} → {e}")

    if errors:
        return {"success": False, "error": "; ".join(errors), "output": "\n\n".join(outputs), "steps": step}
    return {"success": True, "response": "\n\n".join(outputs), "steps": step, "provider": "shell"}


def _pg_connect():
    # Intentional dedicated connection — holds across claim+complete atomic pairs; reconnects on error.
    import psycopg2
    dsn = os.environ.get("WILLOW_DB_URL", "")
    if dsn:
        return psycopg2.connect(dsn)
    return psycopg2.connect(
        dbname=os.environ.get("WILLOW_PG_DB", "willow_19"),
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
    )


def _claim_task(conn) -> dict | None:
    cur = conn.cursor()
    cur.execute("""
        UPDATE public.tasks
        SET status = 'running', updated_at = NOW()
        WHERE id = (
            SELECT id FROM public.tasks
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, task, submitted_by
    """)
    row = cur.fetchone()
    conn.commit()
    cur.close()
    if not row:
        return None
    return {"task_id": row[0], "task": row[1], "submitted_by": row[2]}


def _complete_task(conn, task_id: str, result: dict, steps: int = 0) -> None:
    cur = conn.cursor()
    cur.execute("""
        UPDATE public.tasks
        SET status = 'complete', result = %s, updated_at = NOW()
        WHERE id = %s
    """, (json.dumps(result), task_id))
    conn.commit()
    cur.close()


def _willow_repo_root() -> Path | None:
    """Resolve willow-1.9 checkout for Run Ledger imports (never rely on sibling-path guesses alone)."""
    env = (os.environ.get("WILLOW_ROOT") or "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser().resolve())
    candidates.append((Path.home() / "github" / "willow-1.9").resolve())
    for base in candidates:
        try:
            if (base / "core" / "run_ledger.py").is_file():
                return base
        except OSError:
            continue
    return None


def _ensure_willow_on_path() -> Path | None:
    root = _willow_repo_root()
    if root is None:
        return None
    key = str(root)
    if key not in sys.path:
        sys.path.insert(0, key)
    return root


def _fail_task(conn, task_id: str, error: str) -> None:
    cur = conn.cursor()
    cur.execute("""
        UPDATE public.tasks
        SET status = 'failed', result = %s, updated_at = NOW()
        WHERE id = %s
    """, (json.dumps({"error": error}), task_id))
    conn.commit()
    cur.close()


# Kart child run IDs — keyed by task_id. Never written to the shared /tmp run file
# so kart tasks cannot clobber the parent session's current_run_id pointer.
_KART_RUN_IDS: dict[str, str] = {}


def _kart_run_open(task_id: str, task_text: str, submitted_by: str) -> None:
    """Open a child Run Ledger record for this Kart task. Best-effort.

    Uses write_tmp=False so the parent session's /tmp/willow-run-{AGENT}.json
    is never overwritten by a Kart child run.
    """
    if _ensure_willow_on_path() is None:
        logger.debug("run_ledger open skipped: WILLOW_ROOT not found")
        return
    try:
        from core.run_ledger import open_run, current_run_id

        parent = current_run_id()
        run_id = open_run(
            purpose=f"kart:{task_id[:8]} {task_text[:60]}",
            parent_run_id=parent,
            write_tmp=False,
        )
        if run_id:
            _KART_RUN_IDS[task_id] = run_id
    except Exception as e:
        logger.debug("run_ledger open skipped: %s", e)


def _kart_run_close(task_id: str, status: str) -> None:
    """Close the child run opened for this Kart task. Best-effort.

    Closes directly via DB using the stored run_id — never calls close_run()
    which would clear the parent session's tmp file.
    """
    run_id = _KART_RUN_IDS.pop(task_id, None)
    if not run_id or _ensure_willow_on_path() is None:
        return
    try:
        from core.run_ledger import _connect
        conn = _connect()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "UPDATE willow.runs SET status=%s, ended_at=now() WHERE id=%s AND status='running'",
            (status, run_id),
        )
        conn.close()
    except Exception as e:
        logger.debug("run_ledger close skipped: %s", e)


def kart_loop(interval: int = 5) -> None:
    """Daemon loop — claim and execute one task at a time, poll every interval seconds."""
    logger.info("kart daemon started (dashboard-integrated, poll=%ds)", interval)
    conn = None
    while True:
        try:
            if conn is None:
                conn = _pg_connect()
            task = _claim_task(conn)
            if not task:
                time.sleep(interval)
                continue
            task_id = task["task_id"]
            task_text = task["task"]
            logger.info("kart claimed %s (by %s): %s", task_id, task.get("submitted_by", "?"), task_text[:60])
            _kart_run_open(task_id, task_text, task.get("submitted_by", ""))
            result = execute_task(task_text)
            if result.get("success"):
                _complete_task(conn, task_id, result, steps=result.get("steps", 0))
                _kart_run_close(task_id, "completed")
                logger.info("kart complete %s (%d steps)", task_id, result.get("steps", 0))
            else:
                _fail_task(conn, task_id, result.get("error", "unknown"))
                _kart_run_close(task_id, "crashed")
                logger.warning("kart failed %s: %s", task_id, result.get("error", "?"))
        except Exception as e:
            logger.error("kart loop error: %s", e)
            try:
                conn.close()
            except Exception:
                pass
            conn = None
            time.sleep(interval)
