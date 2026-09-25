"""FR-MTR-04 (PRD 14.1, 14.5, 17.3; GitHub issue #7, `spark-456/tilo`, ticket CC-SE).

PRD 14.1: "Caps. Per run, per user per day, and per org per day, all from config. Demo defaults:
300 credits per public run; US$15 soft and US$25 hard daily model spend on `tilo-demo`, the hard
cap flipping the kill switch." FR-MTR-04's acceptance test: "Exceeding the demo hard cap switches
the link to replay-only." `packages/metering/tests/test_FR_MTR_04_caps_and_kill_switch.py`
(already merged, ticket P8-01a) covers the *value-level* rules (demo defaults, hard >= soft) against
its own local stub; this file covers the *contract* those tests will eventually load instead of the
stub -- `contracts/metering.schema.json`'s `caps` and `spend` groups (issue #7) -- plus BQ-42's
decided per-org cap value, which is new here (the stub predates that decision).

Test-writer split: contracts/metering.schema.json does not exist yet, so every test here must fail
for that reason. `treasury` and `reconciliation` groups are covered by
`test_FR_MTR_02_...py` and `test_FR_MTR_08_...py` respectively, to keep one file per requirement ID.
"""

from __future__ import annotations

import pytest
from _cc_se_lib import sample_metering_config
from _lib import errors_for, load_schema


def test_FR_MTR_04_run_credits_cap_is_300(repo_root, registry):
    """PRD 14.1/17.3: '300 credits per public run.'"""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["caps"]["run_credits"] = 300
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MTR-04: caps.run_credits=300 should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("value", [0, -5, None])
def test_FR_MTR_04_run_credits_cap_must_be_positive(repo_root, registry, value):
    """PRD 14.1 requires a per-run cap from config, so null (no cap) is invalid too."""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["caps"]["run_credits"] = value
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-04: caps.run_credits={value} must be invalid (PRD 14.1: number > 0)"


@pytest.mark.parametrize("value", [0, -5, None])
def test_FR_MTR_04_user_day_cap_must_be_positive(repo_root, registry, value):
    """PRD 14.1 requires a per-user daily cap from config; only the per-org cap may be null
    (BQ-42). Issue #7 asked for null here, but the PRD shape wins (ADR-0002 decision 13)."""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["caps"]["user_day_credits"] = value
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-04: caps.user_day_credits={value} must be invalid (PRD 14.1: number > 0)"


def test_FR_MTR_04_org_day_cap_is_null_per_BQ_42(repo_root, registry):
    """BQ-42 (decided by the orchestrator, docs/open-questions.md): no separate per-org daily
    cap -- `caps.org_day_credits: null`; the US$15/US$25 daily spend caps apply to every org."""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    assert instance["caps"]["org_day_credits"] is None
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MTR-04: BQ-42's org_day_credits=null must validate, got: {[e.message for e in errors][:5]}"


def test_FR_MTR_04_caps_missing_org_day_credits_key_is_invalid(repo_root, registry):
    """The key is required even though BQ-42 sets its value to null (issue #7: 'All keys are
    required')."""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    del instance["caps"]["org_day_credits"]
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MTR-04: caps missing org_day_credits must be invalid even though its value is null"


def test_FR_MTR_04_daily_spend_caps_15_and_25(repo_root, registry):
    """PRD 14.1/17.3: 'US$15 soft and US$25 hard daily model spend.'"""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["spend"] = {"daily_usd_soft": 15, "daily_usd_hard": 25}
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MTR-04: spend $15/$25 should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("field", ["daily_usd_soft", "daily_usd_hard"])
def test_FR_MTR_04_spend_caps_must_be_positive(repo_root, registry, field):
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["spend"][field] = 0
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-04: spend.{field}=0 must be invalid (issue #7: number > 0)"
