"""Shared fixtures and plain data factories for packages/policy acceptance tests (ticket P4-01,
PRD 10.4, docs/security/p4-policy-invariants.md).

No business logic lives here (root CLAUDE.md test-writer rule): every helper below either loads
a file unchanged or returns a literal dict shaped like the contract it names. The engine itself
(packages/policy/src/tilo_policy) does not exist yet; importing it is what makes these tests
fail for the right reason until the builder ships it (see API.md in this directory).

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, the same plain-module-import pattern
packages/providers/tests/conftest.py and tests/contracts/_lib.py use.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


def contracts_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "contracts"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def list_fixtures(repo_root: pathlib.Path, relative: str) -> list[pathlib.Path]:
    """Every *.json directly under contracts/fixtures/<relative>/."""
    d = contracts_dir(repo_root) / "fixtures" / relative
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


@pytest.fixture(scope="session")
def risk_table_path(repo_root: pathlib.Path) -> pathlib.Path:
    """PRD 10.4 tiers fixture: config/autonomy.yaml is not in the repo yet
    (spark-456/tilo#1), so tests always load an explicit fixture path rather than
    tilo_policy.load_risk_table()'s default."""
    return contracts_dir(repo_root) / "fixtures" / "policy.risk_tier_table" / "valid" / "prd_10_4_tiers.json"


@pytest.fixture()
def risk_table_invalid_paths(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return list_fixtures(repo_root, "policy.risk_tier_table/invalid")


@pytest.fixture()
def crossref_valid_cases(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/crossref/valid")]


@pytest.fixture()
def crossref_invalid_cases(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/crossref/invalid")]


@pytest.fixture()
def l2_action_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stands in for ADR-0013 (Proposed): tests of the L2 rules that run after it lands set
    `L2_ACTION_RECORDED` True. Without this fixture the engine gates every L2 send (BQ-57, PI-21)."""
    from tilo_policy import coverage

    monkeypatch.setattr(coverage, "L2_ACTION_RECORDED", True)
