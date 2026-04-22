import json
from pathlib import Path
from unittest.mock import patch
from willow.fylgja.events.prompt_submit import (
    detect_feedback,
    should_anchor,
    get_active_task,
)


def test_detect_feedback_finds_hook_error():
    results = detect_feedback("the hooks are broken and not firing")
    assert any(r["type"] == "technical" for r in results)


def test_detect_feedback_finds_background_pattern():
    results = detect_feedback("you should run that in the background")
    assert any(r["type"] == "process" for r in results)


def test_detect_feedback_empty_on_clean_prompt():
    results = detect_feedback("what is the weather today")
    assert results == []


def test_should_anchor_true_at_interval(tmp_path):
    state_file = tmp_path / "anchor_state.json"
    state_file.write_text(json.dumps({"prompt_count": 9}))
    with patch("willow.fylgja.events.prompt_submit.STATE_FILE", state_file):
        assert should_anchor() is True


def test_should_anchor_false_before_interval(tmp_path):
    state_file = tmp_path / "anchor_state.json"
    state_file.write_text(json.dumps({"prompt_count": 3}))
    with patch("willow.fylgja.events.prompt_submit.STATE_FILE", state_file):
        assert should_anchor() is False


def test_get_active_task_returns_none_when_no_file(tmp_path):
    with patch("willow.fylgja.events.prompt_submit.ACTIVE_BUILD_FILE",
               tmp_path / "missing.json"):
        assert get_active_task() is None


def test_get_active_task_returns_label(tmp_path):
    f = tmp_path / "build.json"
    f.write_text(json.dumps({"label": "Implementing Fylgja events"}))
    with patch("willow.fylgja.events.prompt_submit.ACTIVE_BUILD_FILE", f):
        assert get_active_task() == "Implementing Fylgja events"
