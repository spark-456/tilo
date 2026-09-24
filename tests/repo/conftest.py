"""Shared fixtures for repo-level acceptance tests (ticket P0-01, PRD 20.3/20.4).

Run before the uv workspace exists with:
  uv run --no-project --with pytest --with pyyaml pytest tests/repo -q

stdlib + tomllib + pyyaml only: no third-party test dependencies beyond
pytest and pyyaml, so these tests run before `just setup` has created the
uv/pnpm workspaces they are checking for.
"""
from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT
