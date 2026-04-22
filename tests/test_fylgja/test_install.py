import json
from pathlib import Path
from willow.fylgja.install import build_hooks_block, apply_hooks

PACKAGE_ROOT = Path("/home/sean-campbell/github/willow-1.9")


def test_build_hooks_block_contains_all_events():
    block = build_hooks_block(PACKAGE_ROOT)
    assert "SessionStart" in block
    assert "UserPromptSubmit" in block
    assert "PreToolUse" in block
    assert "PostToolUse" in block
    assert "Stop" in block


def test_build_hooks_block_points_at_fylgja():
    block = build_hooks_block(PACKAGE_ROOT)
    assert "fylgja" in json.dumps(block)


def test_apply_hooks_dry_run_does_not_write(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}))
    apply_hooks(settings_path=settings, package_root=PACKAGE_ROOT, dry_run=True)
    content = json.loads(settings.read_text())
    assert content == {"hooks": {}}


def test_apply_hooks_writes_block(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "sonnet", "hooks": {}}))
    apply_hooks(settings_path=settings, package_root=PACKAGE_ROOT, dry_run=False)
    content = json.loads(settings.read_text())
    assert "SessionStart" in content["hooks"]
    assert content["model"] == "sonnet"
