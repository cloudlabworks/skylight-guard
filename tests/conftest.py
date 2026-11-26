"""Load the pure modules by file path.

Importing ``custom_components.skylight_guard`` would execute its
``__init__.py`` (which needs Home Assistant). ``guard.py`` and
``event_payload.py`` are deliberately free of Home Assistant imports, so the
tests load them directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "skylight_guard"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"skylight_guard_{name}", PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def guard():
    return _load("guard")


@pytest.fixture(scope="session")
def event_payload():
    return _load("event_payload")


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT
