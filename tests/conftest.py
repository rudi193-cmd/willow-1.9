"""Shared test fixtures — initialize Postgres schema before any test runs."""
import os
import sys
from pathlib import Path
import pytest

# Ensure willow-1.9 is first on the path — must come before any willow-1.7 paths
REPO_ROOT = str(Path(__file__).parent.parent)
sys.path = [REPO_ROOT] + [p for p in sys.path if "willow-1.7" not in p]

os.environ.setdefault("WILLOW_PG_DB", "willow_19")


@pytest.fixture(scope="session", autouse=True)
def init_pg_schema():
    """Initialize Postgres schema once per test session."""
    try:
        import importlib
        import core.pg_bridge as pgb
        importlib.reload(pgb)
        pgb.PgBridge()
    except Exception as e:
        print(f"  pg schema init warning: {e}")
