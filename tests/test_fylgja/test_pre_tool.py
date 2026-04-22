import json
from unittest.mock import patch
from willow.fylgja.events.pre_tool import (
    check_bash_block,
    check_agent_block,
    check_kb_first,
)


def test_blocks_psql():
    reason = check_bash_block("psql -U willow willow_19")
    assert reason is not None
    assert "MCP" in reason


def test_blocks_cat():
    reason = check_bash_block("cat /home/sean/somefile.py")
    assert reason is not None
    assert "Read" in reason


def test_blocks_ls():
    reason = check_bash_block("ls /home/sean/")
    assert reason is not None
    assert "Glob" in reason


def test_allows_git():
    reason = check_bash_block("git log --oneline -10")
    assert reason is None


def test_allows_pytest():
    reason = check_bash_block("python3 -m pytest tests/ -v")
    assert reason is None


def test_blocks_explore_subagent():
    reason = check_agent_block("Explore")
    assert reason is not None
    assert "MCP" in reason


def test_allows_general_purpose_agent():
    reason = check_agent_block("general-purpose")
    assert reason is None


def test_kb_first_returns_advisory_when_record_found():
    mock_result = [{"id": "abc", "title": "settings.json", "collection": "hanuman/file-index"}]
    with patch("willow.fylgja.events.pre_tool._mcp_store_search", return_value=mock_result):
        advisory = check_kb_first("/home/sean/.claude/settings.json")
    assert advisory is not None
    assert "KB-FIRST" in advisory


def test_kb_first_returns_none_when_no_record():
    with patch("willow.fylgja.events.pre_tool._mcp_store_search", return_value=[]):
        advisory = check_kb_first("/some/unknown/file.py")
    assert advisory is None
