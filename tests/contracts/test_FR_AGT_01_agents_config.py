"""FR-AGT-01 (PRD 8.1, 8.6; GitHub issue #3, `spark-456/tilo`, ticket CC-SH).

PRD 8.6: "Roles and limits as in 8.1, set from config | Changing `max_specialists` to 3 caps
concurrency at 3 in a load test." Issue #3: "The harness needs its role limits and timings in
config, not in code... `config/` is S0's." Proposed `contracts/agents.schema.json` shape and
`config/agents.yaml` defaults, verbatim from the issue:

    limits: directors_per_world (const 1), leads_per_district (const 1),
            max_specialists (1..6), max_depth (const 3)
    context: compact_at (0.60), handoff_at (0.70); rule 0 < compact_at < handoff_at < 1 (D-08,
             FR-AGT-09, PRD 8.5 "At 60% of context the agent compacts... at 70% it hands off")
    liveness: heartbeat_s (15, FR-AGT-10, PRD 8.5), silent_after_s (90, PRD 8.5 sweeper)
    retries: max_attempts (3, FR-AGT-13, PRD 8.3 "a unit fails 3 times")
    questions: hourly_cap_per_person (6, PRD 8.3 load control)

All fields required, `additionalProperties: false` (issue #3).

This is the test-writer split (CLAUDE.md ticket loop): `contracts/agents.schema.json` and
`config/agents.yaml` do not exist yet on this branch, so every test here must fail for that
reason -- see `_cc_sh_lib.py`'s module docstring for why `CC_SH_SCHEMA_NAMES` is not folded
into `_lib.SCHEMA_NAMES`.
"""

from __future__ import annotations

import re

import pytest
import yaml
from _cc_sh_lib import agents_yaml_path, list_cc_sh_fixtures, sample_agents_config
from _lib import errors_for, load_json, load_schema
from test_FR_WLD_02_contracts_check_drift import _copy_runnable_repo, _run_contracts_check

CONTRACTS_PY_SRC = "packages/contracts-py/src"
CONTRACTS_TS_SRC = "packages/contracts-ts/src"


def test_FR_AGT_01_agents_schema_exists(repo_root):
    schema = load_schema(repo_root, "agents")
    assert schema.get("title") == "AgentsConfig", (
        f"FR-AGT-01: contracts/agents.schema.json title should be 'AgentsConfig', got {schema.get('title')!r}"
    )


def test_FR_AGT_01_minimal_sample_agents_config_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-01: a well-formed agents config should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("group", ["limits", "context", "liveness", "retries", "questions"])
def test_FR_AGT_01_missing_top_level_group_is_invalid(repo_root, registry, group):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    del instance[group]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-AGT-01: an agents config missing {group!r} must be invalid (issue #3: all fields required)"


def test_FR_AGT_01_additional_top_level_property_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["extra_group"] = {"anything": 1}
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-01: additionalProperties must be false at the top level (issue #3)"


def test_FR_AGT_01_directors_per_world_is_const_1(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["limits"]["directors_per_world"] = 2
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-01: limits.directors_per_world must be const 1 (PRD 8.1)"


def test_FR_AGT_01_leads_per_district_is_const_1(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["limits"]["leads_per_district"] = 2
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-01: limits.leads_per_district must be const 1 (PRD 8.1)"


def test_FR_AGT_01_max_depth_is_const_3(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["limits"]["max_depth"] = 4
    errors = errors_for(schema, instance, registry)
    assert errors, (
        "FR-AGT-01: limits.max_depth must be const 3 (PRD 8.1 'Hierarchy depth is capped at three agent levels')"
    )


@pytest.mark.parametrize("value", [1, 6])
def test_FR_AGT_01_max_specialists_in_range_is_valid(repo_root, registry, value):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["limits"]["max_specialists"] = value
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-01: max_specialists={value} is within 1..6 and should validate"


@pytest.mark.parametrize("value", [0, 7, 3.5])
def test_FR_AGT_01_max_specialists_out_of_range_is_invalid(repo_root, registry, value):
    """PRD 8.1: '<= 6 concurrent per world'. The acceptance test names 3 as a legal value too,
    so the closed range is 1..6 integers."""
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["limits"]["max_specialists"] = value
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-AGT-01: max_specialists={value!r} is outside 1..6 and must be invalid"


def test_FR_AGT_01_max_specialists_3_is_valid(repo_root, registry):
    """The acceptance test's exact number (PRD 8.6): 'Changing max_specialists to 3 caps
    concurrency at 3 in a load test' -- the config value itself must be a legal setting."""
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["limits"]["max_specialists"] = 3
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-01: max_specialists=3 should validate, got: {[e.message for e in errors][:5]}"


def test_FR_AGT_01_context_thresholds_ordered_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["context"] = {"compact_at": 0.60, "handoff_at": 0.70}
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-AGT-01: compact_at=0.60 < handoff_at=0.70 should validate, got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize(
    "compact_at,handoff_at",
    [(0.70, 0.60), (0.60, 0.60), (0.0, 0.70), (0.60, 1.0)],
)
def test_FR_AGT_01_context_thresholds_out_of_order_is_invalid(repo_root, registry, compact_at, handoff_at):
    """Issue #3's stated rule: '0 < compact_at < handoff_at < 1'."""
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["context"] = {"compact_at": compact_at, "handoff_at": handoff_at}
    errors = errors_for(schema, instance, registry)
    assert errors, (
        f"FR-AGT-01: context {{compact_at: {compact_at}, handoff_at: {handoff_at}}} breaks "
        "'0 < compact_at < handoff_at < 1' and must be invalid"
    )


def test_FR_AGT_01_heartbeat_and_sweeper_are_positive_integers(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    for field, bad in (("heartbeat_s", -1), ("silent_after_s", 0)):
        instance = sample_agents_config()
        instance["liveness"][field] = bad
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-AGT-01: liveness.{field}={bad} must be invalid (PRD 8.5)"


def test_FR_AGT_01_retries_max_attempts_must_be_positive(repo_root, registry):
    schema = load_schema(repo_root, "agents")
    instance = sample_agents_config()
    instance["retries"]["max_attempts"] = 0
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-01: retries.max_attempts=0 must be invalid (FR-AGT-13 'Retries up to 3')"


def test_FR_AGT_01_agents_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_sh_fixtures(repo_root, "agents", "valid")
    invalid = list_cc_sh_fixtures(repo_root, "agents", "invalid")
    assert valid, "FR-AGT-01: contracts/fixtures/agents/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-AGT-01: contracts/fixtures/agents/invalid/ must contain at least one *.json fixture"


def test_FR_AGT_01_agents_valid_fixtures_pass_the_schema(repo_root, registry):
    fixtures = list_cc_sh_fixtures(repo_root, "agents", "valid")
    assert fixtures, "FR-AGT-01: no valid agents fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "agents")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert not errors, (
            f"FR-AGT-01: {path.name} must validate against agents.schema.json, got: {[e.message for e in errors][:3]}"
        )


def test_FR_AGT_01_agents_invalid_fixtures_fail_the_schema(repo_root, registry):
    fixtures = list_cc_sh_fixtures(repo_root, "agents", "invalid")
    assert fixtures, "FR-AGT-01: no invalid agents fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "agents")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert errors, f"FR-AGT-01: {path.name} must fail validation against agents.schema.json (name says which rule)"


def test_FR_AGT_01_config_agents_yaml_exists(repo_root):
    path = agents_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-01: config/agents.yaml must exist (issue #3, PRD 8.1 'set from config')"


def test_FR_AGT_01_config_agents_yaml_validates_against_schema(repo_root, registry):
    path = agents_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-01: see the config-exists test"
    instance = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = load_schema(repo_root, "agents")
    errors = errors_for(schema, instance, registry)
    msgs = [e.message for e in errors][:5]
    assert not errors, f"FR-AGT-01: config/agents.yaml must validate against agents.schema.json, got: {msgs}"


def test_FR_AGT_01_config_agents_yaml_matches_issue_3_defaults(repo_root):
    """Issue #3's proposed file, field for field: max_specialists 6, compact_at 0.60,
    handoff_at 0.70, heartbeat_s 15, silent_after_s 90, max_attempts 3, hourly_cap_per_person 6."""
    path = agents_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-01: see the config-exists test"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = sample_agents_config()
    assert cfg == expected, f"FR-AGT-01: config/agents.yaml should ship issue #3's defaults {expected}, got {cfg}"


def test_FR_AGT_01_generated_python_type_exists(repo_root):
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), f"FR-AGT-01: {CONTRACTS_PY_SRC}/ must exist"
    pattern = re.compile(r"\bclass\s+AgentsConfig\b")
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in src.rglob("*.py"))
    assert hit, f"FR-AGT-01: no generated Python class 'AgentsConfig' found under {CONTRACTS_PY_SRC}/"


def test_FR_AGT_01_generated_typescript_type_exists(repo_root):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"FR-AGT-01: {CONTRACTS_TS_SRC}/ must exist"
    pattern = re.compile(r"\b(?:interface|type)\s+AgentsConfig\b")
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in ts_files)
    assert hit, f"FR-AGT-01: no generated TypeScript interface/type 'AgentsConfig' found under {CONTRACTS_TS_SRC}/"


@pytest.mark.slow
def test_FR_AGT_01_contracts_check_fails_on_agents_schema_drift(repo_root, tmp_path):
    """Mirrors test_FR_WLD_03_generated_types_cover_events.py's event-data drift test: once
    contracts/agents.schema.json exists, `just contracts-check` must still fail when it is
    edited without regenerating."""
    schema_path = repo_root / "contracts" / "agents.schema.json"
    assert schema_path.is_file(), "FR-AGT-01: contracts/agents.schema.json must exist before this runs"

    work_dir = tmp_path / "agents-drift"
    _copy_runnable_repo(repo_root, work_dir)

    import json

    rel = schema_path.relative_to(repo_root)
    mutated_path = work_dir / rel
    schema = json.loads(mutated_path.read_text(encoding="utf-8"))
    schema.setdefault("$defs", {})["drift_marker_field_not_in_generated_output"] = {"type": "string"}
    mutated_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    result = _run_contracts_check(work_dir, repo_root / ".venv")
    msg = f"FR-AGT-01: contracts-check must fail on drift.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, msg
