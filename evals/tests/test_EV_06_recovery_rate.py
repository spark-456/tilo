"""EV-06 recovery rate (PRD 3.5 EV-06: failed steps recovered without escalation, >= 70%).

Failed steps are the distinct (run, unit) pairs named by data.unit in agent.blocked or agent.recovered events. A
step recovered without escalation has an agent.recovered and no agent.blocked for the same unit in that run. No
failed steps is no_data, and the method says the chaos suite (10% tool failures) is what produces them."""

import pytest
from _metrics_lib import blocked, compute, only, rec, recovered, rows_for


def test_EV_06_share_of_failed_steps_recovered_without_escalation_counts_first():
    run = rec(
        recovered("U1"),  # recovered, never blocked: counts as recovered
        blocked("U2"),  # failed, never recovered
        blocked("U3"),
        recovered("U3"),  # blocked first: it was escalated, so not "without escalation"
    )

    row = only(compute([run]), "EV-06", "recorded")

    assert row.status == "computed"
    assert (row.n, row.of) == (1, 3), "1 of 3 failed steps recovered without escalation"
    assert row.value == pytest.approx(1 / 3)
    assert "70%" in row.target
    assert row.method.strip()


def test_EV_06_the_same_unit_id_in_two_runs_is_two_failed_steps():
    runs = [rec(recovered("U1")), rec(blocked("U1"))]

    row = only(compute(runs), "EV-06", "recorded")

    assert (row.n, row.of) == (1, 2)


def test_EV_06_a_unit_is_counted_once_however_many_events_name_it():
    run = rec(recovered("U1", 1), recovered("U1", 2), recovered("U1", 3), blocked("U2"), blocked("U2"))

    row = only(compute([run]), "EV-06", "recorded")

    assert (row.n, row.of) == (1, 2)


def test_EV_06_no_failed_steps_is_no_data_and_the_method_names_the_chaos_suite():
    rows = rows_for(compute([rec(), rec()]), "EV-06")

    assert len(rows) == 1
    row = rows[0]
    assert (row.status, row.value, row.basis, row.n) == ("no_data", None, None, 0)
    method = row.method.lower()
    assert "chaos" in method and "10%" in method, "the method says where failed steps come from"


def test_EV_06_scripted_fakes_failures_are_labelled_mechanics_only_and_kept_apart():
    runs = [rec(recovered("U1")), rec(blocked("U1"), basis="scripted_fakes")]

    rows = rows_for(compute(runs), "EV-06")

    assert [(r.basis, r.n, r.of) for r in rows] == [("recorded", 1, 1), ("scripted_fakes", 0, 1)]
    assert rows[1].note.startswith("mechanics only")
