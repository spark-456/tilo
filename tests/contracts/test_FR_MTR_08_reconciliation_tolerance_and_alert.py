"""FR-MTR-08 (PRD 14.4, 14.5; GitHub issue #7, `spark-456/tilo`, ticket CC-SE).

PRD 14.4: "Reconciliation. Daily, ledger credits x US$0.005 must match billed model spend in the
billing export within +/-10%; larger drift raises an alert and freezes new claims in the deck
until explained." FR-MTR-08's acceptance test: "A seeded 15% drift raises an alert." This needs
`contracts/metering.schema.json`'s `reconciliation` group (issue #7: `tolerance` and
`billing_services`) plus the reconciliation rule itself, tested as a property (PRD 14.4's own
formula, not any implementation -- see `test_FR_MTR_02_...py`'s module docstring for why).

Test-writer split: contracts/metering.schema.json does not exist yet, so the schema tests below
must fail for that reason.
"""

from __future__ import annotations

import pytest
from _cc_se_lib import sample_metering_config
from _lib import errors_for, load_schema
from hypothesis import given
from hypothesis import strategies as st


def test_FR_MTR_08_tolerance_is_10_percent(repo_root, registry):
    """PRD 14.4: 'within +/-10%.'"""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["reconciliation"]["tolerance"] = 0.10
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-MTR-08: reconciliation.tolerance=0.10 should validate, got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("value", [0, 1, -0.1, 1.2])
def test_FR_MTR_08_tolerance_out_of_open_unit_interval_is_invalid(repo_root, registry, value):
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["reconciliation"]["tolerance"] = value
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-08: reconciliation.tolerance={value} is outside (0, 1) and must be invalid (issue #7)"


def test_FR_MTR_08_billing_services_is_an_array_of_non_empty_strings(repo_root, registry):
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["reconciliation"]["billing_services"] = ["", "vertex-ai-billing-export"]
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MTR-08: reconciliation.billing_services must reject an empty string entry (issue #7)"


def test_FR_MTR_08_billing_services_may_be_empty_by_default(repo_root, registry):
    """The demo default ships an empty list until a billing-export service is named."""
    schema = load_schema(repo_root, "metering")
    instance = sample_metering_config()
    instance["reconciliation"]["billing_services"] = []
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-MTR-08: an empty billing_services list should validate, got: {[e.message for e in errors][:5]}"
    )


# ---------------------------------------------------------------------------
# Property: PRD 14.4's reconciliation rule -- drift beyond tolerance alerts,
# drift within tolerance does not. FR-MTR-08's acceptance test is a single
# seeded case of this general rule.
# ---------------------------------------------------------------------------

CREDIT_USD = 0.005  # contracts/providers.schema.json $defs.prices.credit_usd


def _drift_exceeds_tolerance(ledger_credits: float, billed_usd: float, tolerance: float) -> bool:
    ledger_usd = ledger_credits * CREDIT_USD
    denom = billed_usd if billed_usd != 0 else ledger_usd
    if denom == 0:
        return False  # nothing spent, nothing billed: no drift to report
    drift = abs(ledger_usd - billed_usd) / denom
    return drift > tolerance


def test_FR_MTR_08_seeded_15_percent_drift_raises_an_alert():
    """FR-MTR-08's own acceptance test, literally: ledger says $100 of spend, billing says $115 --
    a 15% drift against the 10% tolerance from config/metering.yaml's demo defaults."""
    tolerance = sample_metering_config()["reconciliation"]["tolerance"]
    ledger_credits = 100 / CREDIT_USD  # $100 of ledger spend, in credits
    billed_usd = 115.0  # 15% over the ledger total
    assert _drift_exceeds_tolerance(ledger_credits, billed_usd, tolerance), (
        "FR-MTR-08: a seeded 15% drift must raise an alert against the 10% tolerance"
    )


def test_FR_MTR_08_drift_within_tolerance_does_not_alert():
    tolerance = sample_metering_config()["reconciliation"]["tolerance"]
    ledger_credits = 100 / CREDIT_USD
    billed_usd = 105.0  # 5% over: within the 10% tolerance
    assert not _drift_exceeds_tolerance(ledger_credits, billed_usd, tolerance), (
        "FR-MTR-08: a 5% drift must not raise an alert against the 10% tolerance"
    )


@given(
    billed_usd=st.floats(min_value=0.01, max_value=100_000, allow_nan=False),
    relative_drift=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False).filter(
        lambda d: abs(abs(d) - 0.10) > 1e-6  # avoid float round-trip noise right at the 10% boundary
    ),
)
def test_FR_MTR_08_alert_iff_drift_exceeds_tolerance(billed_usd, relative_drift):
    """Whatever the billed amount, a ledger total exactly `relative_drift` away from it alerts
    exactly when |relative_drift| is past the 10% tolerance -- the general PRD 14.4 rule
    FR-MTR-08's single seeded case is an instance of."""
    tolerance = 0.10
    ledger_usd = billed_usd * (1 + relative_drift)
    ledger_credits = ledger_usd / CREDIT_USD
    expected = abs(relative_drift) > tolerance
    assert _drift_exceeds_tolerance(ledger_credits, billed_usd, tolerance) == expected, (
        f"FR-MTR-08: drift {relative_drift:.3f} vs tolerance {tolerance} disagreed with the expected alert state"
    )
