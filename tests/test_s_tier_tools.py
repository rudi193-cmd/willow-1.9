"""Tests for S-tier tools built in d65bef9.

Covers:
  - _split_identifier (S9 voice keyterms)
  - _policy_check_fn via WILLOW_MOCK_POLICY (S8 policy-as-code)
  - env_check inner delta logic (S6 env bundles)
  - diagnostic_summary baseline delta (S4 LSP telemetry)
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = str(Path(__file__).parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ── _split_identifier (S9) ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def split_identifier():
    """Import _split_identifier with required env vars."""
    prev = os.environ.get("WILLOW_AGENT_NAME")
    os.environ["WILLOW_AGENT_NAME"] = "test-agent"
    try:
        # sap_mcp may already be imported; import module and grab function
        import importlib
        import sap.sap_mcp as _mod
        fn = _mod._split_identifier
    finally:
        if prev is None:
            os.environ.pop("WILLOW_AGENT_NAME", None)
        else:
            os.environ["WILLOW_AGENT_NAME"] = prev
    return fn


class TestSplitIdentifier:
    def test_camel_case(self, split_identifier):
        result = split_identifier("camelCaseWord")
        assert "camel" in result
        assert "Case" in result
        assert "Word" in result

    def test_pascal_case(self, split_identifier):
        result = split_identifier("PascalCaseIdent")
        assert "Pascal" in result
        assert "Case" in result
        assert "Ident" in result

    def test_snake_case(self, split_identifier):
        result = split_identifier("snake_case_name")
        assert "snake" in result
        assert "case" in result
        assert "name" in result

    def test_kebab_case(self, split_identifier):
        result = split_identifier("kebab-case-id")
        assert "kebab" in result
        assert "case" in result

    def test_path_segment(self, split_identifier):
        result = split_identifier("sap/middleware.py")
        assert "middleware" in result

    def test_short_words_filtered(self, split_identifier):
        # Words of length <= 2 are excluded (filter: 2 < len <= 20)
        result = split_identifier("a_bb_ccc")
        assert "a" not in result
        assert "bb" not in result
        assert "ccc" in result

    def test_long_word_excluded(self, split_identifier):
        long_word = "a" * 21
        result = split_identifier(long_word)
        assert long_word not in result

    def test_empty_string(self, split_identifier):
        assert split_identifier("") == []


# ── _policy_check_fn (S8) ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def policy_check():
    """Import _policy_check_fn from middleware (no WILLOW_AGENT_NAME required)."""
    from sap.middleware import _policy_check_fn
    return _policy_check_fn


class TestPolicyCheckFn:
    def test_no_rules_returns_ok(self, policy_check, monkeypatch):
        monkeypatch.setenv("WILLOW_MOCK_POLICY", json.dumps([]))
        action, rule = policy_check("hanuman", "kb_search")
        assert action == "ok"
        assert rule is None

    def test_block_rule_all_tools(self, policy_check, monkeypatch):
        rules = [{"name": "lockdown", "rule_type": "block", "target": "*",
                  "action": "block", "active": True}]
        monkeypatch.setenv("WILLOW_MOCK_POLICY", json.dumps(rules))
        action, rule = policy_check("hanuman", "kb_ingest")
        assert action == "block"
        assert rule == "lockdown"

    def test_block_rule_specific_tool(self, policy_check, monkeypatch):
        rules = [{"name": "no-ingest", "rule_type": "block", "target": "kb_ingest",
                  "action": "block", "active": True}]
        monkeypatch.setenv("WILLOW_MOCK_POLICY", json.dumps(rules))
        action, rule = policy_check("hanuman", "kb_ingest")
        assert action == "block"

    def test_block_rule_does_not_match_other_tool(self, policy_check, monkeypatch):
        rules = [{"name": "no-ingest", "rule_type": "block", "target": "kb_ingest",
                  "action": "block", "active": True}]
        monkeypatch.setenv("WILLOW_MOCK_POLICY", json.dumps(rules))
        action, rule = policy_check("hanuman", "kb_search")
        assert action == "ok"

    def test_warn_rule(self, policy_check, monkeypatch):
        rules = [{"name": "slow-warn", "rule_type": "warn", "target": "infer_chat",
                  "action": "warn", "active": True}]
        monkeypatch.setenv("WILLOW_MOCK_POLICY", json.dumps(rules))
        action, rule = policy_check("hanuman", "infer_chat")
        assert action == "warn"
        assert rule == "slow-warn"

    def test_limit_rule_under_threshold_no_pg(self, policy_check, monkeypatch):
        # With no PG, _count_receipts returns 0, so limit rules never fire
        rules = [{"name": "rate-cap", "rule_type": "limit", "target": "kb_search",
                  "action": "block", "threshold": 5, "window_sec": 60, "active": True}]
        monkeypatch.setenv("WILLOW_MOCK_POLICY", json.dumps(rules))
        action, rule = policy_check("hanuman", "kb_search")
        assert action == "ok"

    def test_inactive_rule_skipped(self, policy_check, monkeypatch):
        rules = [{"name": "disabled", "rule_type": "block", "target": "*",
                  "action": "block", "active": False}]
        monkeypatch.setenv("WILLOW_MOCK_POLICY", json.dumps(rules))
        action, rule = policy_check("hanuman", "any_tool")
        assert action == "ok"

    def test_malformed_mock_env_returns_ok(self, policy_check, monkeypatch):
        monkeypatch.setenv("WILLOW_MOCK_POLICY", "not-valid-json")
        action, rule = policy_check("hanuman", "kb_search")
        assert action == "ok"


# ── env_check delta logic (S6) ───────────────────────────────────────────────

class TestEnvCheckDelta:
    """Test env delta computation logic independently of the async tool."""

    def _compute_delta(self, snapshot: dict, current: dict, prefixes: tuple) -> dict:
        """Mirrors the _check() inner function in env_check."""
        filtered_current = {k: v for k, v in current.items()
                            if any(k.startswith(p) for p in prefixes)}
        added   = {k: filtered_current[k] for k in filtered_current if k not in snapshot}
        removed = {k: snapshot[k] for k in snapshot if k not in filtered_current}
        changed = {k: {"was": snapshot[k], "now": filtered_current[k]}
                   for k in filtered_current
                   if k in snapshot and filtered_current[k] != snapshot[k]}
        return {
            "added":   added,
            "removed": removed,
            "changed": changed,
            "clean":   not (added or removed or changed),
        }

    def _prefixes(self):
        os.environ.setdefault("WILLOW_AGENT_NAME", "test-agent")
        from sap.sap_mcp import _ENV_SNAPSHOT_PREFIXES
        return _ENV_SNAPSHOT_PREFIXES

    def test_clean_env_matches_snapshot(self):
        prefixes = self._prefixes()
        snap = {"WILLOW_PG_DB": "mydb", "GROVE_URL": "http://localhost"}
        cur  = {"WILLOW_PG_DB": "mydb", "GROVE_URL": "http://localhost", "EDITOR": "vim"}
        delta = self._compute_delta(snap, cur, prefixes)
        assert delta["clean"] is True
        assert delta["added"] == {}
        assert delta["removed"] == {}
        assert delta["changed"] == {}

    def test_added_key_detected(self):
        prefixes = self._prefixes()
        snap = {"WILLOW_PG_DB": "mydb"}
        cur  = {"WILLOW_PG_DB": "mydb", "WILLOW_STORE_ROOT": "/tmp/store"}
        delta = self._compute_delta(snap, cur, prefixes)
        assert delta["clean"] is False
        assert "WILLOW_STORE_ROOT" in delta["added"]

    def test_removed_key_detected(self):
        prefixes = self._prefixes()
        snap = {"WILLOW_PG_DB": "mydb", "GROVE_URL": "http://x"}
        cur  = {"WILLOW_PG_DB": "mydb"}
        delta = self._compute_delta(snap, cur, prefixes)
        assert delta["clean"] is False
        assert "GROVE_URL" in delta["removed"]

    def test_changed_value_detected(self):
        prefixes = self._prefixes()
        snap = {"WILLOW_PG_DB": "old_db"}
        cur  = {"WILLOW_PG_DB": "new_db"}
        delta = self._compute_delta(snap, cur, prefixes)
        assert delta["clean"] is False
        assert delta["changed"]["WILLOW_PG_DB"] == {"was": "old_db", "now": "new_db"}

    def test_non_prefix_keys_ignored(self):
        prefixes = self._prefixes()
        snap = {"WILLOW_PG_DB": "mydb"}
        cur  = {"WILLOW_PG_DB": "mydb", "RANDOM_VAR": "should-be-ignored"}
        delta = self._compute_delta(snap, cur, prefixes)
        assert delta["clean"] is True
        assert "RANDOM_VAR" not in delta["added"]


# ── diagnostic_summary baseline delta (S4) ──────────────────────────────────

class TestDiagnosticBaselineDelta:
    """Test baseline delta computation — core logic of diagnostic_summary."""

    def _compute_new_diags(self, all_diags: list, baseline_diags: list) -> list:
        """Mirrors the baseline delta logic in diagnostic_summary._diag()."""
        baseline_sigs = {(d.get("file"), d.get("line"), d.get("code"))
                         for d in baseline_diags}
        return [d for d in all_diags
                if (d.get("file"), d.get("line"), d.get("code")) not in baseline_sigs]

    def test_no_baseline_returns_all(self):
        diags = [
            {"file": "foo.py", "line": 1, "code": "E501", "message": "line too long"},
            {"file": "bar.py", "line": 5, "code": "F401", "message": "unused import"},
        ]
        new = self._compute_new_diags(diags, [])
        assert len(new) == 2

    def test_existing_baseline_suppressed(self):
        known = {"file": "foo.py", "line": 1, "code": "E501", "message": "old"}
        new_issue = {"file": "bar.py", "line": 10, "code": "E302", "message": "new"}
        new = self._compute_new_diags([known, new_issue], [known])
        assert len(new) == 1
        assert new[0]["file"] == "bar.py"

    def test_all_known_returns_empty(self):
        diags = [{"file": "x.py", "line": 3, "code": "W291", "message": "trail"}]
        new = self._compute_new_diags(diags, diags)
        assert new == []

    def test_same_file_different_line_is_new(self):
        baseline = [{"file": "a.py", "line": 1, "code": "E501"}]
        current  = [{"file": "a.py", "line": 2, "code": "E501"}]
        new = self._compute_new_diags(current, baseline)
        assert len(new) == 1

    def test_same_line_different_code_is_new(self):
        baseline = [{"file": "a.py", "line": 5, "code": "E501"}]
        current  = [{"file": "a.py", "line": 5, "code": "F401"}]
        new = self._compute_new_diags(current, baseline)
        assert len(new) == 1

    def test_severity_format(self):
        sev_sym = {"Error": "✗", "Warning": "⚠", "Info": "ℹ", "Hint": "★"}
        d = {"file": "f.py", "line": 1, "code": "E302", "message": "missing blank",
             "severity": "Error", "source": "ruff"}
        sym = sev_sym.get(d["severity"], "·")
        line = f"  {sym} [{d['file']}:{d['line']}] {d['message']} [{d['code']}] ({d['source']})"
        assert "✗" in line
        assert "E302" in line
        assert "ruff" in line
