"""Case schema and loader tests (EFF-07; PRD 19.2). Run: uv run pytest evals/tests -q."""

import json

import jsonschema
import pytest
from conftest import write_case
from tilo_evals import CaseError, load_cases


def test_EFF_07_case_schema_exists_and_is_draft_2020_12(repo_root):
    schema = json.loads((repo_root / "evals" / "case.schema.json").read_text(encoding="utf-8"))
    assert schema.get("$schema", "").endswith("2020-12/schema")
    jsonschema.Draft202012Validator.check_schema(schema)


def _load_one(tmp_path, **kwargs):
    write_case(tmp_path / "cases", **kwargs)
    (case,) = load_cases(root=str(tmp_path / "cases"))
    return case


def _expect_error(tmp_path, needle: str | None, **kwargs) -> None:
    write_case(tmp_path / "cases", **kwargs)
    with pytest.raises(CaseError) as excinfo:
        load_cases(root=str(tmp_path / "cases"))
    if needle:
        assert needle in str(excinfo.value)


def test_EFF_07_load_cases_loads_a_well_formed_case(tmp_path):
    rec = "evals/recordings/E-PLAN-01.jsonl"
    case = _load_one(tmp_path, case_id="E-PLAN-01", group="E-PLAN", ground_truth={"ok": True}, recording=rec)
    assert case.id == "E-PLAN-01" and case.status == "ready"
    assert case.checks == [{"check": "no_side_effects", "args": {}}]


def test_EFF_07_load_cases_allows_null_ground_truth_when_status_is_skeleton(tmp_path):
    case = _load_one(
        tmp_path, case_id="E-PLAN-01", group="E-PLAN", status="skeleton", ground_truth=None, recording=None
    )
    assert case.status == "skeleton" and case.ground_truth is None


def test_EFF_07_load_cases_allows_notes_and_an_autorater_check(tmp_path):
    """P8-08 skeletons carry `notes`; E-RES declares `kind: autorater` checks not looked up in the registry."""
    autorater = {"check": "groundedness", "args": {}, "kind": "autorater"}
    case = _load_one(
        tmp_path,
        case_id="E-RES-01",
        group="E-RES",
        status="skeleton",
        ground_truth=None,
        recording=None,
        notes="needs a groundedness autorater",
        checks=[{"check": "no_side_effects", "args": {}}, autorater],
    )
    assert case.notes == "needs a groundedness autorater" and case.checks[1] == autorater


@pytest.mark.parametrize(
    "needle,kwargs",
    [
        ("not-a-valid-id", dict(case_id="not-a-valid-id", group="E-PLAN", filename="not-a-valid-id.yaml")),
        ("E-PLAN-01", dict(case_id="E-PLAN-01", group="E-RES")),  # dir/group agree, id's own prefix doesn't
        ("E-PLAN-01", dict(case_id="E-PLAN-01", group="E-PLAN", filename="E-PLAN-02.yaml")),
        ("nope", dict(case_id="E-PLAN-01", group="E-PLAN", checks=[{"check": "nope", "args": {}}])),
        (None, dict(case_id="E-PLAN-01", group="E-PLAN", status="ready", ground_truth=None)),
        (None, dict(case_id="E-PLAN-01", group="E-PLAN", checks=[])),
        (None, dict(case_id="E-PLAN-01", group="E-PLAN", recording="evals/../../etc/passwd")),
        (None, dict(case_id="E-PLAN-01", group="E-PLAN", recording="C:/Windows/x.jsonl")),
        (None, dict(case_id="E-PLAN-01", group="E-PLAN", recording="/etc/x.jsonl")),
        (None, dict(case_id="E-PLAN-01", group="E-PLAN", recording="x\n../../../etc/passwd")),
        (None, dict(case_id="E-PLAN-01", group="E-PLAN", measures=["nope"])),
    ],
    ids="bad-id group-diff name-diff bad-check need-truth need-check rec-up rec-drive rec-abs rec-nl measure".split(),
)
def test_EFF_07_load_cases_rejects_malformed_cases(tmp_path, needle, kwargs):
    _expect_error(tmp_path, needle, ground_truth=kwargs.pop("ground_truth", {"ok": True}), **kwargs)


def test_EFF_07_load_cases_rejects_a_duplicate_id(tmp_path):
    """Both copies match filename and dir (one nested under E-PLAN), so only the duplicate check fires."""
    write_case(tmp_path / "cases", case_id="E-PLAN-01", group="E-PLAN", ground_truth={})
    write_case(
        tmp_path / "cases", case_id="E-PLAN-01", group="E-PLAN", ground_truth={}, filename="dup/E-PLAN/E-PLAN-01.yaml"
    )
    with pytest.raises(CaseError) as excinfo:
        load_cases(root=str(tmp_path / "cases"))
    assert "E-PLAN-01" in str(excinfo.value)
