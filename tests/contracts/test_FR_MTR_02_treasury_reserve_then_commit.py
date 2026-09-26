"""FR-MTR-02 (PRD 14.1, 14.5; GitHub issue #7, `spark-456/tilo`, ticket CC-SE).

PRD 14.1: "Each step reserves its estimated cost plus 15% before running and commits the actual
cost after. A step that cannot reserve waits." FR-MTR-04's acceptance test is "No run exceeds its
approved budget in a 100-run soak test" -- a property this file checks two ways:

1. Contract: `contracts/metering.schema.json` (issue #7) carries `treasury.reserve_margin` (the
   15% reserve) and `treasury.request_at` (FR-MTR-03's 80% threshold, tested separately in
   `test_FR_MTR_03_...py`), and `config/metering.yaml` ships the PRD's own numbers.
2. Property: the reserve-then-commit rule itself, as PRD 14.1 states it, never lets committed
   spend exceed a cap, however many steps run and whatever their estimates and actual costs are
   (Hypothesis). This is the algorithm the PRD specifies, not `packages/metering`'s `Treasury`
   (not built yet -- P8-01b/c, owned by SE) or any stub in this pass (test-writer commits no
   production code); it is the invariant any future implementation must satisfy.

This is the test-writer split (CLAUDE.md ticket loop): `contracts/metering.schema.json` and
`config/metering.yaml` do not exist yet on this branch, so every schema/config test here must fail
for that reason.
"""

from __future__ import annotations

import re

import pytest
import yaml
from _cc_se_lib import list_cc_se_fixtures, metering_yaml_path, sample_metering_config
from _lib import errors_for, load_json, load_schema
from hypothesis import given
from hypothesis import strategies as st
from test_FR_WLD_02_contracts_check_drift import _copy_runnable_repo, _run_contracts_check

CONTRACTS_PY_SRC = "packages/contracts-py/src"
CONTRACTS_TS_SRC = "packages/contracts-ts/src"


def test_FR_MTR_02_metering_schema_exists(repo_root):
    schema = load_schema(repo_root, "metering")
    assert schema.get("title") == "Metering", (
        f"FR-MTR-02: contracts/metering.schema.json title should be 'Metering', got {schema.get('title')!r}"
    )


def test_FR_MTR_02_minimal_sample_metering_config_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "metering")
    errors = errors_for(schema, sample_metering_config(), registry)
    assert not errors, (
        f"FR-MTR-02: a well-formed metering config should validate, got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("group", ["treasury", "caps", "spend", "reconciliation"])
def test_FR_MTR_02_missing_top_level_group_is_invalid(repo_root, registry, group):
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    del instance[group]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-02: a metering config missing {group!r} must be invalid (issue #7: all keys required)"


def test_FR_MTR_02_additional_top_level_property_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["extra"] = {"anything": 1}
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MTR-02: additionalProperties must be false at the top level (issue #7)"


@pytest.mark.parametrize("value", [0, 1, -0.1, 1.5])
def test_FR_MTR_02_reserve_margin_out_of_open_unit_interval_is_invalid(repo_root, registry, value):
    """Issue #7: 'reserve_margin: number, 0 < x < 1'."""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["treasury"]["reserve_margin"] = value
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-02: treasury.reserve_margin={value} is outside (0, 1) and must be invalid"


def test_FR_MTR_02_reserve_margin_15_percent_is_valid(repo_root, registry):
    """PRD 14.1: 'reserves its estimated cost plus 15%.'"""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["treasury"]["reserve_margin"] = 0.15
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MTR-02: reserve_margin=0.15 should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MTR_02_metering_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_se_fixtures(repo_root, "metering", "valid")
    invalid = list_cc_se_fixtures(repo_root, "metering", "invalid")
    assert valid, "FR-MTR-02: contracts/fixtures/metering/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-MTR-02: contracts/fixtures/metering/invalid/ must contain at least one *.json fixture"


def test_FR_MTR_02_metering_valid_fixtures_pass_the_schema(repo_root, registry):
    fixtures = list_cc_se_fixtures(repo_root, "metering", "valid")
    assert fixtures, "FR-MTR-02: no valid metering fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "metering")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert not errors, (
            f"FR-MTR-02: {path.name} must validate against metering.schema.json, got: {[e.message for e in errors][:3]}"
        )


def test_FR_MTR_02_metering_invalid_fixtures_fail_the_schema(repo_root, registry):
    fixtures = list_cc_se_fixtures(repo_root, "metering", "invalid")
    assert fixtures, "FR-MTR-02: no invalid metering fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "metering")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert errors, (
            f"FR-MTR-02: {path.name} must fail validation against metering.schema.json (name says which rule)"
        )


def test_FR_MTR_02_config_metering_yaml_exists(repo_root):
    path = metering_yaml_path(repo_root)
    assert path.is_file(), "FR-MTR-02: config/metering.yaml must exist (issue #7, PRD 14.1 'from config')"


def test_FR_MTR_02_config_metering_yaml_validates_against_schema(repo_root, registry):
    path = metering_yaml_path(repo_root)
    assert path.is_file(), "FR-MTR-02: see the config-exists test"
    instance = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = load_schema(repo_root, "metering")
    errors = errors_for(schema, instance, registry)
    msgs = [e.message for e in errors][:5]
    assert not errors, f"FR-MTR-02: config/metering.yaml must validate against metering.schema.json, got: {msgs}"


def test_FR_MTR_02_config_metering_yaml_matches_demo_defaults(repo_root):
    """PRD 14.1/17.3 demo defaults, matching packages/metering/tests/data/metering.stub.yaml
    (already merged, ticket P8-01a): 300 run credits, no org cap (BQ-42), $15/$25 daily spend,
    15% reserve margin, 80% budget-request threshold, 10% reconciliation tolerance."""
    path = metering_yaml_path(repo_root)
    assert path.is_file(), "FR-MTR-02: see the config-exists test"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = sample_metering_config()
    assert cfg == expected, f"FR-MTR-02: config/metering.yaml should ship the PRD demo defaults {expected}, got {cfg}"


def test_FR_MTR_02_generated_python_type_exists(repo_root):
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), f"FR-MTR-02: {CONTRACTS_PY_SRC}/ must exist"
    pattern = re.compile(r"\bclass\s+Metering\b")
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in src.rglob("*.py"))
    assert hit, f"FR-MTR-02: no generated Python class 'Metering' found under {CONTRACTS_PY_SRC}/"


def test_FR_MTR_02_generated_typescript_type_exists(repo_root):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"FR-MTR-02: {CONTRACTS_TS_SRC}/ must exist"
    pattern = re.compile(r"\b(?:interface|type)\s+Metering\b")
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in ts_files)
    assert hit, f"FR-MTR-02: no generated TypeScript interface/type 'Metering' found under {CONTRACTS_TS_SRC}/"


@pytest.mark.slow
def test_FR_MTR_02_contracts_check_fails_on_metering_schema_drift(repo_root, tmp_path):
    """Mirrors test_FR_AGT_01_agents_config.py's drift test: once contracts/metering.schema.json
    exists, `just contracts-check` must still fail when it is edited without regenerating."""
    schema_path = repo_root / "contracts" / "metering.schema.json"
    assert schema_path.is_file(), "FR-MTR-02: contracts/metering.schema.json must exist before this runs"

    work_dir = tmp_path / "metering-drift"
    _copy_runnable_repo(repo_root, work_dir)

    import json

    rel = schema_path.relative_to(repo_root)
    mutated_path = work_dir / rel
    schema = json.loads(mutated_path.read_text(encoding="utf-8"))
    schema.setdefault("$defs", {})["drift_marker_field_not_in_generated_output"] = {"type": "string"}
    mutated_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    result = _run_contracts_check(work_dir, repo_root / ".venv")
    msg = f"FR-MTR-02: contracts-check must fail on drift.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, msg


# ---------------------------------------------------------------------------
# Property test: reserve-then-commit never lets committed spend exceed a cap
# (PRD 14.1; FR-MTR-02's acceptance test, "no run exceeds its approved budget
# in a 100-run soak test"). This formalises the PRD's own algorithm, not any
# implementation: a step reserves estimate*(1+margin) before running, waits
# (never runs) if that reservation would not fit in what remains of the cap,
# and its actual cost -- once it does run -- never exceeds its own
# reservation (the point of reserving first).
# ---------------------------------------------------------------------------


def _reserve_then_commit(steps: list[tuple[float, float]], cap: float, reserve_margin: float) -> float:
    reserved_total = 0.0
    committed_total = 0.0
    for estimate, actual_fraction in steps:
        reservation = estimate * (1 + reserve_margin)
        if reserved_total + reservation > cap:
            continue  # PRD 14.1: "A step that cannot reserve waits."
        reserved_total += reservation
        committed_total += actual_fraction * reservation  # actual cost never exceeds its own reservation
    return committed_total


@given(
    steps=st.lists(
        st.tuples(
            st.floats(min_value=0, max_value=1000, allow_nan=False),
            st.floats(min_value=0, max_value=1, allow_nan=False),
        ),
        max_size=100,
    ),
    cap=st.floats(min_value=1, max_value=1000, allow_nan=False),
    reserve_margin=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
)
def test_FR_MTR_02_reserve_then_commit_never_exceeds_the_cap(steps, cap, reserve_margin):
    """A 100-run soak test's invariant, generalised: whatever the estimates and actual costs
    (each within its own reservation), total committed spend never exceeds the cap."""
    committed = _reserve_then_commit(steps, cap, reserve_margin)
    assert committed <= cap + 1e-9, (
        f"FR-MTR-02: committed {committed} exceeded cap {cap} with reserve_margin={reserve_margin} -- "
        "reserve-then-commit must never let a run exceed its approved budget"
    )


def test_FR_MTR_02_reserve_then_commit_example_from_the_prd():
    """A concrete instance of the property above, using the demo defaults (300-credit run cap,
    15% reserve margin): a step estimated at 300 credits reserves 345, which alone exceeds the
    cap, so it must wait -- nothing is committed."""
    committed = _reserve_then_commit([(300.0, 1.0)], cap=300.0, reserve_margin=0.15)
    assert committed == 0.0, "FR-MTR-02: a step whose reservation alone exceeds the cap must wait, not run"
