"""Helpers for the P8-06a loader tests (EFF-07): REPO_ROOT, write_case, a stand-in no_side_effects check."""

import pathlib
from typing import Any

import yaml
from tilo_evals import checks as checks_registry
from tilo_evals.checks import CheckResult

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEFAULTS = {"title": "Fixture case", "measures": ["EFF-07"], "status": "ready", "deploy_gate": False}
_DEFAULTS |= {"inputs": {}, "scripted_answers": [], "ground_truth": None, "recording": None}
_DEFAULTS["checks"] = [{"check": "no_side_effects", "args": {}}]


def _stub_no_side_effects(case: Any, outcome: Any) -> CheckResult:  # noqa: ARG001
    return CheckResult(passed=True)


# Part b may register a real "no_side_effects" check in tilo_evals.checks; don't clobber it with this
# loader-only stand-in (needed so a schema-valid case file can reference *a* registered check before part b lands).
if not checks_registry.is_registered("no_side_effects"):
    checks_registry.register("no_side_effects")(_stub_no_side_effects)


def write_case(cases_root: pathlib.Path, *, case_id: str, group: str, filename: str | None = None, **overrides: Any):
    body = {"id": case_id, "group": group, **_DEFAULTS, **overrides}
    case_path = cases_root / group / (filename or f"{case_id}.yaml")
    case_path.parent.mkdir(parents=True, exist_ok=True)
    case_path.write_bytes(yaml.safe_dump(body, sort_keys=False).encode("utf-8"))
    return case_path
