"""Shared fixtures for ticket P0-02 acceptance tests (contracts v1, PRD 15.2).

Run with `uv run pytest tests/contracts -q` (jsonschema and referencing are
root dev dependencies as of this ticket's test wiring; see pyproject.toml and
uv.lock). Unlike tests/repo, these tests need real $ref resolution across
contracts/*.schema.json, so they are not written to run standalone with
`--no-project`.
"""

from __future__ import annotations

import pathlib

import pytest
from _lib import build_registry, contracts_dir
from hypothesis import settings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Timing is not a contract property. Under load (parallel sessions, CI) the 200 ms default
# deadline made regex-driven property tests flaky; the properties themselves are unchanged.
settings.register_profile("contracts", deadline=None)
settings.load_profile("contracts")


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def contracts_root(repo_root: pathlib.Path) -> pathlib.Path:
    return contracts_dir(repo_root)


@pytest.fixture(scope="session")
def registry(repo_root: pathlib.Path):
    """A referencing.Registry over every contracts/**/*.schema.json found right
    now. Session-scoped: rebuilt once per test run, which is correct because
    nothing in this test suite writes to contracts/.
    """
    return build_registry(repo_root)
