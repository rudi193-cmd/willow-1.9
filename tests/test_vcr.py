"""Tests for tests/vcr.py — VCR fixture helper.

Covers:
  - dehydrate(): home dir, UUID, timestamp normalization
  - with_fixture(): hit, miss+record, miss+CI, miss+local
  - with_vcr() decorator: sync and async, fixture_name default
  - kb_ingest / kb_search integration stubs
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from vcr import dehydrate, with_fixture, with_vcr, _fixture_path, _FIXTURES_ROOT


# ── dehydrate ─────────────────────────────────────────────────────────────────

class TestDehydrate:
    def test_replaces_home_dir(self):
        home = str(Path.home())
        result = dehydrate(f"path is {home}/willow")
        assert "[HOME]" in result
        assert home not in result

    def test_replaces_uuid(self):
        s = "atom id is 3f6a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c"
        result = dehydrate(s)
        assert "[UUID]" in result
        assert "3f6a1b2c" not in result

    def test_replaces_timestamp(self):
        s = "created at 2026-05-18T11:08:18.448445-06:00"
        result = dehydrate(s)
        assert "[TIMESTAMP]" in result
        assert "2026-05-18" not in result

    def test_replaces_utc_timestamp(self):
        result = dehydrate("ts=2025-01-01T00:00:00Z")
        assert "[TIMESTAMP]" in result

    def test_non_string_passthrough(self):
        assert dehydrate(42) == 42
        assert dehydrate(True) is True
        assert dehydrate(None) is None

    def test_nested_dict(self):
        home = str(Path.home())
        d = {"path": f"{home}/foo", "count": 3}
        result = dehydrate(d)
        assert result["path"] == "[HOME]/foo"
        assert result["count"] == 3

    def test_list(self):
        home = str(Path.home())
        result = dehydrate([f"{home}/a", "plain"])
        assert result[0] == "[HOME]/a"
        assert result[1] == "plain"

    def test_already_clean_string_unchanged(self):
        s = "no paths or ids here"
        assert dehydrate(s) == s


# ── with_fixture ──────────────────────────────────────────────────────────────

class TestWithFixture:
    def test_calls_fn_when_vcr_inactive(self, tmp_path):
        """When not in a test env (VCR inactive), fn is called directly."""
        called = []
        def fn():
            called.append(1)
            return {"status": "ok"}

        with patch.dict(os.environ, {}, clear=True):
            # Manually clear PYTEST_CURRENT_TEST so VCR is off
            env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
            with patch.dict(os.environ, env, clear=True):
                result = with_fixture({"q": "test"}, "t", fn)

        assert result == {"status": "ok"}
        assert called

    def test_reads_from_existing_fixture(self, tmp_path):
        """A cached fixture is returned without calling fn."""
        fixture_data = {"output": {"status": "cached"}}
        path = _fixture_path("test_read", {"q": "hello"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fixture_data))

        try:
            called = []
            def fn():
                called.append(1)
                return {"status": "live"}

            result = with_fixture({"q": "hello"}, "test_read", fn)
            assert result == {"status": "cached"}
            assert not called
        finally:
            path.unlink(missing_ok=True)

    def test_writes_fixture_with_vcr_record(self, tmp_path):
        """VCR_RECORD=1 causes a new fixture to be written."""
        input_data = {"title": "record test", "uid": "no-uuid-here"}
        path = _fixture_path("test_record", input_data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)

        try:
            with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                result = with_fixture(input_data, "test_record", lambda: {"id": "ABC123"})

            assert result == {"id": "ABC123"}
            assert path.exists()
            saved = json.loads(path.read_text())
            assert saved["output"] == {"id": "ABC123"}
            assert "input" in saved
        finally:
            path.unlink(missing_ok=True)

    def test_raises_in_ci_when_fixture_missing(self):
        """CI=1 without VCR_RECORD raises FileNotFoundError on missing fixture."""
        input_data = {"q": "ci-missing-fixture-xyz-unique-99182736"}
        path = _fixture_path("ci_test", input_data)
        path.unlink(missing_ok=True)

        with patch.dict(os.environ, {"CI": "1", "VCR_RECORD": ""}):
            with pytest.raises(FileNotFoundError, match="VCR fixture missing"):
                with_fixture(input_data, "ci_test", lambda: {})

    def test_no_write_without_vcr_record(self):
        """Without VCR_RECORD, missing fixture just calls fn — no file written."""
        input_data = {"q": "no-record-test-unique-66554433"}
        path = _fixture_path("no_record", input_data)
        path.unlink(missing_ok=True)

        with patch.dict(os.environ, {"VCR_RECORD": ""}):
            result = with_fixture(input_data, "no_record", lambda: {"live": True})

        assert result == {"live": True}
        assert not path.exists()


# ── with_vcr decorator ────────────────────────────────────────────────────────

class TestWithVcrDecorator:
    def test_sync_decorator_records_and_replays(self):
        """@with_vcr on a sync function records then replays from fixture."""
        call_count = [0]

        @with_vcr("vcr_sync_test")
        def fetch(query: str, limit: int = 5):
            call_count[0] += 1
            return {"results": [query], "count": 1}

        input_data = {"query": "vcr-decorator-unique-sync-7781", "limit": 5}
        path = _fixture_path("vcr_sync_test", input_data)
        path.unlink(missing_ok=True)

        try:
            with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                r1 = fetch("vcr-decorator-unique-sync-7781", limit=5)
            assert r1 == {"results": ["vcr-decorator-unique-sync-7781"], "count": 1}
            assert call_count[0] == 1
            assert path.exists()

            r2 = fetch("vcr-decorator-unique-sync-7781", limit=5)
            assert r2 == r1
            assert call_count[0] == 1  # not called again
        finally:
            path.unlink(missing_ok=True)

    def test_async_decorator_records_and_replays(self):
        """@with_vcr on an async function records then replays from fixture."""
        call_count = [0]

        @with_vcr("vcr_async_test")
        async def async_fetch(query: str, limit: int = 5):
            call_count[0] += 1
            return {"results": [query], "async": True}

        input_data = {"query": "vcr-decorator-unique-async-5542", "limit": 5}
        path = _fixture_path("vcr_async_test", input_data)
        path.unlink(missing_ok=True)

        async def run():
            try:
                with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                    r1 = await async_fetch("vcr-decorator-unique-async-5542", limit=5)
                assert r1 == {"results": ["vcr-decorator-unique-async-5542"], "async": True}
                assert call_count[0] == 1
                assert path.exists()

                r2 = await async_fetch("vcr-decorator-unique-async-5542", limit=5)
                assert r2 == r1
                assert call_count[0] == 1
            finally:
                path.unlink(missing_ok=True)

        asyncio.run(run())

    def test_default_fixture_name_uses_function_name(self):
        """@with_vcr() without a name uses fn.__name__."""
        @with_vcr()
        def my_special_function(x: int):
            return x * 2

        input_data = {"x": 99}
        path = _fixture_path("my_special_function", input_data)
        path.unlink(missing_ok=True)

        try:
            with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                result = my_special_function(99)
            assert result == 198
            assert path.exists()
        finally:
            path.unlink(missing_ok=True)

    def test_different_inputs_produce_different_fixtures(self):
        """Two different queries hash to different fixture files."""
        @with_vcr("vcr_hash_test")
        def search(query: str):
            return {"q": query}

        path_a = _fixture_path("vcr_hash_test", {"query": "apple"})
        path_b = _fixture_path("vcr_hash_test", {"query": "banana"})
        path_a.unlink(missing_ok=True)
        path_b.unlink(missing_ok=True)

        try:
            with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                search("apple")
                search("banana")
            assert path_a.exists()
            assert path_b.exists()
            assert path_a != path_b
        finally:
            path_a.unlink(missing_ok=True)
            path_b.unlink(missing_ok=True)


# ── kb_ingest / kb_search integration stubs ──────────────────────────────────

class TestKbVcrIntegration:
    """Verify the @with_vcr pattern works for the real kb_ingest / kb_search
    call signatures (minus live Postgres)."""

    def test_kb_ingest_stub(self):
        """@with_vcr wraps a kb_ingest-shaped function correctly."""
        @with_vcr("kb_ingest")
        def kb_ingest(
            app_id: str,
            title: str,
            summary: str,
            source_type: str = "mcp",
            source_id: str = "",
            category: str = "general",
            domain: str = "",
            force: bool = False,
        ):
            return {"id": "FAKEID01", "status": "ingested"}

        path = _fixture_path("kb_ingest", {
            "app_id": "willow", "title": "VCR test atom",
            "summary": "testing vcr fixture", "source_type": "mcp",
            "source_id": "", "category": "general", "domain": "", "force": False,
        })
        path.unlink(missing_ok=True)

        try:
            with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                result = kb_ingest("willow", "VCR test atom", "testing vcr fixture")
            assert result["status"] == "ingested"
            assert path.exists()

            result2 = kb_ingest("willow", "VCR test atom", "testing vcr fixture")
            assert result2 == result
        finally:
            path.unlink(missing_ok=True)

    def test_kb_search_stub(self):
        """@with_vcr wraps a kb_search-shaped function correctly."""
        @with_vcr("kb_search")
        def kb_search(
            app_id: str,
            query: str,
            limit: int = 20,
            semantic: bool = False,
            include_embedding: bool = False,
            fields: list = None,
        ):
            return {"knowledge": [{"id": "A1", "title": "result"}], "total": 1, "mode": "keyword"}

        path = _fixture_path("kb_search", {
            "app_id": "willow", "query": "vcr test query",
            "limit": 20, "semantic": False, "include_embedding": False, "fields": None,
        })
        path.unlink(missing_ok=True)

        try:
            with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                result = kb_search("willow", "vcr test query")
            assert result["total"] == 1
            assert path.exists()

            result2 = kb_search("willow", "vcr test query")
            assert result2 == result
        finally:
            path.unlink(missing_ok=True)

    def test_fixture_is_dehydrated_on_disk(self):
        """Saved fixture replaces home dir in input so it's portable."""
        home = str(Path.home())

        @with_vcr("kb_ingest_dehydrate")
        def kb_ingest(app_id: str, title: str, summary: str):
            return {"id": "X1"}

        summary_with_home = f"found at {home}/willow/foo.py"
        path = _fixture_path("kb_ingest_dehydrate", {
            "app_id": "willow", "title": "dehydrate test", "summary": summary_with_home,
        })
        path.unlink(missing_ok=True)

        try:
            with patch.dict(os.environ, {"VCR_RECORD": "1"}):
                kb_ingest("willow", "dehydrate test", summary_with_home)

            saved = json.loads(path.read_text())
            assert home not in json.dumps(saved["input"])
            assert "[HOME]" in json.dumps(saved["input"])
        finally:
            path.unlink(missing_ok=True)
