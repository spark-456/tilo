"""EV-03 estimate accuracy (PRD 3.5 EV-03: actual / estimated credits, median within +-25%).

Per run with a world.planned (data.credits = {min, max}) and a world.completed (data.credits_used):
ratio = credits_used / ((min + max) / 2). The value is the median ratio; the note says how many runs landed
inside [min, max]. A zero midpoint is skipped, never divided."""

import math

import pytest
from _metrics_lib import completed, compute, only, planned, rec, rows_for
from hypothesis import given, settings
from hypothesis import strategies as st


def test_EV_03_value_is_the_median_of_used_over_the_estimate_midpoint():
    runs = [
        rec(planned(8, 12), completed(9)),  # ratio 0.9, inside
        rec(planned(8, 12), completed(10)),  # ratio 1.0, inside
        rec(planned(8, 12), completed(15)),  # ratio 1.5, outside the range
    ]

    row = only(compute(runs), "EV-03", "recorded")

    assert row.status == "computed"
    assert row.value == pytest.approx(1.0)
    assert row.n == 3
    assert "±25%" in row.target, "target text: median within +-25%"
    assert "2 of 3" in row.note and "inside" in row.note, "the note says how many runs landed inside [min, max]"
    assert row.method.strip()


def test_EV_03_an_even_number_of_runs_takes_the_mean_of_the_two_middle_ratios():
    runs = [rec(planned(10, 10), completed(8)), rec(planned(10, 10), completed(12))]

    assert only(compute(runs), "EV-03", "recorded").value == pytest.approx(1.0)


def test_EV_03_a_zero_midpoint_is_skipped_and_never_divided():
    runs = [rec(planned(0, 0), completed(0)), rec(planned(0, 0), completed(3)), rec(planned(10, 10), completed(12))]

    row = only(compute(runs), "EV-03", "recorded")  # must not raise ZeroDivisionError

    assert row.value == pytest.approx(1.2)
    assert row.n == 1, "only the run with a usable midpoint is counted"


def test_EV_03_only_zero_midpoints_leave_no_data_and_no_number():
    rows = rows_for(compute([rec(planned(0, 0), completed(0))]), "EV-03")

    assert [(r.status, r.value, r.basis) for r in rows] == [("no_data", None, None)]


def test_EV_03_runs_missing_the_plan_or_the_completion_are_left_out():
    runs = [rec(planned(10, 10)), rec(completed(10)), rec(planned(10, 10), completed(10))]

    row = only(compute(runs), "EV-03", "recorded")

    assert row.n == 1 and row.value == pytest.approx(1.0)


def test_EV_03_bank_runs_without_a_plan_event_give_no_data_not_a_made_up_ratio():
    rows = rows_for(compute([rec(completed(3.52), basis="scripted_fakes", measures=("EV-01",))]), "EV-03")

    assert [(r.status, r.value) for r in rows] == [("no_data", None)]


@settings(max_examples=80, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(0, 500),
            st.integers(0, 500),
            st.floats(0, 5000, allow_nan=False),
        ),
        min_size=1,
        max_size=15,
    )
)
def test_EV_03_property_never_raises_and_the_median_lies_between_the_extreme_ratios(specs):
    runs = [rec(planned(min(a, b), max(a, b)), completed(used)) for a, b, used in specs]

    rows = rows_for(compute(runs), "EV-03")

    ratios = [used / ((min(a, b) + max(a, b)) / 2) for a, b, used in specs if (a + b) > 0]
    if not ratios:
        assert [r.status for r in rows] == ["no_data"]
        return
    row = only(rows, "EV-03", "recorded")
    assert row.n == len(ratios)
    assert min(ratios) - 1e-9 <= row.value <= max(ratios) + 1e-9
    assert math.isfinite(row.value)
