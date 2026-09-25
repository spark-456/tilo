"""Case-schema and loader tests for the P8-06 eval harness (EFF-07 support;
PRD 19.2: "Each case lives in evals/cases/<group>/<id>.yaml with inputs,
scripted answers, ground truth and checks"). Ticket spec (SE orchestrator
"## P8-06"): "load_cases(root='evals/cases') -> list[Case] validates every
file against the schema, checks the id against the path, and checks that ids
are unique and that check names are registered." Acceptance test named in
the spec: "a bad id, a group mismatch, an unknown check, and a duplicate id
are each rejected."

Run with `uv run pytest "evals/tests" -q` from the repo root.
"""

from __future__ import annotations

import json

import jsonschema
import pytest
from conftest import write_case
from tilo_evals import Case, CaseError, load_cases


def test_EFF_07_case_schema_exists_and_is_draft_2020_12(repo_root):
    schema_path = repo_root / "evals" / "case.schema.json"
    assert schema_path.is_file(), "P8-06: evals/case.schema.json must exist (contract-change #8)"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema.get("$schema", "").endswith("2020-12/schema"), "P8-06: case.schema.json must be JSON Schema 2020-12"
    jsonschema.Draft202012Validator.check_schema(schema)


def test_EFF_07_load_cases_loads_a_well_formed_case(tmp_path):
    cases_root = tmp_path / "cases"
    write_case(cases_root, case_id="E-PLAN-01", group="E-PLAN", ground_truth={"ok": True})

    cases = load_cases(root=str(cases_root))

    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, Case)
    assert case.id == "E-PLAN-01"
    assert case.group == "E-PLAN"
    assert case.status == "ready"
    assert case.checks == [{"check": "no_side_effects", "args": {}}]


def test_EFF_07_load_cases_rejects_an_id_not_matching_the_pattern(tmp_path):
    """The id pattern is ^E-(PLAN|RES|DOC|MAIL|CHN|ROUTE|HAND|RED)-\\d{2}$."""
    cases_root = tmp_path / "cases"
    write_case(
        cases_root,
        case_id="not-a-valid-id",
        group="E-PLAN",
        ground_truth={"ok": True},
        filename="not-a-valid-id.yaml",
    )

    with pytest.raises(CaseError) as excinfo:
        load_cases(root=str(cases_root))
    assert "not-a-valid-id" in str(excinfo.value)


def test_EFF_07_load_cases_rejects_a_group_that_does_not_match_the_id_prefix(tmp_path):
    """group must match "the directory and the id prefix" -- here the group
    field and its directory agree (E-RES) but the id's own family prefix
    (E-PLAN) does not, which load_cases must still reject.
    """
    cases_root = tmp_path / "cases"
    write_case(cases_root, case_id="E-PLAN-01", group="E-RES", ground_truth={"ok": True})

    with pytest.raises(CaseError) as excinfo:
        load_cases(root=str(cases_root))
    assert "E-PLAN-01" in str(excinfo.value)


def test_EFF_07_load_cases_rejects_an_unregistered_check_name(tmp_path):
    cases_root = tmp_path / "cases"
    write_case(
        cases_root,
        case_id="E-PLAN-01",
        group="E-PLAN",
        ground_truth={"ok": True},
        checks=[{"check": "not_a_registered_check", "args": {}}],
    )

    with pytest.raises(CaseError) as excinfo:
        load_cases(root=str(cases_root))
    assert "not_a_registered_check" in str(excinfo.value)


def test_EFF_07_load_cases_rejects_a_duplicate_id(tmp_path):
    cases_root = tmp_path / "cases"
    write_case(cases_root, case_id="E-PLAN-01", group="E-PLAN", ground_truth={"ok": True}, filename="a.yaml")
    write_case(cases_root, case_id="E-PLAN-01", group="E-PLAN", ground_truth={"ok": True}, filename="b.yaml")

    with pytest.raises(CaseError) as excinfo:
        load_cases(root=str(cases_root))
    assert "E-PLAN-01" in str(excinfo.value)


def test_EFF_07_load_cases_requires_ground_truth_when_status_is_ready(tmp_path):
    """ "ground_truth (object or null; required non-null when status is ready)"."""
    cases_root = tmp_path / "cases"
    write_case(cases_root, case_id="E-PLAN-01", group="E-PLAN", status="ready", ground_truth=None)

    with pytest.raises(CaseError):
        load_cases(root=str(cases_root))


def test_EFF_07_load_cases_allows_null_ground_truth_when_status_is_skeleton(tmp_path):
    cases_root = tmp_path / "cases"
    write_case(
        cases_root,
        case_id="E-PLAN-01",
        group="E-PLAN",
        status="skeleton",
        ground_truth=None,
        recording=None,
    )

    cases = load_cases(root=str(cases_root))
    assert cases[0].status == "skeleton"
    assert cases[0].ground_truth is None


def test_EFF_07_load_cases_requires_at_least_one_check(tmp_path):
    cases_root = tmp_path / "cases"
    write_case(cases_root, case_id="E-PLAN-01", group="E-PLAN", ground_truth={"ok": True}, checks=[])

    with pytest.raises(CaseError):
        load_cases(root=str(cases_root))
