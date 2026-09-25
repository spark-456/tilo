"""EFF-07 (PRD 6.6, 17.3, 19.2; GitHub issue #8, `spark-456/tilo`, ticket CC-SE).

PRD 6.6: "Lean evals. Full passes run each case once; only deploy-gate cases run three times;
passes stop at a credit cap in `config/evals.yaml`." EFF-07's acceptance test: "A pass hitting the
cap stops and reports partial results." PRD 19.2: "A full pass runs every case once, and
deploy-gate cases three times" over an eval set of eight groups (heading "170 cases", rows 160; BQ-67). This needs
`contracts/evals.schema.json` (issue #8) and `config/evals.yaml`, which
`evals/src/tilo_evals/config.py`'s `EvalsConfig` (already merged, ticket P8-06a) currently loads
from a local stub with the same shape.

Test-writer split: neither the schema nor the config file exists yet on this branch, so every test
below must fail for that reason. The credit-cap *stop* behaviour itself (a pass halting at the cap)
is `evals/`'s runner, not built yet (P8-06 part c) and not this ticket's contract scope; this file
covers the cap values the runner will read.
"""

from __future__ import annotations

import pytest
import yaml
from _cc_se_lib import PRD_19_2_GROUPS, evals_yaml_path, list_cc_se_fixtures, sample_evals_config
from _lib import errors_for, load_json, load_schema


def test_EFF_07_evals_schema_exists(repo_root):
    schema = load_schema(repo_root, "evals")
    assert schema.get("title") == "Evals", (
        f"EFF-07: contracts/evals.schema.json title should be 'Evals', got {schema.get('title')!r}"
    )


def test_EFF_07_minimal_sample_evals_config_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "evals")
    errors = errors_for(schema, sample_evals_config(), registry)
    assert not errors, f"EFF-07: a well-formed evals config should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("group", ["credit_cap", "deploy_gate_repeats", "cost_regression_threshold", "groups"])
def test_EFF_07_missing_top_level_key_is_invalid(repo_root, registry, group):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    del instance[group]
    errors = errors_for(schema, instance, registry)
    assert errors, f"EFF-07: an evals config missing {group!r} must be invalid (issue #8: all keys required)"


def test_EFF_07_additional_top_level_property_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    instance["extra"] = 1
    errors = errors_for(schema, instance, registry)
    assert errors, "EFF-07: additionalProperties must be false at the top level (issue #8)"


@pytest.mark.parametrize("tier", ["full", "smoke", "gate"])
def test_EFF_07_credit_cap_has_the_three_pass_tiers(repo_root, registry, tier):
    """BQ-43 (decided by the orchestrator): full 2,000, smoke 200, gate 1,000 credits."""
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    del instance["credit_cap"][tier]
    errors = errors_for(schema, instance, registry)
    assert errors, f"EFF-07: credit_cap missing {tier!r} must be invalid (issue #8)"


@pytest.mark.parametrize("tier", ["full", "smoke", "gate"])
def test_EFF_07_credit_cap_values_must_be_positive(repo_root, registry, tier):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    instance["credit_cap"][tier] = 0
    errors = errors_for(schema, instance, registry)
    assert errors, f"EFF-07: credit_cap.{tier}=0 must be invalid (issue #8: number > 0)"


def test_EFF_07_deploy_gate_repeats_is_3(repo_root, registry):
    """PRD 19.2: 'deploy-gate cases three times.'"""
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    instance["deploy_gate_repeats"] = 3
    errors = errors_for(schema, instance, registry)
    assert not errors, f"EFF-07: deploy_gate_repeats=3 should validate, got: {[e.message for e in errors][:5]}"


def test_EFF_07_deploy_gate_repeats_must_be_at_least_1(repo_root, registry):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    instance["deploy_gate_repeats"] = 0
    errors = errors_for(schema, instance, registry)
    assert errors, "EFF-07: deploy_gate_repeats=0 must be invalid (issue #8: integer >= 1)"


@pytest.mark.parametrize("group,count", list(PRD_19_2_GROUPS.items()))
def test_EFF_07_groups_matches_prd_19_2_case_counts(repo_root, registry, group, count):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    assert instance["groups"][group] == count
    instance["groups"][group] = count + 1  # any group's count drifting from the PRD table is wrong
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"EFF-07: groups.{group} is a config value the harness checks the case set against (issue #8), "
        f"not a schema const -- {count + 1} should still validate, got: {[e.message for e in errors][:5]}"
    )


def test_EFF_07_groups_requires_exactly_the_eight_prd_19_2_groups(repo_root, registry):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    del instance["groups"]["E-RED"]
    errors = errors_for(schema, instance, registry)
    assert errors, "EFF-07: groups missing a PRD 19.2 group (E-RED) must be invalid"


def test_EFF_07_prd_19_2_group_table_sums_to_160():
    """PRD 19.2's heading says 'Eval set (170 cases)', but its eight rows sum to 160
    (10+10+6+50+30+20+20+14). The per-group counts are what the harness checks the case set
    against, so the rows win until the user answers BQ-67 (docs/open-questions.md)."""
    assert sum(PRD_19_2_GROUPS.values()) == 160, "EFF-07: the PRD 19.2 group rows must sum to 160 cases (BQ-67)"


def test_EFF_07_evals_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_se_fixtures(repo_root, "evals", "valid")
    invalid = list_cc_se_fixtures(repo_root, "evals", "invalid")
    assert valid, "EFF-07: contracts/fixtures/evals/valid/ must contain at least one *.json fixture"
    assert invalid, "EFF-07: contracts/fixtures/evals/invalid/ must contain at least one *.json fixture"


def test_EFF_07_evals_valid_fixtures_pass_the_schema(repo_root, registry):
    fixtures = list_cc_se_fixtures(repo_root, "evals", "valid")
    assert fixtures, "EFF-07: no valid evals fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "evals")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert not errors, (
            f"EFF-07: {path.name} must validate against evals.schema.json, got: {[e.message for e in errors][:3]}"
        )


def test_EFF_07_evals_invalid_fixtures_fail_the_schema(repo_root, registry):
    fixtures = list_cc_se_fixtures(repo_root, "evals", "invalid")
    assert fixtures, "EFF-07: no invalid evals fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "evals")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert errors, f"EFF-07: {path.name} must fail validation against evals.schema.json (name says which rule)"


def test_EFF_07_config_evals_yaml_exists(repo_root):
    path = evals_yaml_path(repo_root)
    assert path.is_file(), "EFF-07: config/evals.yaml must exist (issue #8, PRD 6.6)"


def test_EFF_07_config_evals_yaml_validates_against_schema(repo_root, registry):
    path = evals_yaml_path(repo_root)
    assert path.is_file(), "EFF-07: see the config-exists test"
    instance = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = load_schema(repo_root, "evals")
    errors = errors_for(schema, instance, registry)
    msgs = [e.message for e in errors][:5]
    assert not errors, f"EFF-07: config/evals.yaml must validate against evals.schema.json, got: {msgs}"


def test_EFF_07_config_evals_yaml_matches_bq_43_and_prd_19_2(repo_root):
    """BQ-43's decided credit caps, PRD 19.2's deploy-gate repeats and group counts, EFF-06's 20%
    regression threshold -- matching `evals/src/tilo_evals/config.py`'s local stub shape (already
    merged, ticket P8-06a), which this schema is meant to validate `config/evals.yaml` against
    once it exists (see that module's `EvalsConfig.load`)."""
    path = evals_yaml_path(repo_root)
    assert path.is_file(), "EFF-07: see the config-exists test"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = sample_evals_config()
    assert cfg == expected, f"EFF-07: config/evals.yaml should ship {expected}, got {cfg}"
