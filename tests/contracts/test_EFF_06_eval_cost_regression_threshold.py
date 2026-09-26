"""EFF-06 (PRD 6.6; GitHub issue #8, `spark-456/tilo`, ticket CC-SE).

PRD 6.6: "Cost per task and per role tracked; a regression over 20% fails the nightly job."
EFF-06's acceptance test: "Seeded regression fails the job." This needs
`contracts/evals.schema.json`'s `cost_regression_threshold` (issue #8) plus the regression rule
itself, tested as a property (PRD 6.6's own formula -- see `test_FR_MTR_02_...py`'s module
docstring for why a pure PRD-specified function, not an implementation, is what a contracts
test-writer pass can check).

Test-writer split: contracts/evals.schema.json does not exist yet, so the schema tests below must
fail for that reason.
"""

from __future__ import annotations

import pytest
from _cc_se_lib import sample_evals_config
from _lib import errors_for, load_schema
from hypothesis import given
from hypothesis import strategies as st


def test_EFF_06_cost_regression_threshold_is_20_percent(repo_root, registry):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    instance["cost_regression_threshold"] = 0.20
    errors = errors_for(schema, instance, registry)
    assert not errors, f"EFF-06: cost_regression_threshold=0.20 should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("value", [0, 1, -0.1])
def test_EFF_06_cost_regression_threshold_out_of_open_unit_interval_is_invalid(repo_root, registry, value):
    schema = load_schema(repo_root, "evals")
    instance = sample_evals_config()
    instance["cost_regression_threshold"] = value
    errors = errors_for(schema, instance, registry)
    assert errors, f"EFF-06: cost_regression_threshold={value} is outside (0, 1) and must be invalid (issue #8)"


# ---------------------------------------------------------------------------
# Property: PRD 6.6's regression rule -- a cost increase over the threshold
# fails the nightly job, one within it does not.
# ---------------------------------------------------------------------------


def _regression_fails(baseline_cost: float, new_cost: float, threshold: float) -> bool:
    if baseline_cost <= 0:
        return new_cost > 0  # no baseline to compare against: any new cost is a regression
    return (new_cost - baseline_cost) / baseline_cost > threshold


def test_EFF_06_seeded_25_percent_regression_fails_the_nightly_job():
    """EFF-06's own acceptance test: a nightly job whose per-task cost rose 25% over yesterday's
    baseline, against config/evals.yaml's 20% threshold."""
    threshold = sample_evals_config()["cost_regression_threshold"]
    assert _regression_fails(baseline_cost=10.0, new_cost=12.5, threshold=threshold), (
        "EFF-06: a seeded 25% cost regression must fail the nightly job"
    )


def test_EFF_06_regression_within_threshold_does_not_fail():
    threshold = sample_evals_config()["cost_regression_threshold"]
    assert not _regression_fails(baseline_cost=10.0, new_cost=11.5, threshold=threshold), (
        "EFF-06: a 15% cost change must not fail the nightly job against a 20% threshold"
    )


@given(
    baseline_cost=st.floats(min_value=0.01, max_value=100_000, allow_nan=False),
    relative_change=st.floats(min_value=-0.9, max_value=0.9, allow_nan=False).filter(
        lambda d: abs(d - 0.20) > 1e-6  # avoid float round-trip noise right at the 20% boundary
    ),
)
def test_EFF_06_regression_fails_iff_over_threshold(baseline_cost, relative_change):
    threshold = 0.20
    new_cost = baseline_cost * (1 + relative_change)
    expected = relative_change > threshold
    assert _regression_fails(baseline_cost, new_cost, threshold) == expected, (
        f"EFF-06: relative change {relative_change:.3f} vs threshold {threshold} disagreed with the expected outcome"
    )
