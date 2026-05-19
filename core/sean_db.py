# core/sean_db.py — GPG-encrypted personal SQLite database. b20: SEANDB1  ΔΣ=42
"""
Stores personal/PII atoms for Sean. File at rest is ~/SAFE/sean.db.gpg.
Open decrypts to /dev/shm (RAM only), close re-encrypts and wipes temp.
Encryption requires only the public key. Decryption requires private key
with passphrase cached in gpg-agent.
"""
import os
import sqlite3
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

_SAFE_DIR = Path.home() / "SAFE"
_GPG_FILE = _SAFE_DIR / "sean.db.gpg"
_PLAIN_LEGACY = _SAFE_DIR / "sean.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS atoms (
    atom_id         INTEGER PRIMARY KEY,
    kind            TEXT,
    title           TEXT,
    category        TEXT,
    summary         TEXT,
    signal_strength INTEGER,
    layer           TEXT DEFAULT 'named',
    proposed_by     TEXT DEFAULT 'claude',
    proposed_at     TEXT,
    ratified_by     TEXT,
    ratified_at     TEXT
);
CREATE TABLE IF NOT EXISTS edges (
    edge_id   INTEGER PRIMARY KEY,
    from_atom INTEGER NOT NULL,
    to_atom   INTEGER NOT NULL,
    relation  TEXT NOT NULL
);
"""


def _recipient() -> str:
    return os.environ.get("WILLOW_PGP_FINGERPRINT", "rudi193@gmail.com")


def _gpg_decrypt(src: Path, dst: Path) -> None:
    """Decrypt src → dst using gpg-agent cached passphrase."""
    result = subprocess.run(
        ["gpg", "--quiet", "--batch", "--yes",
         "--decrypt", "--output", str(dst), str(src)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"GPG decrypt failed (is gpg-agent running?): "
            f"{result.stderr.decode(errors='replace').strip()}"
        )


def _gpg_encrypt(src: Path, dst: Path) -> None:
    """Encrypt src → dst with Sean's public key (no passphrase needed)."""
    result = subprocess.run(
        ["gpg", "--quiet", "--batch", "--yes",
         "--encrypt", "--recipient", _recipient(),
         "--output", str(dst), str(src)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"GPG encrypt failed: {result.stderr.decode(errors='replace').strip()}"
        )


def _wipe(path: Path) -> None:
    """Zero-fill then unlink."""
    try:
        size = path.stat().st_size
        if size > 0:
            path.write_bytes(b"\x00" * size)
    except Exception:
        pass
    path.unlink(missing_ok=True)


@contextmanager
def open_sean_db():
    """Context manager yielding a sqlite3 connection to the personal DB.

    Decrypts ~/SAFE/sean.db.gpg → /dev/shm on entry.
    Re-encrypts and wipes the plaintext temp file on exit.
    Raises RuntimeError if gpg-agent cannot decrypt (passphrase not cached).
    """
    _SAFE_DIR.mkdir(parents=True, exist_ok=True)

    # Use /dev/shm so the plaintext never touches disk
    shm = Path("/dev/shm") if Path("/dev/shm").exists() else Path(tempfile.gettempdir())
    fd, tmp_str = tempfile.mkstemp(prefix="sean-", suffix=".db", dir=str(shm))
    os.close(fd)
    tmp = Path(tmp_str)

    try:
        if _GPG_FILE.exists():
            _gpg_decrypt(_GPG_FILE, tmp)
        elif _PLAIN_LEGACY.exists():
            # One-time migration: copy plaintext into place and encrypt it below
            import shutil
            shutil.copy2(str(_PLAIN_LEGACY), str(tmp))
        # else: brand new DB — sqlite3.connect creates the file

        conn = sqlite3.connect(str(tmp))
        conn.executescript(_SCHEMA)
        conn.commit()

        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

        _gpg_encrypt(tmp, _GPG_FILE)

        # Remove legacy plaintext after first successful encrypt
        if _PLAIN_LEGACY.exists():
            _wipe(_PLAIN_LEGACY)

    finally:
        _wipe(tmp)


def atom_count() -> int:
    """Quick count without needing caller to manage context. Requires gpg-agent."""
    with open_sean_db() as conn:
        return conn.execute("SELECT count(*) FROM atoms").fetchone()[0]


if __name__ == "__main__":
    # python3 -m core.sean_db  — interactive read
    import json
    with open_sean_db() as conn:
        atoms = conn.execute(
            "SELECT atom_id, kind, title, category, summary FROM atoms ORDER BY atom_id"
        ).fetchall()
    print(f"atoms ({len(atoms)}):")
    for row in atoms:
        print(json.dumps(dict(zip(["id", "kind", "title", "category", "summary"], row)), ensure_ascii=False))
