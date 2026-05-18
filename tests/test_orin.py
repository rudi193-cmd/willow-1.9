"""Tests for agents/orin — mistral:7b batch processor sub-agent.

Tests the task handlers in isolation using mock _ask_ollama responses.
No real Ollama call is made.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = str(Path(__file__).parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_ollama(response: str):
    """Patch _ask_ollama to return a fixed string."""
    return patch("sap.clients.professor_client._ask_ollama", return_value=response)


# ── summarize ─────────────────────────────────────────────────────────────────

class TestSummarize:
    def test_valid_json_response(self):
        payload = json.dumps({"bullets": ["Point A", "Point B"], "one_line": "Summary"})
        with _mock_ollama(payload):
            from agents.orin.tasks import summarize
            result = summarize("Some content about Willow")
        assert result["task"] == "summarize"
        assert result["result"]["bullets"] == ["Point A", "Point B"]
        assert result["result"]["one_line"] == "Summary"

    def test_json_in_code_fence(self):
        payload = '```json\n{"bullets": ["Fact 1"], "one_line": "short"}\n```'
        with _mock_ollama(payload):
            from agents.orin.tasks import summarize
            result = summarize("content")
        assert result["result"]["bullets"] == ["Fact 1"]

    def test_fallback_on_plain_bullets(self):
        plain = "- First thing\n- Second thing\n- Third thing"
        with _mock_ollama(plain):
            from agents.orin.tasks import summarize
            result = summarize("content")
        assert len(result["result"]["bullets"]) == 3

    def test_context_passed_through(self):
        resp = json.dumps({"bullets": ["x"], "one_line": "y"})
        captured = []
        def mock_ask(model, system, user):
            captured.append(user)
            return resp
        with patch("sap.clients.professor_client._ask_ollama", mock_ask):
            from agents.orin import tasks as t
            import importlib; importlib.reload(t)
            t.summarize("content", context="extra context")
        assert any("extra context" in u for u in captured)


# ── classify ──────────────────────────────────────────────────────────────────

class TestClassify:
    def test_valid_json_response(self):
        payload = json.dumps({"category": "code", "confidence": 0.9, "reason": "has code"})
        with _mock_ollama(payload):
            from agents.orin.tasks import classify
            result = classify("def foo(): pass", ["code", "governance", "general"])
        assert result["task"] == "classify"
        assert result["result"]["category"] == "code"
        assert result["result"]["confidence"] == 0.9

    def test_fallback_finds_mentioned_category(self):
        with _mock_ollama("This looks like governance to me."):
            from agents.orin.tasks import classify
            result = classify("some policy text", ["code", "governance", "general"])
        assert result["result"]["category"] == "governance"

    def test_fallback_returns_first_category_on_total_failure(self):
        with _mock_ollama("I have no idea what this is."):
            from agents.orin.tasks import classify
            result = classify("nonsense", ["code", "governance"])
        assert result["result"]["category"] == "code"
        assert result["parse_error"] is True


# ── extract ───────────────────────────────────────────────────────────────────

class TestExtract:
    def test_valid_json_array(self):
        atoms = [
            {"title": "Willow uses Postgres", "summary": "Postgres stores KB atoms", "category": "architecture"},
            {"title": "SOIL is local", "summary": "SOIL uses SQLite for local store", "category": "architecture"},
        ]
        with _mock_ollama(json.dumps(atoms)):
            from agents.orin.tasks import extract
            result = extract("Willow uses Postgres for KB. SOIL uses SQLite locally.")
        assert result["task"] == "extract"
        assert result["result"]["count"] == 2
        assert result["result"]["atoms"][0]["title"] == "Willow uses Postgres"

    def test_wrapped_in_atoms_key(self):
        payload = json.dumps({"atoms": [{"title": "T", "summary": "S", "category": "general"}]})
        with _mock_ollama(payload):
            from agents.orin.tasks import extract
            result = extract("content")
        assert result["result"]["count"] == 1

    def test_empty_parse_returns_zero_atoms(self):
        with _mock_ollama("I cannot extract anything useful."):
            from agents.orin.tasks import extract
            result = extract("content")
        assert result["result"]["count"] == 0
        assert result["result"]["atoms"] == []


# ── tension ───────────────────────────────────────────────────────────────────

class TestTension:
    def test_conflict_detected(self):
        payload = json.dumps({"conflict": True, "score": 0.9, "reason": "A says up, B says down"})
        with _mock_ollama(payload):
            from agents.orin.tasks import tension
            result = tension("The sky is up", "The sky is down")
        assert result["task"] == "tension"
        assert result["result"]["conflict"] is True
        assert result["result"]["score"] == 0.9

    def test_no_conflict(self):
        payload = json.dumps({"conflict": False, "score": 0.05, "reason": "Complementary"})
        with _mock_ollama(payload):
            from agents.orin.tasks import tension
            result = tension("Water is wet", "Ice is cold")
        assert result["result"]["conflict"] is False

    def test_fallback_on_plain_text_conflict_word(self):
        with _mock_ollama("These clearly contradict each other."):
            from agents.orin.tasks import tension
            result = tension("A", "B")
        assert result["result"]["conflict"] is True
        assert result["parse_error"] is True

    def test_fallback_no_conflict_word(self):
        with _mock_ollama("They seem compatible."):
            from agents.orin.tasks import tension
            result = tension("A", "B")
        assert result["result"]["conflict"] is False


# ── dispatcher ────────────────────────────────────────────────────────────────

class TestDispatcher:
    def test_unknown_task_type_returns_error(self):
        from agents.orin.tasks import run
        result = run("nonexistent", {"content": "x"})
        assert "error" in result
        assert "nonexistent" in result["error"]

    def test_valid_dispatch_summarize(self):
        payload = json.dumps({"bullets": ["b"], "one_line": "l"})
        with _mock_ollama(payload):
            from agents.orin.tasks import run
            result = run("summarize", {"content": "some text"})
        assert result["task"] == "summarize"

    def test_valid_dispatch_tension(self):
        payload = json.dumps({"conflict": False, "score": 0.1, "reason": "ok"})
        with _mock_ollama(payload):
            from agents.orin.tasks import run
            result = run("tension", {"atom_a": "A", "atom_b": "B"})
        assert result["task"] == "tension"
