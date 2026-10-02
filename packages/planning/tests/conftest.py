"""Pytest fixtures for ticket FR-INT-01/FR-INT-02 acceptance tests. Fixture builders, schema
validation and the deterministic `SafetyProvider` fake live in `_planning_contracts_lib.py` (see
its module docstring for why: this file is auto-loaded by pytest under the bare module name
`"conftest"`, which collides with any sibling test directory's own `conftest.py` in the same
`uv run pytest` session if helpers are imported back out of it with `from conftest import ...`).
"""

from __future__ import annotations

import pathlib

import pytest
from _plan_validator_lib import build_fake_connectors, build_fake_policies, build_fake_skills, build_risk_table
from _planning_contracts_lib import build_registry, make_safety_provider

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def registry(repo_root: pathlib.Path):
    return build_registry(repo_root)


@pytest.fixture()
def safety_provider():
    return make_safety_provider()


# --- FR-INT-09 (PlanGraph validator) fixtures --------------------------------------------------


@pytest.fixture(scope="session")
def risk_table(repo_root: pathlib.Path):
    return build_risk_table(repo_root)


@pytest.fixture(scope="session")
def fake_connectors(repo_root: pathlib.Path):
    return build_fake_connectors(repo_root)


@pytest.fixture(scope="session")
def fake_skills():
    return build_fake_skills()


@pytest.fixture(scope="session")
def fake_policies(repo_root: pathlib.Path):
    return build_fake_policies(repo_root)
