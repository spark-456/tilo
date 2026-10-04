"""Property tests for the result cache (FR-MEM-01 freshness, FR-MEM-02 fit check plus Verifier, PRD 13.1,
14.3, EV-09). Invariants over many ages and decisions, using only the public interface in
`_memory_testlib` (BQ-191). Costs are multiples of 0.25 so credit arithmetic is exact in binary floating
point and `saved == origin_cost - lookup_cost` can be asserted with `==`."""

from __future__ import annotations

from datetime import timedelta

from _memory_testlib import WEB_FRESH_FOR, Fetcher, Rig, assert_valid_memory_hit, web
from hypothesis import given, settings
from hypothesis import strategies as st

quarter = st.integers(min_value=0, max_value=400).map(lambda n: n / 4)


@settings(deadline=None, max_examples=60)
@given(age_seconds=st.integers(min_value=0, max_value=30 * 86400))
def test_FR_MEM_01_property_web_result_is_reused_iff_at_most_seven_days_old(age_seconds):
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(), fetch)
    rig.clock.advance(timedelta(seconds=age_seconds))

    result = rig.get(web(), fetch)

    fresh = timedelta(seconds=age_seconds) <= WEB_FRESH_FOR
    assert (result.outcome == "hit") is fresh
    assert fetch.calls == (1 if fresh else 2), "refetched exactly when stale"


@settings(deadline=None, max_examples=80)
@given(
    age_seconds=st.integers(min_value=0, max_value=14 * 86400),
    fit=st.booleans(),
    verify=st.booleans(),
    origin_cost=quarter,
    lookup_cost=quarter,
)
def test_FR_MEM_02_property_reuse_needs_freshness_fit_check_and_verifier(
    age_seconds, fit, verify, origin_cost, lookup_cost
):
    if lookup_cost > origin_cost:  # a result cheaper to fetch than to look up is not a case the PRD prices
        origin_cost, lookup_cost = lookup_cost, origin_cost
    rig = Rig(lookup_cost=lookup_cost)
    fetch = Fetcher(origin_cost=origin_cost)
    rig.get(web(), fetch)
    rig.clock.advance(timedelta(seconds=age_seconds))
    rig.fit.accept, rig.verifier.accept = fit, verify

    result = rig.get(web(), fetch)

    expect_hit = timedelta(seconds=age_seconds) <= WEB_FRESH_FOR and fit and verify
    assert (result.outcome == "hit") is expect_hit
    if expect_hit:
        (event,) = result.events
        assert event["data"] == {
            "origin_cost": origin_cost,
            "lookup_cost": lookup_cost,
            "saved": origin_cost - lookup_cost,  # EV-09
        }
        assert result.saved == origin_cost - lookup_cost == rig.cache.credits_saved
        assert_valid_memory_hit(event)
    else:
        assert result.events == [] and result.saved == 0 and rig.cache.credits_saved == 0
        assert any(r.outcome == "miss" for r in rig.cache.log)


@settings(deadline=None, max_examples=40)
@given(
    steps=st.lists(
        st.tuples(st.integers(min_value=0, max_value=10 * 86400), st.booleans(), st.booleans()),
        min_size=1,
        max_size=12,
    )
)
def test_FR_MEM_02_property_credits_saved_equals_the_sum_of_memory_hit_events(steps):
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(), fetch)
    results = []
    last_total = 0.0
    for advance_seconds, fit, verify in steps:
        rig.clock.advance(timedelta(seconds=advance_seconds))
        rig.fit.accept, rig.verifier.accept = fit, verify
        results.append(rig.get(web(), fetch))
        assert rig.cache.credits_saved >= last_total >= 0, "credits saved never go down or below zero"
        last_total = rig.cache.credits_saved

    events = [e for r in results for e in r.events]
    assert all(e["type"] == "memory.hit" for e in events)
    assert rig.cache.credits_saved == sum(e["data"]["saved"] for e in events)
    assert sum(1 for r in results if r.outcome == "hit") == len(events), "one memory.hit per reuse, none per miss"
    assert sum(1 for r in rig.cache.log if r.outcome == "miss") >= sum(1 for r in results if r.outcome == "miss")
