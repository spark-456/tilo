"""Case schema and loader tests (EFF-07; PRD 19.2). Run: uv run pytest evals/tests -q."""

import json

import jsonschema
import pytest
import yaml
from conftest import REPO_ROOT, write_case
from tilo_evals import CaseError, EvalsConfig, EvalsConfigError, load_cases


def test_EFF_07_case_schema_exists_and_is_draft_2020_12():
    schema = json.loads((REPO_ROOT / "evals" / "case.schema.json").read_text(encoding="utf-8"))
    assert schema.get("$schema", "").endswith("2020-12/schema")
    jsonschema.Draft202012Validator.check_schema(schema)


def _load_one(tmp_path, **kwargs):
    write_case(tmp_path / "cases", **kwargs)
    (case,) = load_cases(root=str(tmp_path / "cases"))
    return case


def test_EFF_07_load_cases_loads_a_well_formed_case(tmp_path):
    rec = "evals/recordings/E-PLAN-01.jsonl"
    case = _load_one(tmp_path, case_id="E-PLAN-01", group="E-PLAN", ground_truth={"ok": True}, recording=rec)
    assert case.id == "E-PLAN-01" and case.status == "ready"
    assert case.checks == [{"check": "no_side_effects", "args": {}}]


def test_EFF_07_load_cases_allows_a_skeleton_with_null_truth_notes_and_an_autorater_check(tmp_path):
    """P8-08 skeletons carry `notes`; E-RES declares `kind: autorater` checks not looked up in the registry."""
    checks = [{"check": "no_side_effects", "args": {}}, {"check": "groundedness", "args": {}, "kind": "autorater"}]
    case = _load_one(tmp_path, case_id="E-RES-01", group="E-RES", status="skeleton", notes="n", checks=checks)
    assert case.ground_truth is None and case.notes == "n" and case.checks == checks


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
    write_case(tmp_path / "cases", ground_truth=kwargs.pop("ground_truth", {"ok": True}), **kwargs)
    with pytest.raises(CaseError, match=needle):
        load_cases(root=str(tmp_path / "cases"))


def test_EFF_07_load_cases_rejects_a_duplicate_id(tmp_path):
    """Both copies match filename and dir (one nested under E-PLAN), so only the duplicate check fires."""
    for name in ("E-PLAN-01.yaml", "dup/E-PLAN/E-PLAN-01.yaml"):
        write_case(tmp_path / "cases", case_id="E-PLAN-01", group="E-PLAN", ground_truth={}, filename=name)
    with pytest.raises(CaseError, match="duplicate case id 'E-PLAN-01'"):
        load_cases(root=str(tmp_path / "cases"))


_DEEP = b"[" * 5000 + b"]" * 5000  # nesting past the recursion limit


@pytest.mark.parametrize(
    "name,data",
    [("x.yaml", b"id: [unclosed"), ("x.yaml", b"\xff\xfe id: x"), ("E-PLAN-01.yml", b""), ("x.yaml", _DEEP)],
    ids="unclosed utf8 yml deep".split(),
)
def test_EFF_07_load_cases_raises_case_error_naming_an_unreadable_or_yml_file(tmp_path, name, data):
    path = write_case(tmp_path / "cases", case_id="E-PLAN-01", group="E-PLAN", ground_truth={}, filename=name)
    path.write_bytes(data or path.read_bytes())
    with pytest.raises(CaseError, match=name.replace(".", "[.]")):
        load_cases(root=str(tmp_path / "cases"))


_CONFIG = {"credit_cap": {"full": 2000}, "deploy_gate_repeats": 3, "cost_regression_threshold": 0.2, "groups": {}}
_PATCHES = "cost_regression_threshold: a|cost_regression_threshold: ~|credit_cap: {a: -5}|deploy_gate_repeats: -3|"
_PATCHES += "groups: x|deploy_gate_repeats: 0|groups: {a: true}|credit_cap: {a: 1.5}"
_BAD = [b"groups: [unclosed", b"\xff\xfe groups: {}", b"groups: " + _DEEP, {"deploy_gate_repeats": 10**400}]
_BAD += [{"cost_regression_threshold": float("inf")}, {"cost_regression_threshold": float("nan")}]


@pytest.mark.parametrize(
    "bad", [None, *_BAD, *(yaml.safe_load("{" + p + "}") for p in _PATCHES.split("|"))], ids=lambda b: repr(b)[:40]
)
def test_EFF_07_evals_config_loads_an_explicit_path_and_rejects_bad_files_and_values(tmp_path, bad):
    body = bad if isinstance(bad, bytes) else yaml.safe_dump({**_CONFIG, **(bad or {})}).encode("utf-8")
    (path := tmp_path / "evals.yaml").write_bytes(body)
    if bad is None:
        assert EvalsConfig.load(str(path)) == EvalsConfig(**_CONFIG)
    else:  # names the file and, for a bad value, the key
        key = "" if isinstance(bad, bytes) else next(iter(bad))
        with pytest.raises(EvalsConfigError, match=f"evals[.]yaml(?s:.*){key}"):
            EvalsConfig.load(str(path))
