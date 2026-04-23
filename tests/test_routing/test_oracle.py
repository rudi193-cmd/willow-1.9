"""willow_route oracle — rule-based fast path and LLM fallback."""
from unittest.mock import patch
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from willow.routing.oracle import route, load_rules, match_rules, DEFAULT_AGENT

SAMPLE_RULES = [
    {"id": "rule-kart",    "pattern": r"\b(task|build|deploy|run|execute)\b",       "agent": "kart",    "priority": 10},
    {"id": "rule-ganesha", "pattern": r"\b(debug|error|diagnose|fix|broken)\b",      "agent": "ganesha", "priority": 10},
    {"id": "rule-jeles",   "pattern": r"\b(search|find|retrieve|index|library)\b",   "agent": "jeles",   "priority": 10},
    {"id": "rule-grove",   "pattern": r"\b(message|channel|send|notify|post)\b",     "agent": "grove",   "priority": 10},
]


def test_match_rules_returns_first_match():
    result = match_rules("debug the gleipnir rate limit", SAMPLE_RULES)
    assert result is not None
    assert result["agent"] == "ganesha"
    assert result["id"] == "rule-ganesha"


def test_match_rules_returns_none_when_no_match():
    result = match_rules("what time is it", SAMPLE_RULES)
    assert result is None


def test_match_rules_case_insensitive():
    result = match_rules("SEND a message to architecture", SAMPLE_RULES)
    assert result is not None
    assert result["agent"] == "grove"


def test_route_rule_match_returns_correct_shape():
    with patch("willow.routing.oracle._load_rules_from_store", return_value=SAMPLE_RULES):
        with patch("willow.routing.oracle._write_decision"):
            decision = route("run the test suite", session_id="abc123")
    assert decision["routed_to"] == "kart"
    assert decision["rule_matched"] == "rule-kart"
    assert decision["confidence"] == 1.0
    assert "latency_ms" in decision
    assert "ts" in decision


def test_route_defaults_to_willow_when_no_rules():
    with patch("willow.routing.oracle._load_rules_from_store", return_value=[]):
        with patch("willow.routing.oracle._llm_route", return_value=None):
            with patch("willow.routing.oracle._write_decision"):
                decision = route("something ambiguous", session_id="abc123")
    assert decision["routed_to"] == DEFAULT_AGENT
    assert decision["rule_matched"] == "llm-fallback"


def test_route_llm_fallback_called_when_no_rule_matches():
    with patch("willow.routing.oracle._load_rules_from_store", return_value=SAMPLE_RULES):
        with patch("willow.routing.oracle._llm_route", return_value={"agent": "gerald", "confidence": 0.72}) as mock_llm:
            with patch("willow.routing.oracle._write_decision"):
                decision = route("ponder the ontology of memory", session_id="abc123")
    mock_llm.assert_called_once()
    assert decision["routed_to"] == "gerald"
    assert decision["rule_matched"] == "llm-fallback"
    assert decision["confidence"] == 0.72


def test_route_snippet_truncated_to_40_chars():
    long_prompt = "a" * 200
    with patch("willow.routing.oracle._load_rules_from_store", return_value=[]):
        with patch("willow.routing.oracle._llm_route", return_value=None):
            with patch("willow.routing.oracle._write_decision"):
                decision = route(long_prompt, session_id="abc")
    assert len(decision["prompt_snippet"]) <= 40


def test_match_rules_skips_bad_regex():
    bad_rules = [{"id": "bad", "pattern": "[invalid(", "agent": "kart", "priority": 10}]
    result = match_rules("anything", bad_rules)
    assert result is None
