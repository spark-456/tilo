"""Case schema and loader (EFF-07; PRD 19.2: "Each case lives in
evals/cases/<group>/<id>.yaml with inputs, scripted answers, ground truth
and checks"). `load_cases` validates every file against
`evals/case.schema.json`, then checks the loader-level rules the schema
cannot express on its own: the id's family prefix matches `group` and the
file's own directory, ids are unique, and every check name is registered
(P8-06 spec).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from . import checks as checks_registry

# evals/src/tilo_evals/cases.py -> parents[3] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
CASE_SCHEMA_PATH = REPO_ROOT / "evals" / "case.schema.json"

_ID_PATTERN = re.compile(r"^E-(PLAN|RES|DOC|MAIL|CHN|ROUTE|HAND|RED)-\d{2}$")


class CaseError(Exception):
    """Raised when a case file fails case.schema.json, or breaks a
    loader-level rule: id/group/directory mismatch, a duplicate id, or an
    unregistered check name."""


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    title: str
    measures: tuple[str, ...]
    status: str
    deploy_gate: bool
    inputs: dict[str, Any]
    scripted_answers: tuple[dict[str, str], ...]
    ground_truth: dict[str, Any] | None
    checks: list[dict[str, Any]]
    recording: str | None
    path: Path


def _load_schema() -> dict[str, Any]:
    import json

    return json.loads(CASE_SCHEMA_PATH.read_text(encoding="utf-8"))


def load_cases(root: str = "evals/cases") -> list[Case]:
    root_path = Path(root)
    validator = jsonschema.Draft202012Validator(_load_schema())

    seen_ids: dict[str, Path] = {}
    cases: list[Case] = []

    if not root_path.is_dir():
        return cases

    for case_path in sorted(root_path.rglob("*.yaml")):
        raw: Any = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
        case_id = raw.get("id", "<missing id>") if isinstance(raw, dict) else "<not a mapping>"

        errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
        if errors:
            messages = "; ".join(error.message for error in errors)
            raise CaseError(f"{case_path}: case {case_id!r} failed case.schema.json: {messages}")

        group = raw["group"]
        dir_name = case_path.parent.name
        if dir_name != group:
            raise CaseError(
                f"{case_path}: case {case_id!r} has group {group!r}, but lives under directory {dir_name!r}"
            )

        match = _ID_PATTERN.match(case_id)
        # case.schema.json already enforces this pattern; match is always
        # truthy here, but guard against a schema/loader drift regardless.
        if match is None:
            raise CaseError(f"{case_path}: case id {case_id!r} does not match the E-<FAMILY>-NN pattern")
        expected_group = f"E-{match.group(1)}"
        if expected_group != group:
            raise CaseError(
                f"{case_path}: case {case_id!r} implies group {expected_group!r}, but its group field is {group!r}"
            )

        for entry in raw["checks"]:
            check_name = entry.get("check")
            if not checks_registry.is_registered(check_name):
                raise CaseError(f"{case_path}: case {case_id!r} uses an unregistered check {check_name!r}")

        if case_id in seen_ids:
            raise CaseError(f"duplicate case id {case_id!r}: {seen_ids[case_id]} and {case_path}")
        seen_ids[case_id] = case_path

        cases.append(
            Case(
                id=case_id,
                group=group,
                title=raw["title"],
                measures=tuple(raw["measures"]),
                status=raw["status"],
                deploy_gate=raw["deploy_gate"],
                inputs=raw["inputs"],
                scripted_answers=tuple(raw["scripted_answers"]),
                ground_truth=raw["ground_truth"],
                checks=raw["checks"],
                recording=raw["recording"],
                path=case_path,
            )
        )

    return cases
