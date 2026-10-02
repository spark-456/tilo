"""Check hardening from the PR #52 reviews (issue #72; EFF-07, PRD 19.2, 19.3, EV-09). A check never passes
because a field was missing, mistyped or never compared. Run: uv run pytest evals/tests -q."""

import json
from pathlib import Path
from typing import Any

import pytest
from tilo_evals import Case, checks
from tilo_evals.checks import CheckResult, Outcome, get, register

_ARGS_RW = {"field": "recipients", "allowlist": ["buyer@acme.example"]}


def _case(ground_truth: dict[str, Any] | None = None) -> Case:
    return Case(
        id="E-PLAN-01",
        group="E-PLAN",
        title="t",
        measures=("EFF-07",),
        status="ready",
        deploy_gate=False,
        inputs={},
        scripted_answers=(),
        ground_truth=ground_truth,
        checks=[],
        recording=None,
        path=Path("evals/cases/E-PLAN/E-PLAN-01.yaml"),
    )


def _run(name: str, args: dict[str, Any], outputs: dict[str, Any], ground_truth: dict[str, Any] | None = None):
    return get(name)(_case(ground_truth), Outcome(events=[], outputs=outputs), args)


@pytest.fixture
def contracts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the checks at a throwaway contracts/ folder and drop the schema caches before and after."""
    root = tmp_path / "contracts"
    root.mkdir()
    monkeypatch.setattr(checks, "_CONTRACTS_DIR", root)
    checks._schema_registry.cache_clear()
    checks._validator.cache_clear()
    yield root
    checks._schema_registry.cache_clear()
    checks._validator.cache_clear()


# ---- recipients_within: a list of strings, never a vacuous pass -----------------------------------


@pytest.mark.parametrize(
    "outputs",
    [{}, {"recipients": None}, {"recipients": "buyer@acme.example"}, {"recipients": {"a": 1}}, {"recipients": [1]}],
    ids=["missing", "null", "string-not-iterated", "object", "non-string-item"],
)
def test_EFF_07_recipients_within_requires_a_list_of_strings(outputs: dict[str, Any]):
    result = _run("recipients_within", _ARGS_RW, outputs)
    assert result.passed is False and result.cause


def test_EFF_07_recipients_within_empty_list_is_within_the_allowlist():
    assert _run("recipients_within", _ARGS_RW, {"recipients": []}).passed is True


def test_EFF_07_recipients_within_missing_field_cause_says_missing():
    assert "missing" in (_run("recipients_within", _ARGS_RW, {}).cause or "")


# ---- schema_valid: field missing, traversal, unreadable schemas -----------------------------------


def test_EFF_07_schema_valid_missing_field_says_field_missing():
    result = _run("schema_valid", {"field": "entry", "schema": "outbox.schema.json"}, {})
    assert result.passed is False
    assert result.cause is not None and "missing" in result.cause and "None is not" not in result.cause


def test_EFF_07_schema_valid_null_field_is_still_validated():
    result = _run("schema_valid", {"field": "entry", "schema": "outbox.schema.json"}, {"entry": None})
    assert result.passed is False and "missing" not in (result.cause or "")


@pytest.mark.parametrize("schema", ["../pyproject.toml", "../evals/case.schema.json", "/etc/passwd"])
def test_EFF_07_schema_valid_refuses_a_path_outside_contracts(schema: str):
    result = _run("schema_valid", {"field": "entry", "schema": schema}, {"entry": {}})
    assert result.passed is False and "outside contracts/" in (result.cause or "")


def test_EFF_07_schema_valid_unknown_schema_fails_with_a_cause():
    result = _run("schema_valid", {"field": "entry", "schema": "no-such.schema.json"}, {"entry": {}})
    assert result.passed is False and "schema unavailable" in (result.cause or "")


@pytest.mark.parametrize("body", [b"{not json", b"[1, 2]", b"\xff\xfe"], ids=["bad-json", "not-an-object", "bad-utf8"])
def test_EFF_07_unreadable_contract_schema_fails_loudly_never_skipped(contracts_dir: Path, body: bytes):
    (contracts_dir / "ok.schema.json").write_text('{"type": "object"}', encoding="utf-8")
    (contracts_dir / "broken.schema.json").write_bytes(body)
    result = _run("schema_valid", {"field": "x", "schema": "ok.schema.json"}, {"x": {}})
    assert result.passed is False and "broken.schema.json" in (result.cause or "")


def test_EFF_07_readable_contract_schemas_still_validate(contracts_dir: Path):
    (contracts_dir / "ok.schema.json").write_text(json.dumps({"type": "object", "required": ["a"]}), encoding="utf-8")
    assert _run("schema_valid", {"field": "x", "schema": "ok.schema.json"}, {"x": {"a": 1}}).passed is True
    assert _run("schema_valid", {"field": "x", "schema": "ok.schema.json"}, {"x": {}}).passed is False


# ---- register: kind restricted to the case schema's enum ------------------------------------------


def test_EFF_07_register_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        register("_bad_kind_check", kind="heuristic")
    assert not checks.is_registered("_bad_kind_check")


@pytest.mark.parametrize("kind", checks.KINDS)
def test_EFF_07_register_accepts_the_schema_kinds(kind: str):
    def fn(case: Any, outcome: Outcome, args: dict[str, Any] | None = None) -> CheckResult:  # noqa: ARG001
        return CheckResult(True)

    assert register(f"_kind_check_{kind}", kind=kind)(fn) is fn


def test_EFF_07_check_kinds_match_the_case_schema_enum():
    schema_path = Path(__file__).resolve().parents[1] / "case.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    kinds = schema["properties"]["checks"]["items"]["properties"]["kind"]["enum"]
    assert set(kinds) == set(checks.KINDS)


# ---- equals_ground_truth: bool is not a number at any depth ---------------------------------------


@pytest.mark.parametrize(
    "truth,value,ok",
    [
        ([1], [True], False),
        ([True], [1], False),
        ({"a": 1}, {"a": True}, False),
        ({"a": [0]}, {"a": [False]}, False),
        ([1, 2], [1, 2], True),
        ({"a": [1, {"b": True}]}, {"a": [1, {"b": True}]}, True),
        ([1, 2], [1], False),
        ([1], {"a": 1}, False),
        ({"a": 1}, {"a": 1, "b": 2}, False),
        ({"a": 1}, {"b": 1}, False),
        ([1], 1, False),
        ([], [], True),
    ],
)
def test_EFF_07_equals_ground_truth_is_type_strict_recursively(truth: Any, value: Any, ok: bool):
    result = _run("equals_ground_truth", {"field": "f"}, {"f": value}, {"f": truth})
    assert result.passed is ok and (ok or result.cause)


def test_EFF_07_equals_ground_truth_tolerance_ignored_for_containers():
    result = _run("equals_ground_truth", {"field": "f", "tolerance": 5}, {"f": [10]}, {"f": [1]})
    assert result.passed is False
