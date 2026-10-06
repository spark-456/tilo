"""Property tests for FR-INT-06 (distinctness is a pure deterministic function of the 5
dimensions, PG-08) and FR-INT-07 (the estimate is exact linear arithmetic over plan units), per
the test-writer brief ("property tests for invariants: ... deterministic reducer").
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_planning.estimate import UnitCost, estimate_units

settings.register_profile("fr_int", deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
settings.load_profile("fr_int")

_DIM_KEYS = ("depth", "sources", "parallelism", "verification", "output_format")
_depth = st.sampled_from(["overview", "standard", "deep"])
_sources = st.integers(min_value=0, max_value=100)
_parallelism = st.integers(min_value=1, max_value=6)
_verification = st.sampled_from(["basic", "standard", "thorough"])
_output_format = st.sampled_from(["pdf", "pptx", "docx", "email", "in_app"])

_dimensions = st.fixed_dictionaries(
    {
        "depth": _depth,
        "sources": _sources,
        "parallelism": _parallelism,
        "verification": _verification,
        "output_format": _output_format,
    }
)


def _approach(dims: dict) -> dict:
    return {
        "id": "x",
        "label": "X",
        "summary": "x",
        "dimensions": dims,
        "time": {"min_s": 0, "max_s": 1},
        "credits": {"min": 0, "max": 1},
        "risks": [],
        "skips": [],
    }


@given(a=_dimensions, b=_dimensions)
@settings(max_examples=100)
def test_FR_INT_06_check_distinct_matches_the_pg08_differing_dimension_count(a, b):
    from tilo_planning.approaches import check_distinct  # noqa: PLC0415 (module may not exist yet)

    differing = sum(1 for key in _DIM_KEYS if a[key] != b[key])

    assert check_distinct([_approach(a), _approach(b)]) is (differing >= 2)


_unit_cost = st.builds(
    UnitCost,
    # Integers, not floats: repeated addition of the same historical cost must equal the
    # count-weighted product exactly (PRD 7.1's "plan units x historical cost"), with no
    # floating-point rounding slack to hide a wrong reducer.
    credits_min=st.integers(min_value=0, max_value=1000),
    credits_max=st.integers(min_value=0, max_value=1000),
    time_min_s=st.integers(min_value=0, max_value=10_000),
    time_max_s=st.integers(min_value=0, max_value=10_000),
)


@given(a=_unit_cost, b=_unit_cost, n_a=st.integers(min_value=0, max_value=5), n_b=st.integers(min_value=0, max_value=5))
@settings(max_examples=50)
def test_FR_INT_07_estimate_is_exact_linear_sum_of_historical_unit_costs(a, n_a, b, n_b):
    """FR-INT-07: "estimates come from plan units x historical cost per unit type" -- the total is
    always exactly the count-weighted sum of each type's historical cost, never an approximation."""
    units = [
        {
            "id": f"U{i}",
            "unit_type": "type_a" if i < n_a else "type_b",
            "title": "u",
            "role": "specialist",
            "district": "D1",
            "skills": [],
            "connectors": [],
            "actions": [],
            "depends_on": [],
        }
        for i in range(n_a + n_b)
    ]
    history = {"type_a": a, "type_b": b}

    estimate = estimate_units(units, history=history)

    assert estimate["credits"]["min"] == n_a * a.credits_min + n_b * b.credits_min
    assert estimate["credits"]["max"] == n_a * a.credits_max + n_b * b.credits_max
    assert estimate["time"]["min_s"] == n_a * a.time_min_s + n_b * b.time_min_s
    assert estimate["time"]["max_s"] == n_a * a.time_max_s + n_b * b.time_max_s
