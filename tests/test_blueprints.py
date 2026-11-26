"""Parse every blueprint and check its structure."""

from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml


class Input(str):
    """Marker for !input references."""


class BlueprintLoader(yaml.SafeLoader):
    pass


def _input(loader: yaml.SafeLoader, node: yaml.Node) -> Input:
    return Input(loader.construct_scalar(node))


BlueprintLoader.add_constructor("!input", _input)

REPO_ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT_DIR = REPO_ROOT / "blueprints" / "automation"
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


# Forks keep working: any GitHub owner/repo/branch, but the path must be the file's own.
SOURCE_URL = re.compile(r"^https://github\.com/[^/]+/[^/]+/blob/[^/]+/(?P<path>.+)$")


def _walk_entity_ids(node, bad: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "entity_id":
                values = v if isinstance(v, list) else [v]
                for item in values:
                    if not isinstance(item, Input) and "{{" not in str(item):
                        bad.append(item)
            else:
                _walk_entity_ids(v, bad)
    elif isinstance(node, list):
        for v in node:
            _walk_entity_ids(v, bad)


def test_core_blueprints_present():
    names = {f.name for f in FILES}
    assert {
        "rogue_event_alert.yaml",
        "morning_greeting.yaml",
        "chore_due_reminder.yaml",
        "frame_bedtime.yaml",
        "home_event_to_frame.yaml",
    } <= names


def test_community_template_present():
    assert (BLUEPRINT_DIR / "community" / "_template.yaml").is_file()


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_blueprint_structure(path: Path):
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=BlueprintLoader)
    bp = doc["blueprint"]
    assert bp["domain"] == "automation"
    assert bp["name"].startswith("Skylight")
    match = SOURCE_URL.match(bp["source_url"])
    assert match, f"source_url is not a GitHub blob URL: {bp['source_url']}"
    if path.name != "_template.yaml":
        assert match["path"] == path.relative_to(REPO_ROOT).as_posix()
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

    body = {k: v for k, v in doc.items() if k != "blueprint"}
    hard_coded: list = []
    _walk_entity_ids(body, hard_coded)
    assert not hard_coded, f"hard-coded entity_id values: {hard_coded}"
    assert "calendar.create_event" not in path.read_text(encoding="utf-8"), (
        "write events with skylight_guard.create_event so the guard sees them"
    )


def test_morning_greeting_uses_guarded_service():
    text = (BLUEPRINT_DIR / "skylight_guard" / "morning_greeting.yaml").read_text()
    assert "action: skylight_guard.create_event" in text
