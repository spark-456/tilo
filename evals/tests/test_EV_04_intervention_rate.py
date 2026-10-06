"""EV-04 intervention rate (PRD 3.5 EV-04: unplanned needs-you cards per run, <= 2 per Town-tier run).

Unplanned = events of type agent.blocked, budget.requested or agent.escalated. Planned approval.requested gates do
not count. Tier comes from world.planned data.tier. The value is the mean per run for the Town tier when Town runs
exist, else the mean over all runs; the note lists the per-tier mean and max."""

import pytest
from _metrics_lib import (
    alert_raised,
    approval_requested,
    blocked,
    budget_requested,
    compute,
    escalated,
    only,
    planned,
    rec,
    rows_for,
)
from hypothesis import given, settings
from hypothesis import strategies as st


def _town(*events):
    return rec(planned(5, 9, "town"), *events)


def test_EV_04_value_is_the_town_tier_mean_of_unplanned_cards_per_run():
    runs = [
        _town(blocked(), budget_requested(), escalated(), approval_requested(), approval_requested()),  # 3
        _town(blocked()),  # 1
        rec(planned(1, 2, "village"), *[blocked(f"U{i}") for i in range(5)]),  # 5, another tier
    ]

    row = only(compute(runs), "EV-04", "recorded")

    assert row.status == "computed"
    assert row.value == pytest.approx(2.0), "the Town mean (3 + 1) / 2, not the all-run mean 3.0"
    assert row.n == 2, "n is the number of Town runs the value averages"
    note = row.note.lower()
    assert "town" in note and "village" in note, "the note lists each tier"
    assert "mean" in note and "max" in note, "per-tier mean and max"
    assert "2" in row.target and "Town" in row.target, "target text: <= 2 per Town-tier run"
    assert row.method.strip()


def test_EV_04_planned_approval_gates_and_alerts_are_not_unplanned_needs_you_cards():
    run = _town(*[approval_requested() for _ in range(4)], alert_raised())

    row = only(compute([run]), "EV-04", "recorded")

    assert row.status == "computed" and row.value == 0.0 and row.n == 1


def test_EV_04_without_town_runs_the_value_is_the_mean_over_all_runs():
    runs = [
        rec(planned(1, 2, "village"), *[blocked(f"U{i}") for i in range(5)]),
        rec(planned(1, 2, "outpost"), blocked()),
    ]

    row = only(compute(runs), "EV-04", "recorded")

    assert row.value == pytest.approx(3.0)
    assert row.n == 2


def test_EV_04_a_run_without_a_plan_event_counts_in_the_all_run_mean():
    row = only(compute([rec(blocked(), escalated()), rec()]), "EV-04", "recorded")

    assert row.value == pytest.approx(1.0) and row.n == 2


def test_EV_04_recorded_and_scripted_fakes_stay_separate():
    runs = [_town(blocked()), rec(planned(5, 9, "town"), *[blocked(f"U{i}") for i in range(4)], basis="scripted_fakes")]

    rows = rows_for(compute(runs), "EV-04")

    assert [(r.basis, r.value) for r in rows] == [
        ("recorded", pytest.approx(1.0)),
        ("scripted_fakes", pytest.approx(4.0)),
    ]
    assert rows[1].note.startswith("mechanics only")


def test_EV_04_no_runs_is_no_data():
    assert [(r.status, r.value) for r in rows_for(compute([]), "EV-04")] == [("no_data", None)]


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["town", "village", "outpost", "city"]),
            st.integers(0, 4),
            st.integers(0, 4),
            st.integers(0, 4),
            st.integers(0, 4),
        ),
        min_size=1,
        max_size=12,
    )
)
def test_EV_04_property_value_is_the_mean_of_unplanned_cards_over_town_runs_else_all_runs(specs):
    runs, counts, town_counts = [], [], []
    for tier, nb, nr, ne, na in specs:
        events = [planned(1, 2, tier)] + [blocked(f"U{i}") for i in range(nb)] + [budget_requested() for _ in range(nr)]
        events += [escalated() for _ in range(ne)] + [approval_requested() for _ in range(na)]
        runs.append(rec(*events))
        counts.append(nb + nr + ne)
        if tier == "town":
            town_counts.append(nb + nr + ne)

    row = only(compute(runs), "EV-04", "recorded")

    chosen = town_counts or counts
    assert row.value == pytest.approx(sum(chosen) / len(chosen))
    assert row.n == len(chosen)
