"""FR-MTR-06: "Credits-saved method". Acceptance: "Saved credits equal origin cost minus lookup in every
`memory.hit`" (PRD 14.5). Method (PRD 14.3): "When Tilo reuses a result, we credit what that result actually cost the
first time, minus the cost of the lookup." Saved = `origin_cost` - lookup cost, counted only when the fit check and
Verifier accept the reuse; estimates of what another approach might have cost are never counted. Also event rule EV-09
(`contracts/event.rules.md`), meter rule MT-05 (`credits_saved` is the sum over accepted reuses) and
`contracts/events/data/memory.hit.schema.json`.

`tilo_metering.savings` does not exist yet, so these fail at import (API_FR_MEM_03_09.md). Fixtures come from
`contracts/fixtures/events/`; no network, no provider.
"""

from __future__ import annotations

import copy
import json
import math

import pytest
from _metering_testlib import REPO_ROOT
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering.savings import InconsistentMemoryHit, credits_saved, hit_saving

settings.register_profile("savings", deadline=None)
settings.load_profile("savings")

FIXTURES = REPO_ROOT / "contracts" / "fixtures" / "events"


def load(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def hit(n: int, origin: float, lookup: float, *, run: str = "r_village_basic_1", saved: float | None = None) -> dict:
    event = copy.deepcopy(load("valid/memory.hit.json"))
    event["id"] = f"01JB5VQ{n:019d}"
    event["seq"] = n
    event["run_id"] = run
    event["data"] = {"origin_cost": origin, "lookup_cost": lookup, "saved": origin - lookup if saved is None else saved}
    return event


def test_FR_MTR_06_a_memory_hit_saves_origin_cost_minus_lookup_cost():
    event = load("valid/memory.hit.json")  # origin 6, lookup 0.5
    assert hit_saving(event) == 5.5
    assert event["data"]["saved"] == hit_saving(event)


def test_FR_MTR_06_credits_saved_is_the_sum_of_origin_minus_lookup_over_every_hit():
    events = [hit(1, 6, 0.5), hit(2, 10, 1), hit(3, 2.5, 2.5)]  # the last one saved nothing
    assert math.isclose(credits_saved(events), 5.5 + 9 + 0, abs_tol=1e-9)


def test_FR_MTR_06_no_hits_means_zero_saved():
    assert credits_saved([]) == 0
    assert credits_saved(iter([])) == 0


def test_FR_MTR_06_only_memory_hit_events_count():
    """Every registered type, hit included: the total is the one hit's saving, whatever other events carry."""
    stream = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((FIXTURES / "valid").glob("*.json"))]
    assert sum(1 for e in stream if e["type"] == "memory.hit") == 1
    assert math.isclose(credits_saved(stream), 5.5, abs_tol=1e-9)


def test_FR_MTR_06_a_saved_field_on_another_event_type_is_never_counted():
    """14.3: estimates of what another approach might have cost are never counted. A `saved` on a non-hit is one."""
    fake = hit(1, 100, 1)
    fake["type"] = "memory.saved"
    fake["data"] = {"layer": "result_cache", "item_count": 3, "saved": 99}
    assert credits_saved([fake, hit(2, 6, 0.5)]) == 5.5


def test_FR_MTR_06_a_hit_whose_saved_is_not_origin_minus_lookup_is_refused_not_summed():
    """The invalid fixture ev09 (saved 6, origin 6, lookup 0.5). BQ-197: raise, naming the event id."""
    bad = load("registry/invalid/ev09_memory_hit_saved_not_origin_minus_lookup.json")
    with pytest.raises(InconsistentMemoryHit) as excinfo:
        hit_saving(bad)
    assert bad["id"] in str(excinfo.value)
    with pytest.raises(InconsistentMemoryHit):
        credits_saved([hit(1, 6, 0.5), bad])


def test_FR_MTR_06_inconsistent_hit_error_is_a_value_error():
    assert issubclass(InconsistentMemoryHit, ValueError)


def test_FR_MTR_06_a_hit_that_cost_more_than_it_saved_is_refused():
    """Schema: credits are >= 0, so saved cannot be negative; a lookup dearer than the origin is not a saving."""
    with pytest.raises(ValueError):
        hit_saving(hit(1, 1, 3))  # saved = -2
    with pytest.raises(ValueError):
        hit_saving(hit(1, 1, 3, saved=0))  # the stored field hides the negative: still not origin - lookup


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "6", None])
def test_FR_MTR_06_costs_must_be_finite_non_negative_numbers(bad):
    event = hit(1, 6, 0.5)
    event["data"]["origin_cost"] = bad
    with pytest.raises(ValueError):
        hit_saving(event)
    event = hit(1, 6, 0.5)
    event["data"]["lookup_cost"] = bad
    with pytest.raises(ValueError):
        hit_saving(event)


@pytest.mark.parametrize("missing", ["origin_cost", "lookup_cost", "saved"])
def test_FR_MTR_06_a_hit_missing_a_cost_field_is_refused(missing):
    event = hit(1, 6, 0.5)
    del event["data"][missing]
    with pytest.raises(ValueError):
        hit_saving(event)


def test_FR_MTR_06_the_same_event_id_counts_once():
    """Replayed events (a duplicate delivery) must not double a saving (FR-MEM-03)."""
    event = hit(1, 6, 0.5)
    assert credits_saved([event, copy.deepcopy(event), event]) == 5.5


def test_FR_MTR_06_saved_can_be_taken_for_one_run():
    events = [hit(1, 6, 0.5, run="r_one"), hit(2, 10, 1, run="r_two"), hit(3, 4, 1, run="r_one")]
    assert math.isclose(credits_saved(events, run_id="r_one"), 5.5 + 3, abs_tol=1e-9)
    assert math.isclose(credits_saved(events, run_id="r_two"), 9, abs_tol=1e-9)
    assert credits_saved(events, run_id="r_none") == 0
    assert math.isclose(credits_saved(events), 5.5 + 9 + 3, abs_tol=1e-9)


def test_FR_MTR_06_credits_saved_does_not_change_the_events_it_reads():
    events = [hit(1, 6, 0.5), hit(2, 10, 1)]
    before = copy.deepcopy(events)
    credits_saved(events)
    assert events == before


costs = st.tuples(
    st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
).map(lambda t: (max(t[0], t[1]), t[1]))  # origin >= lookup


@given(pairs=st.lists(costs, max_size=30))
def test_FR_MTR_06_property_total_is_the_sum_of_origin_minus_lookup(pairs):
    events = [hit(i + 1, o, l_) for i, (o, l_) in enumerate(pairs)]
    expected = math.fsum(o - l_ for o, l_ in pairs)
    assert math.isclose(credits_saved(events), expected, rel_tol=1e-9, abs_tol=1e-6)


@given(pairs=st.lists(costs, min_size=1, max_size=20), seed=st.randoms())
def test_FR_MTR_06_property_total_does_not_depend_on_event_order(pairs, seed):
    events = [hit(i + 1, o, l_) for i, (o, l_) in enumerate(pairs)]
    shuffled = list(events)
    seed.shuffle(shuffled)
    assert math.isclose(credits_saved(events), credits_saved(shuffled), rel_tol=1e-9, abs_tol=1e-6)


@given(pairs=st.lists(costs, max_size=15), extra=costs)
def test_FR_MTR_06_property_an_accepted_hit_never_lowers_the_total(pairs, extra):
    events = [hit(i + 1, o, l_) for i, (o, l_) in enumerate(pairs)]
    more = [*events, hit(999, *extra)]
    assert credits_saved(more) >= credits_saved(events) - 1e-6
