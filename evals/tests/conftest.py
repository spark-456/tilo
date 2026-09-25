"""Fixtures for the P8-06a loader tests (EFF-07): `repo_root`, `write_case`,
and a stand-in "no_side_effects" check (real one lands in part b) so a well-formed case loads.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml
from tilo_evals import checks as checks_registry
from tilo_evals.checks import CheckResult

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@checks_registry.register("no_side_effects")
def _stub_no_side_effects(case: Any, outcome: Any) -> CheckResult:  # noqa: ARG001
    return CheckResult(passed=True)


def write_case(
    cases_root: pathlib.Path, *, case_id: str, group: str, filename: str | None = None, **overrides: Any
) -> pathlib.Path:
    """Writes evals/cases/<group>/<id>.yaml; `filename` places a malformed case
    independently of case_id/group, and any case field overrides its default."""
    body: dict[str, Any] = {
        "id": case_id,
        "group": group,
        "title": "Fixture case",
        "measures": ["EFF-07"],
        "status": "ready",
        "deploy_gate": False,
        "inputs": {},
        "scripted_answers": [],
        "ground_truth": None,
        "checks": [{"check": "no_side_effects", "args": {}}],
        "recording": None,
    }
    body.update(overrides)
    group_dir = cases_root / group
    group_dir.mkdir(parents=True, exist_ok=True)
    case_path = group_dir / (filename or f"{case_id}.yaml")
    case_path.write_bytes(yaml.safe_dump(body, sort_keys=False).encode("utf-8"))
    return case_path
