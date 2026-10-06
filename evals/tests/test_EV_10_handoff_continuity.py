"""EV-10 handoff continuity (PRD 3.5 EV-10: forced context handoffs that finish with no rework, >= 95%).

Two sources: agent.context_handoff_completed events (share with data.verification_passed true) and runs whose
`measures` include EV-10 (share with passed true). The row value is the case-pass share when such runs exist, else
the event share. The note says which, with the pinned phrases "from case passes" and "from handoff events"."""

import pytest
from _metrics_lib import compute, handoff, only, rec, rows_for


def _hand(passed, *events):
    return rec(*events, passed=passed, case_id="E-HAND-01", group="E-HAND", measures=("EV-10",))


def test_EV_10_value_is_the_case_pass_share_when_ev10_runs_exist():
    runs = [
        _hand(True, handoff(True)),
        _hand(True, handoff(True)),
        _hand(True, handoff(True)),
        _hand(False, handoff(True)),
    ]

    row = only(compute(runs), "EV-10", "recorded")

    assert row.status == "computed"
    assert (row.n, row.of) == (3, 4)
    assert row.value == pytest.approx(0.75), "the case-pass share, not the (all true) event share"
    assert "from case passes" in row.note
    assert "95%" in row.target
    assert row.method.strip()


def test_EV_10_without_ev10_runs_the_value_is_the_share_of_verified_handoff_events():
    runs = [rec(handoff(True), handoff(True)), rec(handoff(False))]

    row = only(compute(runs), "EV-10", "recorded")

    assert (row.n, row.of) == (2, 3)
    assert row.value == pytest.approx(2 / 3)
    assert "from handoff events" in row.note


def test_EV_10_a_pending_ev10_run_is_not_a_success_and_not_in_the_denominator():
    row = only(compute([_hand(True), _hand(None)]), "EV-10", "recorded")

    assert (row.n, row.of) == (1, 1)


def test_EV_10_no_handoff_events_and_no_ev10_runs_is_no_data():
    rows = rows_for(compute([rec(), rec(passed=False)]), "EV-10")

    assert [(r.status, r.value, r.basis, r.n) for r in rows] == [("no_data", None, None, 0)]


def test_EV_10_scripted_fakes_events_are_labelled_mechanics_only_and_kept_apart():
    runs = [rec(handoff(True)), rec(handoff(False), basis="scripted_fakes")]

    rows = rows_for(compute(runs), "EV-10")

    assert [(r.basis, r.n, r.of) for r in rows] == [("recorded", 1, 1), ("scripted_fakes", 0, 1)]
    assert rows[1].note.startswith("mechanics only")
