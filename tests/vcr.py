"""VCR fixture helper — deterministic cache for kb_ingest and kb_search in tests.

Ported from services/vcr.ts (Claude Code source). Fixtures are keyed by a
SHA1 of the dehydrated input so the same logical call always hits the same
file, regardless of home directory, UUIDs, or timestamps.

Fixture file: tests/fixtures/<func_name>-<sha1[:12]>.json
  { "input": <dehydrated>, "output": <result> }

Control env vars:
  VCR_RECORD=1  — write new fixtures when missing (local dev / record run)
  CI            — raise FileNotFoundError when fixture is missing (default CI gate)

Pytest sets PYTEST_CURRENT_TEST automatically, so VCR activates inside any
pytest session without extra configuration.
"""
import asyncio
import functools
import hashlib
import inspect
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

_FIXTURES_ROOT = Path(__file__).parent / "fixtures"
_HOME = str(Path.home())
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)


def _should_use_vcr() -> bool:
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("VCR") == "1"
    )


def dehydrate(value: Any) -> Any:
    """Replace env-specific strings with stable placeholders.

    Mirrors dehydrateValue() from services/vcr.ts — home dir, UUIDs, and
    timestamps are the main sources of fixture hash churn.
    """
    if isinstance(value, str):
        s = value.replace(_HOME, "[HOME]")
        s = _UUID_RE.sub("[UUID]", s)
        s = _TS_RE.sub("[TIMESTAMP]", s)
        return s
    if isinstance(value, dict):
        return {k: dehydrate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [dehydrate(item) for item in value]
    return value


def _sha1_12(data: Any) -> str:
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha1(serialized.encode()).hexdigest()[:12]


def _fixture_path(fixture_name: str, input_data: Any) -> Path:
    h = _sha1_12(dehydrate(input_data))
    return _FIXTURES_ROOT / f"{fixture_name}-{h}.json"


def with_fixture(input_data: Any, fixture_name: str, fn: Callable) -> Any:
    """Generic fixture helper — sync version of withFixture() from vcr.ts.

    If VCR is active:
      - Hit:  return cached output.
      - Miss + VCR_RECORD=1:  call fn(), save fixture, return result.
      - Miss + CI:  raise FileNotFoundError (commit the fixture first).
      - Miss + local:  call fn() and return result without saving.
    If VCR is inactive, fn() is called directly.
    """
    if not _should_use_vcr():
        return fn()

    path = _fixture_path(fixture_name, input_data)
    if path.exists():
        cached = json.loads(path.read_text())
        return cached["output"]

    if os.environ.get("CI") and not os.environ.get("VCR_RECORD"):
        raise FileNotFoundError(
            f"VCR fixture missing: {path}. "
            "Re-run locally with VCR_RECORD=1, then commit the fixture."
        )

    result = fn()

    if os.environ.get("VCR_RECORD"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"input": dehydrate(input_data), "output": result}, indent=2, default=str)
        )

    return result


async def _with_fixture_async(input_data: Any, fixture_name: str, fn: Callable) -> Any:
    """Async variant of with_fixture for coroutine callables."""
    if not _should_use_vcr():
        return await fn()

    path = _fixture_path(fixture_name, input_data)
    if path.exists():
        cached = json.loads(path.read_text())
        return cached["output"]

    if os.environ.get("CI") and not os.environ.get("VCR_RECORD"):
        raise FileNotFoundError(
            f"VCR fixture missing: {path}. "
            "Re-run locally with VCR_RECORD=1, then commit the fixture."
        )

    result = await fn()

    if os.environ.get("VCR_RECORD"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"input": dehydrate(input_data), "output": result}, indent=2, default=str)
        )

    return result


def with_vcr(fixture_name: str = ""):
    """Decorator: cache function I/O in a SHA1-keyed fixture file.

    Works for both sync and async functions. The fixture name defaults to
    the wrapped function's __name__.

    Usage:
        @with_vcr("kb_ingest")
        def ingest(title, summary, **kwargs):
            return pg.ingest_atom(title=title, summary=summary, **kwargs)

        @with_vcr()
        async def kb_search_live(query, limit=20):
            return await pg.knowledge_search(query, limit=limit)
    """
    def decorator(fn: Callable) -> Callable:
        name = fixture_name or fn.__name__

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                sig = inspect.signature(fn)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                input_data = dict(bound.arguments)
                return await _with_fixture_async(input_data, name, lambda: fn(*args, **kwargs))
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            sig = inspect.signature(fn)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            input_data = dict(bound.arguments)
            return with_fixture(input_data, name, lambda: fn(*args, **kwargs))

        return sync_wrapper
    return decorator
