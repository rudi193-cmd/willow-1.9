"""Shared test fixtures — isolated test database, fresh schema each session."""
import os
import sys
from pathlib import Path
import pytest

REPO_ROOT = str(Path(__file__).parent.parent)
sys.path = [REPO_ROOT] + [p for p in sys.path if "willow-1.7" not in p]

os.environ["WILLOW_PG_DB"] = "willow_19_test"

_PG_USER = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", ""))
_PG_HOST = os.environ.get("WILLOW_PG_HOST")
_PG_PORT = os.environ.get("WILLOW_PG_PORT")


def _ensure_test_db():
    """Create willow_19_test if it doesn't exist."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            dbname="postgres",
            user=_PG_USER,
            host=_PG_HOST,
            port=_PG_PORT,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = 'willow_19_test'")
            if not cur.fetchone():
                cur.execute("CREATE DATABASE willow_19_test")
        conn.close()
    except Exception as e:
        print(f"  test db bootstrap warning: {e}")


@pytest.fixture(scope="session", autouse=True)
def init_pg_schema():
    """Bootstrap test database and initialize schema once per session."""
    _ensure_test_db()
    try:
        import importlib
        import core.pg_bridge as pgb
        importlib.reload(pgb)
        pgb.PgBridge()
    except Exception as e:
        print(f"  pg schema init warning: {e}")
