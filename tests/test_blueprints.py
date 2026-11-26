"""Parse every blueprint and check its structure."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


class Input(str):
    """Marker for !input references."""


class BlueprintLoader(yaml.SafeLoader):
    pass


def _input(loader: yaml.SafeLoader, node: yaml.Node) -> Input:
    return Input(loader.construct_scalar(node))


BlueprintLoader.add_constructor("!input", _input)

BLUEPRINT_DIR = Path(__file__).resolve().parent.parent / "blueprints" / "automation"
FILES = sorted(BLUEPRINT_DIR.rglob("*.yaml"))


def _walk_inputs(node, found: set[str]) -> None:
    if isinstance(node, Input):
        found.add(str(node))
    elif isinstance(node, dict):
        for v in node.values():
            _walk_inputs(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_inputs(v, found)


def test_three_blueprints_present():
    names = {f.name for f in FILES}
    assert {"rogue_event_alert.yaml", "morning_greeting.yaml", "chore_due_reminder.yaml"} <= names


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_blueprint_structure(path: Path):
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=BlueprintLoader)
    bp = doc["blueprint"]
    assert bp["domain"] == "automation"
    assert bp["name"].startswith("Skylight Guard")
    assert bp["source_url"].startswith("https://github.com/cloudlabworks/skylight-guard/")
    assert bp["source_url"].endswith(path.name)
    assert isinstance(bp["input"], dict) and bp["input"]
    for key, spec in bp["input"].items():
        assert "selector" in spec, f"input {key} has no selector"
    assert doc.get("triggers"), "no triggers"
    assert doc.get("actions"), "no actions"

    used: set[str] = set()
    _walk_inputs({k: v for k, v in doc.items() if k != "blueprint"}, used)
    declared = set(bp["input"])
    assert used <= declared, f"undeclared inputs: {used - declared}"
    assert declared <= used, f"unused inputs: {declared - used}"


def test_morning_greeting_uses_guarded_service():
    text = (BLUEPRINT_DIR / "skylight_guard" / "morning_greeting.yaml").read_text()
    assert "action: skylight_guard.create_event" in text
