"""EV-08 memory reuse (PRD 3.5 EV-08: credits saved / first-run credits on repeat runs, >= 50%).

From memory.hit events: sum(saved) / sum(origin_cost). The saved sum is tilo_metering.savings.credits_saved, so an
inconsistent hit raises InconsistentMemoryHit and the metric must not swallow it (PRD 14.3, FR-MTR-06)."""

import pytest
from _metrics_lib import compute, memory_hit, only, rec, rows_for
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering.savings import InconsistentMemoryHit


def test_EV_08_value_is_credits_saved_over_first_run_credits():
    runs = [rec(memory_hit(10, 1)), rec(memory_hit(10, 2))]  # saved 9 + 8 = 17 of 20

    row = only(compute(runs), "EV-08", "recorded")

    assert row.status == "computed"
    assert row.value == pytest.approx(0.85)
    assert row.n == 2, "n is the number of memory hits behind the figure"
    assert "50%" in row.target
    assert row.method.strip()


def test_EV_08_a_hit_seen_twice_by_event_id_is_counted_once_in_both_sums():
    first, second = memory_hit(10, 1), memory_hit(20, 0)  # 9 + 20 saved of 30
    runs = [rec(first, second), rec(first)]  # the same event again, in another run's list

    row = only(compute(runs), "EV-08", "recorded")

    assert row.value == pytest.approx(29 / 30), "origin_cost is de-duplicated the same way credits_saved is"
    assert row.n == 2


def test_EV_08_an_inconsistent_hit_raises_and_is_not_swallowed():
    bad = memory_hit(10, 3, saved=9)  # saved should be 7

    with pytest.raises(InconsistentMemoryHit):
        compute([rec(bad)])


def test_EV_08_a_lookup_dearer_than_the_origin_raises_too():
    with pytest.raises(InconsistentMemoryHit):
        compute([rec(memory_hit(5, 9, saved=0))])


def test_EV_08_no_memory_hit_is_no_data_and_no_number():
    rows = rows_for(compute([rec(), rec()]), "EV-08")

    assert [(r.status, r.value, r.basis, r.n) for r in rows] == [("no_data", None, None, 0)]


def test_EV_08_hits_that_cost_nothing_to_originate_give_no_ratio_not_a_division():
    rows = rows_for(compute([rec(memory_hit(0, 0))]), "EV-08")

    assert all(r.value is None for r in rows)


def test_EV_08_scripted_fakes_hits_are_labelled_mechanics_only():
    rows = rows_for(compute([rec(memory_hit(10, 5), basis="scripted_fakes")]), "EV-08")

    assert [(r.basis, r.value) for r in rows] == [("scripted_fakes", pytest.approx(0.5))]
    assert rows[0].note.startswith("mechanics only")


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(1, 1000), st.integers(0, 1000)), min_size=1, max_size=15))
def test_EV_08_property_consistent_hits_give_a_share_between_zero_and_one(pairs):
    hits = [memory_hit(float(origin), float(min(lookup, origin))) for origin, lookup in pairs]

    row = only(compute([rec(*hits)]), "EV-08", "recorded")

    saved = sum(origin - min(lookup, origin) for origin, lookup in pairs)
    assert 0.0 <= row.value <= 1.0
    assert row.value == pytest.approx(saved / sum(origin for origin, _ in pairs))
