"""FR-AGT-14 (PRD 8.6): "A weekly schedule fires on time and reuses memory." PRD 13.1 memory layers: the result cache
keeps a
file result until its fingerprint changes (a hit credits `saved`), artifact memory is offered as a starting point, never
silently reused.

What the schedule owns (design brief rule 6): every firing's `RunStart` names the same result-cache namespace (the
schedule
id, never another schedule's) and chains `prior_world_id` to the world the previous firing started. What the cache
owns is
`tilo_memory.cache.ResultCache`; here the run starter is a fake that, like the real one, asks one ResultCache per
namespace
for the same file on each firing. Two firings 7 days apart: an unchanged fingerprint is a `memory.hit` with saved > 0, a
changed one is a miss. Interface: API_FR_AGT_14.md.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from schedule_support import MON_0330Z, WEEK, Clock, FakeRunStarter, make_rig, make_schedule
from tilo_harness.schedule import RunStart
from tilo_memory.cache import CacheRequest, CacheResult, Fetched, ResultCache

ORIGIN_COST = 6.0
LOOKUP_COST = 0.25


class CachingRunStarter(FakeRunStarter):
    """Starts a run that reads one file through the schedule's result cache."""

    def __init__(self, clock: Any) -> None:
        super().__init__(clock)
        self._clock_fn = clock
        self.caches: dict[str, ResultCache] = {}
        self.fingerprint = "sha256-v1"
        self.lookups: list[tuple[str, str, CacheResult]] = []  # (schedule_id, world_id, result)

    def start(self, run: RunStart) -> str:
        world_id = super().start(run)
        cache = self.caches.setdefault(
            run.cache_namespace,
            ResultCache(
                clock=self._clock_fn,
                fit_check=lambda _r, _v: True,
                verifier=lambda _r, _v: True,
                lookup_cost=LOOKUP_COST,
            ),
        )
        base = {
            "v": "1.0",
            "ts": self._clock_fn().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "world_id": world_id,
            "run_id": f"r_{world_id[2:]}_1",
            "actor": run.owner_user_id,
        }
        result = cache.get_or_fetch(
            CacheRequest(kind="file", text="the weekly supplier sheet", fingerprint=self.fingerprint),
            lambda: Fetched(value="rows", origin_cost=ORIGIN_COST),
            base=base,
            seq=2,
        )
        self.lookups.append((run.schedule_id, world_id, result))
        return world_id


def _rig(*schedules):
    clock = Clock(MON_0330Z)
    starter = CachingRunStarter(clock)
    return make_rig(list(schedules) or [make_schedule()], starter=starter, clock=clock), starter


def test_FR_AGT_14_a_second_firing_a_week_later_reuses_an_unchanged_file_result_and_credits_the_saving():
    rig, starter = _rig()
    rig.ticker.tick()
    rig.clock.advance(WEEK)
    assert rig.ticker.tick().fired == 1
    (_, _, first), (_, _, second) = starter.lookups
    assert (first.outcome, first.reason, first.saved) == ("miss", "absent", 0.0)
    assert second.outcome == "hit"
    assert second.saved == ORIGIN_COST - LOOKUP_COST
    assert second.saved > 0
    assert [e["type"] for e in second.events] == ["memory.hit"]  # the one event that credits the saving
    assert second.events[0]["data"]["saved"] == second.saved


def test_FR_AGT_14_a_changed_fingerprint_is_a_miss_on_the_second_firing():
    rig, starter = _rig()
    rig.ticker.tick()
    starter.fingerprint = "sha256-v2"
    rig.clock.advance(WEEK)
    rig.ticker.tick()
    (_, _, _first), (_, _, second) = starter.lookups
    assert second.outcome == "miss"
    assert second.saved == 0.0
    assert second.events == []
    # and the week after, with that new fingerprint unchanged, hits again
    rig.clock.advance(WEEK)
    rig.ticker.tick()
    assert starter.lookups[2][2].outcome == "hit"


def test_FR_AGT_14_every_firing_of_a_schedule_names_the_same_cache_namespace_and_no_other_schedule_shares_it():
    rig, starter = _rig(make_schedule("sched_a"), make_schedule("sched_b", owner_user_id="u_other"))
    rig.ticker.tick()
    rig.clock.advance(WEEK)
    rig.ticker.tick()
    namespaces = {(r.schedule_id, r.cache_namespace) for r in starter.started}
    assert namespaces == {("sched_a", "sched_a"), ("sched_b", "sched_b")}
    assert len(starter.caches) == 2
    # the same file on the very first firing of each schedule is a miss: nothing leaked across schedules or owners
    first_firings = [res for _sid, _w, res in starter.lookups[:2]]
    assert [r.outcome for r in first_firings] == ["miss", "miss"]
    assert [r.outcome for _s, _w, r in starter.lookups[2:]] == ["hit", "hit"]


def test_FR_AGT_14_the_second_run_start_carries_the_first_firings_world_id_and_the_chain_continues():
    rig, starter = _rig()
    for _ in range(3):
        rig.ticker.tick()
        rig.clock.advance(WEEK)
    first, second, third = starter.started
    # PRD 13.1 artifact memory: offered as a starting point (prior_world_id), never silently reused.
    # The first firing has no earlier firing; the design brief does not say whether it points at the approved brief
    # (see the report), so either is accepted.
    assert first.prior_world_id in (None, first.approved_brief_ref)
    assert second.prior_world_id == starter.world_ids[0]
    assert third.prior_world_id == starter.world_ids[1]


def test_FR_AGT_14_the_run_start_names_the_owner_so_decisions_and_memory_scope_are_the_owners():
    rig, starter = _rig(
        make_schedule("sched_a", owner_user_id="u_owner"), make_schedule("sched_b", owner_user_id="u_other")
    )
    rig.ticker.tick()
    assert {r.schedule_id: r.owner_user_id for r in starter.started} == {"sched_a": "u_owner", "sched_b": "u_other"}


def test_FR_AGT_14_a_firing_a_minute_late_still_chains_to_the_previous_world():
    rig, starter = _rig()
    rig.ticker.tick()
    rig.clock.advance(WEEK + timedelta(minutes=1))
    assert rig.ticker.tick().fired == 1
    assert starter.started[1].prior_world_id == starter.world_ids[0]
