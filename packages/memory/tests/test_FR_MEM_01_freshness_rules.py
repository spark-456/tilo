"""FR-MEM-01 (PRD 13.1, 13.5): "Memory layers as in 13.1 with freshness rules".
Acceptance: "A 6-day-old web result is reused; an 8-day-old one is refetched".

Result-cache rules from PRD 13.1: keyed by "normalised request plus source fingerprint, with
`origin_cost`"; "Web results fresh for 7 days; files until they change; never cached: email bodies";
every reuse emits `memory.hit` (contracts/events/data/memory.hit.schema.json, EV-09).

The fit check and the Verifier accept everything in this file, so the only thing that can stop a reuse
is freshness (FR-MEM-02 covers their rejections). Public interface: see `_memory_testlib` (BQ-191).

Ambiguities resolved by the PRD's wording (logged BQ-190, BQ-193):
- "fresh for 7 days": age <= 7 days is fresh, age > 7 days is stale (exactly 7 days still reuses).
- "normalised request": leading/trailing whitespace stripped and runs of whitespace collapsed.
- A refetch replaces the entry, so its 7 days start from the refetch.
"""

from __future__ import annotations

from datetime import timedelta

from _memory_testlib import DAY, LOOKUP_COST, ORIGIN_COST, WEB_FRESH_FOR, Fetcher, Rig, assert_valid_memory_hit, web
from tilo_memory.cache import CacheRequest


def test_FR_MEM_01_web_result_6_days_old_is_reused():
    rig = Rig()
    fetch = Fetcher()
    first = rig.get(web(), fetch)  # nothing cached yet: fetched
    assert first.outcome == "miss" and fetch.calls == 1

    rig.clock.advance(6 * DAY)
    second = rig.get(web(), fetch)

    assert second.outcome == "hit", "FR-MEM-01: a 6-day-old web result is reused"
    assert second.reason is None
    assert second.value == "table-v1", "the reused value is the cached one"
    assert fetch.calls == 1, "a reuse must not call the source again"
    assert second.saved == ORIGIN_COST - LOOKUP_COST == 5.5
    assert len(second.events) == 1, "every reuse emits one memory.hit (PRD 13.1)"
    hit = second.events[0]
    assert hit["type"] == "memory.hit"
    assert hit["data"] == {"origin_cost": 6.0, "lookup_cost": 0.5, "saved": 5.5}
    assert hit["seq"] == 101
    assert_valid_memory_hit(hit)


def test_FR_MEM_01_web_result_8_days_old_is_refetched():
    rig = Rig()  # fit check and Verifier accept: only freshness can stop the reuse
    fetch = Fetcher()
    rig.get(web(), fetch)

    rig.clock.advance(8 * DAY)
    second = rig.get(web(), fetch)

    assert second.outcome == "miss", "FR-MEM-01: an 8-day-old web result is not reused"
    assert second.reason == "stale"
    assert fetch.calls == 2, "FR-MEM-01: an 8-day-old web result is refetched"
    assert second.value == "table-v2", "the caller gets the fresh value, not the stale one"
    assert second.saved == 0
    assert second.events == [], "a refetch is not a reuse: no memory.hit, nothing credited"
    assert rig.cache.credits_saved == 0


def test_FR_MEM_01_web_freshness_boundary_is_seven_days():
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(), fetch)

    rig.clock.advance(WEB_FRESH_FOR)  # exactly 7 days: still fresh (BQ-190)
    at_limit = rig.get(web(), fetch)
    assert at_limit.outcome == "hit" and fetch.calls == 1

    rig.clock.advance(timedelta(seconds=1))  # 7 days and 1 second since the fetch: stale
    over = rig.get(web(), fetch)
    assert over.outcome == "miss" and over.reason == "stale" and fetch.calls == 2


def test_FR_MEM_01_a_refetch_restarts_the_freshness_clock():
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(), fetch)
    rig.clock.advance(8 * DAY)
    rig.get(web(), fetch)  # refetched at day 8 -> v2

    rig.clock.advance(3 * DAY)  # day 11 since the first fetch, day 3 since the refetch
    third = rig.get(web(), fetch)

    assert third.outcome == "hit", "the refetched result is fresh for 7 days from the refetch"
    assert third.value == "table-v2"
    assert fetch.calls == 2


def test_FR_MEM_01_files_are_reused_until_they_change():
    rig = Rig()
    fetch = Fetcher(prefix="rows")
    request = CacheRequest(kind="file", text="extract the price table", fingerprint="sha256-file-1")
    rig.get(request, fetch)

    rig.clock.advance(400 * DAY)  # no age limit on files
    unchanged = rig.get(request, fetch)
    assert unchanged.outcome == "hit", "PRD 13.1: files are reused until they change"
    assert unchanged.value == "rows-v1" and fetch.calls == 1
    assert unchanged.events and unchanged.events[0]["type"] == "memory.hit"

    changed = CacheRequest(kind="file", text="extract the price table", fingerprint="sha256-file-2")
    after_change = rig.get(changed, fetch)  # the source fingerprint changed: the old result is not reused
    assert after_change.outcome == "miss"
    assert after_change.value == "rows-v2" and fetch.calls == 2
    assert after_change.events == []


def test_FR_MEM_01_a_different_source_fingerprint_is_a_different_entry():
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(fingerprint="sha256-aaaa"), fetch)

    other = rig.get(web(fingerprint="sha256-bbbb"), fetch)  # same request text, source changed
    assert other.outcome == "miss" and fetch.calls == 2

    back = rig.get(web(fingerprint="sha256-aaaa"), fetch)  # the first entry is still there and fresh
    assert back.outcome == "hit" and back.value == "table-v1" and fetch.calls == 2


def test_FR_MEM_01_requests_are_keyed_after_whitespace_normalisation():
    rig = Rig()
    fetch = Fetcher()
    rig.get(web(text="supplier price table"), fetch)

    messy = rig.get(web(text="  supplier   price\ttable \n"), fetch)

    assert messy.outcome == "hit", "PRD 13.1: keyed by the normalised request"
    assert fetch.calls == 1

    different = rig.get(web(text="supplier price table for steel"), fetch)
    assert different.outcome == "miss" and fetch.calls == 2, "a different request is never a hit"


def test_FR_MEM_01_email_bodies_are_never_cached():
    rig = Rig()
    fetch = Fetcher(prefix="body")
    request = CacheRequest(kind="email_body", text="thread 18c2f body", fingerprint="msg-18c2f")

    first = rig.get(request, fetch)
    second = rig.get(request, fetch)  # immediately again: still not served from the cache

    assert fetch.calls == 2, "PRD 13.1: never cached: email bodies"
    assert first.outcome == "miss" and second.outcome == "miss"
    assert second.reason == "not_cacheable"
    assert second.value == "body-v2"
    assert second.events == [] and rig.cache.credits_saved == 0
    assert rig.fit.calls == [] and rig.verifier.calls == [], "nothing to check: nothing was ever stored"
