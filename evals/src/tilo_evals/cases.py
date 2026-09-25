"""Case schema and loader (EFF-07; PRD 19.2): validates evals/cases/<group>/<id>.yaml against
case.schema.json, then checks what the schema can't: id/group/dir/filename, unique ids, registered checks."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from . import checks as checks_registry

REPO_ROOT = Path(__file__).resolve().parents[3]
CASE_SCHEMA_PATH = REPO_ROOT / "evals" / "case.schema.json"
_ID_PATTERN = re.compile(r"^E-(PLAN|RES|DOC|MAIL|CHN|ROUTE|HAND|RED)-\d{2}$")


class CaseError(Exception):
    """Case fails case.schema.json, or a loader rule: id/group/dir/filename, duplicate id, unregistered check."""


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
    notes: str | None = None


def load_cases(root: str = "evals/cases") -> list[Case]:
    root_path = Path(root)
    if not root_path.is_dir():
        return []
    validator = jsonschema.Draft202012Validator(json.loads(CASE_SCHEMA_PATH.read_text(encoding="utf-8")))
    seen: dict[str, Path] = {}
    cases: list[Case] = []
    for case_path in sorted(root_path.rglob("*.yaml")):
        raw: Any = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
        case_id = raw.get("id", "<missing id>") if isinstance(raw, dict) else "<not a mapping>"
        errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
        if errors:
            raise CaseError(
                f"{case_path}: {case_id!r} failed case.schema.json: " + "; ".join(e.message for e in errors)
            )
        group, dir_name = raw["group"], case_path.parent.name
        match = _ID_PATTERN.match(case_id)  # schema enforces the pattern; guard against drift
        if dir_name != group or (f"E-{match.group(1)}" if match else None) != group:
            raise CaseError(f"{case_path}: {case_id!r} group/dir mismatch (group={group!r}, dir={dir_name!r})")
        if case_path.stem != case_id:
            raise CaseError(f"{case_path}: filename {case_path.stem!r} does not match id {case_id!r}")
        for entry in raw["checks"]:  # kind: autorater is declared, not run in replay; skip the lookup
            if entry.get("kind") != "autorater" and not checks_registry.is_registered(entry.get("check")):
                raise CaseError(f"{case_path}: {case_id!r} uses an unregistered check {entry.get('check')!r}")
        if case_id in seen:
            raise CaseError(f"duplicate case id {case_id!r}: {seen[case_id]} and {case_path}")
        seen[case_id] = case_path
        kwargs = dict(raw, measures=tuple(raw["measures"]), scripted_answers=tuple(raw["scripted_answers"]))
        kwargs.setdefault("notes", None)
        cases.append(Case(path=case_path, **kwargs))
    return cases
