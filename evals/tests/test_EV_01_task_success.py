"""EV-01 task success (PRD 3.5 EV-01; 19.3 counts first): among runs that were expected to complete and whose
checks are decided, the share that passed. A run whose only checks are autoraters (passed None) is pending: it is
left out of the denominator and counted in the note, never as a success."""

import re

import pytest
from _metrics_lib import compute, only, rec, rows_for
from hypothesis import given, settings
from hypothesis import strategies as st


def test_EV_01_task_success_is_the_share_of_decided_runs_that_passed_counts_first():
    rows = compute([rec(passed=p) for p in (True, True, True, False)])

    row = only(rows, "EV-01", "recorded")

    assert row.status == "computed"
    assert (row.n, row.of) == (3, 4), "counts first: 3 of 4"
    assert row.value == pytest.approx(0.75)
    assert "85%" in row.target and "60%" in row.target, "the PRD target text: >= 85% seeded, >= 60% open"
    assert row.method.strip()


def test_EV_01_runs_not_expected_to_complete_are_left_out_of_the_denominator():
    runs = [rec(passed=True), rec(passed=True)]
    runs += [rec(passed=False, expected_completed=False) for _ in range(3)]  # a refusal that was right to stop

    row = only(compute(runs), "EV-01", "recorded")

    assert (row.n, row.of) == (2, 2)
    assert row.value == pytest.approx(1.0)


def test_EV_01_pending_autorater_runs_are_excluded_and_counted_in_the_note_never_as_success():
    runs = [rec(passed=True), rec(passed=None), rec(passed=None)]

    row = only(compute(runs), "EV-01", "recorded")

    assert (row.n, row.of) == (1, 1), "pending runs are not in the denominator"
    assert row.value == pytest.approx(1.0)
    assert "2 pending" in row.note, "the note says how many runs are still pending an autorater"


def test_EV_01_a_pass_rate_of_zero_is_a_number_with_its_counts_not_missing_data():
    row = only(compute([rec(passed=False), rec(passed=False)]), "EV-01", "recorded")

    assert row.status == "computed" and row.value == 0.0
    assert (row.n, row.of) == (0, 2)


def test_EV_01_only_pending_runs_never_produce_a_success_figure_or_crash():
    rows = compute([rec(passed=None), rec(passed=None)])

    for row in rows_for(rows, "EV-01"):
        assert row.value is None or row.n == 0, "a pending run is never counted as a success"
        assert row.of == 0 or row.value is not None


def test_EV_01_recorded_and_scripted_fakes_are_separate_rows_recorded_first_never_pooled():
    runs = [rec(passed=True), rec(passed=False)]
    runs += [rec(passed=True, basis="scripted_fakes", measures=("EV-01",)) for _ in range(3)]

    rows = rows_for(compute(runs), "EV-01")

    assert [r.basis for r in rows] == ["recorded", "scripted_fakes"]
    assert [(r.n, r.of) for r in rows] == [(1, 2), (3, 3)]
    assert not rows[0].note.startswith("mechanics only")
    assert rows[1].note.startswith("mechanics only"), "a fake-run figure is labelled mechanics only"


def test_EV_01_no_runs_gives_exactly_one_no_data_row_without_a_number():
    rows = rows_for(compute([]), "EV-01")

    assert len(rows) == 1
    row = rows[0]
    assert (row.status, row.basis, row.value, row.n) == ("no_data", None, None, 0)


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(st.sampled_from([True, False, None]), st.booleans(), st.sampled_from(["recorded", "scripted_fakes"])),
        max_size=25,
    )
)
def test_EV_01_property_value_is_passed_over_decided_and_pending_is_never_a_success(specs):
    runs = [rec(passed=p, expected_completed=e, basis=b) for p, e, b in specs]
    rows = rows_for(compute(runs), "EV-01")

    for basis in ("recorded", "scripted_fakes"):
        decided = [p for p, e, b in specs if b == basis and e and p is not None]
        row = next((r for r in rows if r.basis == basis), None)
        if not decided:
            assert row is None or row.value is None
            continue
        assert row is not None and row.status == "computed"
        assert (row.n, row.of) == (sum(decided), len(decided))
        assert row.value == pytest.approx(sum(decided) / len(decided))
        pending = sum(1 for p, e, b in specs if b == basis and e and p is None)
        if pending:
            assert re.search(rf"\b{pending} pending\b", row.note)
