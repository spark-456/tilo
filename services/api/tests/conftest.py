"""Shared fixtures for ticket ST-3b acceptance tests (services/api/tests, module family
tilo_api.cards). New conftest.py for this directory (services/api/tests did not exist before
this ticket); kept minimal and additive per the ticket instructions.

Run with `uv run pytest services/api/tests -q` (jsonschema and referencing are root dev
dependencies; see root pyproject.toml, the same ones tests/contracts and packages/policy/tests
already rely on).
"""

from __future__ import annotations

import pathlib

import pytest
from _cards_lib import REPO_ROOT, build_registry


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def registry():
    """A referencing.Registry over every contracts/**/*.schema.json, for resolving
    card.schema.json's $refs into common.schema.json."""
    return build_registry(REPO_ROOT)
