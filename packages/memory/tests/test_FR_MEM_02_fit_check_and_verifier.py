"""FR-MEM-02 (PRD 13.1, 13.5, 14.3): "Fit check plus Verifier before reuse".
Acceptance: "A cache hit rejected by the Verifier is logged as a miss and saves nothing".

PRD 13.1: "A cached result is reused only if a fit check (model) and the Verifier accept it; every reuse
emits `memory.hit` and is credited in P8." PRD 14.3: "Saved = origin_cost - lookup cost, counted only when
the fit check and Verifier accept the reuse."

The entry in every test below is well inside its 7 days, so a result that is still found rejected can only
have been stopped by the fit check or the Verifier. Public interface: see `_memory_testlib` (BQ-191).

Ambiguities resolved (BQ-192, BQ-193):
- There is no `memory.miss` type in `contracts/events/registry.yaml` (only `memory.hit`, `memory.saved`).
  "Logged as a miss" is therefore asserted on the cache's own append-only `cache.log` (record with
  `.outcome == "miss"` and a `.reason`), and by the absence of any `memory.hit` event. Not a world event.
- A rejected entry is not served; the source is fetched and the fresh result is stored in its place.
"""

from __future__ import annotations

from _memory_testlib import DAY, LOOKUP_COST, ORIGIN_COST, Fetcher, Rig, assert_valid_memory_hit, web


def _seeded(*, fit: bool = True, verify: bool = True) -> tuple[Rig, Fetcher]:
    """A rig whose cache already holds a 1-day-old web result, with the checks then set to `fit`/`verify`."""
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(), fetch)  # stored at T0
    rig.clock.advance(1 * DAY)
    rig.fit.accept, rig.verifier.accept = fit, verify
    return rig, fetch


def test_FR_MEM_02_reuse_needs_the_fit_check_and_the_verifier_to_accept():
    rig, fetch = _seeded()

    result = rig.get(web(), fetch)

    assert result.outcome == "hit"
    assert fetch.calls == 1
    assert len(rig.fit.calls) == 1, "FR-MEM-02: the fit check runs before a reuse"
    assert len(rig.verifier.calls) == 1, "FR-MEM-02: the Verifier runs before a reuse"
    for seen_request, seen_value in (rig.fit.calls[0], rig.verifier.calls[0]):
        assert seen_request.text == "supplier price table"
        assert seen_value == "table-v1", "both checks judge the cached value that would be reused"
    assert result.saved == ORIGIN_COST - LOOKUP_COST
    assert_valid_memory_hit(result.events[0])


def test_FR_MEM_02_cache_hit_rejected_by_the_verifier_is_logged_as_a_miss_and_saves_nothing():
    rig, fetch = _seeded(verify=False)

    result = rig.get(web(), fetch)

    assert result.outcome == "miss", "FR-MEM-02: a hit the Verifier rejects is a miss"
    assert result.reason == "verifier_rejected"
    assert result.saved == 0, "FR-MEM-02: a rejected reuse saves nothing"
    assert result.events == [], "no memory.hit: nothing is credited in P8 (PRD 13.1, 14.3)"
    assert rig.cache.credits_saved == 0
    assert fetch.calls == 2, "the rejected result is not served: the source is fetched"
    assert result.value == "table-v2", "the caller gets the fresh value, never the rejected one"

    logged = [r for r in rig.cache.log if r.reason == "verifier_rejected"]
    assert len(logged) == 1, "FR-MEM-02: the rejection is logged"
    assert logged[0].outcome == "miss" and logged[0].saved == 0
    assert not any(r.outcome == "hit" for r in rig.cache.log), "the rejected lookup is not logged as a hit"


def test_FR_MEM_02_cache_hit_rejected_by_the_fit_check_is_a_miss_even_if_the_verifier_accepts():
    rig, fetch = _seeded(fit=False, verify=True)

    result = rig.get(web(), fetch)

    assert result.outcome == "miss", "FR-MEM-02: both the fit check and the Verifier must accept"
    assert result.reason == "fit_rejected"
    assert result.saved == 0 and result.events == []
    assert rig.cache.credits_saved == 0
    assert fetch.calls == 2 and result.value == "table-v2"
    assert any(r.outcome == "miss" and r.reason == "fit_rejected" for r in rig.cache.log)


def test_FR_MEM_02_rejection_is_not_sticky_the_fresh_result_replaces_the_rejected_one():
    rig, fetch = _seeded(verify=False)
    rig.get(web(), fetch)  # rejected -> refetched -> v2 stored in its place
    rig.verifier.accept = True

    later = rig.get(web(), fetch)

    assert later.outcome == "hit" and later.value == "table-v2", "the stored result is the fresh one"
    assert fetch.calls == 2, "no third fetch: the replacement is a normal fresh entry"


def test_FR_MEM_02_credits_saved_counts_only_accepted_reuse():
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(), fetch)  # miss: nothing cached yet
    assert rig.cache.credits_saved == 0

    accepted = rig.get(web(), fetch)  # hit: saves 6 - 0.5
    assert rig.cache.credits_saved == 5.5

    rig.verifier.accept = False
    rejected = rig.get(web(), fetch)  # Verifier rejects: nothing added, fresh v2 stored
    assert rejected.outcome == "miss"
    assert rig.cache.credits_saved == 5.5, "FR-MEM-02: a rejected reuse adds nothing to credits saved"

    rig.verifier.accept = True
    again = rig.get(web(), fetch)  # v2 is fresh: hit
    assert again.outcome == "hit"

    events = accepted.events + rejected.events + again.events
    assert [e["type"] for e in events] == ["memory.hit", "memory.hit"]
    assert rig.cache.credits_saved == sum(e["data"]["saved"] for e in events) == 11.0
