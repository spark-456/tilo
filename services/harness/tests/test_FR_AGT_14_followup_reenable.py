"""FR-AGT-14d item 4 (code-review follow-up): switching a schedule on again moves a stale `next_due`.

A schedule that was paused, or auto-disabled after `MAX_FAILURES`, keeps the `next_due` it had. Re-enabled weeks
later it would fire a catch-up run for a slot long past, at once, unexpectedly. In the store's shared transition
(both stores, the STORE's own clock, never the caller's): `update(enabled=True)` with a `next_due` at or before the
store's now sets it to the first cadence slot STRICTLY after now; a `next_due` still in the future is left alone. The
failure count, the backoff and the error are cleared as before. `enabled=False` and a title-only update never move it.

One suite against the in-memory store (fake clock) always and the Firestore store under `-m emulator` (server time).
Interface: services/api/tests/API_FR_AGT_14d.md. The PATCH route's side is in services/api/tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fr_agt_14_store_support import (
    MON_0330Z,
    WEEK,
    StoreRig,
    firestore_rig,
    make_record,
    make_tick_rig,
    memory_rig,
)
from tilo_harness.schedule import MAX_FIRES_PER_TICK, next_slot
from tilo_harness.schedule_store import MAX_FAILURES

KOLKATA = make_record().cadence


@pytest.fixture(params=["memory", pytest.param("firestore", marks=pytest.mark.emulator)])
def rig(request: pytest.FixtureRequest) -> StoreRig:
    if request.param == "memory":
        return memory_rig()
    request.getfixturevalue("emulator_host")
    return firestore_rig()


def test_FR_AGT_14_reenabling_a_long_paused_schedule_moves_next_due_to_the_next_slot(rig: StoreRig) -> None:
    stale = next_slot(KOLKATA, rig.now() - 3 * WEEK - timedelta(days=2))  # a cadence slot about 3 weeks ago
    rig.add(make_record("sched_a", next_due=stale))
    assert rig.store.update("sched_a", enabled=False).enabled is False
    assert rig.store.get("sched_a").next_due == stale  # pausing moves nothing
    back = rig.store.update("sched_a", enabled=True)
    assert back is not None and back.enabled is True
    after = rig.now()
    got = rig.store.get("sched_a")
    assert got.next_due > after - timedelta(minutes=5) and got.next_due > stale + 2 * WEEK
    assert got.next_due == next_slot(KOLKATA, got.next_due - timedelta(microseconds=1))  # still on the cadence
    assert got.next_due - after <= WEEK + timedelta(hours=1)  # the NEXT slot, not one further out
    assert back.next_due == got.next_due  # the returned record agrees


def test_FR_AGT_14_a_future_next_due_is_left_alone_on_reenable(rig: StoreRig) -> None:
    future = next_slot(KOLKATA, rig.now() + timedelta(days=1))
    rig.add(make_record("sched_a", next_due=future, enabled=False))
    rig.store.update("sched_a", enabled=True)
    assert rig.store.get("sched_a").next_due == future


def test_FR_AGT_14_reenable_still_clears_failures_backoff_and_error(rig: StoreRig) -> None:
    due = next_slot(KOLKATA, rig.now() - 2 * WEEK)
    rig.add(make_record("sched_a", next_due=due))
    if rig.is_memory:  # the memory store's `due` and failure path run on its fake clock
        for _ in range(MAX_FAILURES):
            assert rig.store.claim("sched_a", due) is True
            rig.store.record_failure("sched_a", due, error="start_failed")
            rig.clock.advance(timedelta(days=2))
        before = rig.store.get("sched_a")
        assert before.enabled is False and before.failures == MAX_FAILURES
    else:  # Firestore: server time cannot be moved, so only the first failure fits
        assert rig.store.claim("sched_a", due) is True
        rig.store.record_failure("sched_a", due, error="start_failed")
        assert rig.store.get("sched_a").failures == 1
    rig.store.update("sched_a", enabled=True)
    got = rig.store.get("sched_a")
    assert (got.enabled, got.failures, got.backoff_until, got.last_error) == (True, 0, None, None)
    assert got.next_due > rig.now()


def test_FR_AGT_14_a_pause_does_not_move_next_due_and_neither_does_a_title_only_update(rig: StoreRig) -> None:
    due = next_slot(KOLKATA, rig.now() - 2 * WEEK)
    rig.add(make_record("sched_a", next_due=due))
    rig.store.update("sched_a", title="Renamed")
    assert rig.store.get("sched_a").next_due == due  # still enabled and due: it still fires its slot
    rig.store.update("sched_a", enabled=False)
    rig.store.update("sched_a", title="Renamed again")
    assert rig.store.get("sched_a").next_due == due


def test_FR_AGT_14_reenable_after_three_weeks_fires_nothing_until_the_next_slot() -> None:
    """The memory store on a fake clock: no catch-up run, then exactly one at the next slot, which is not `skipped`."""
    rig = make_tick_rig([make_record("sched_a", next_due=MON_0330Z + WEEK)], now=MON_0330Z + timedelta(days=1))
    rig.store.update("sched_a", enabled=False)
    rig.clock.set(MON_0330Z + 3 * WEEK + timedelta(days=2, hours=5))  # Wednesday 3 weeks on: slot of week 3 long past
    rig.store.update("sched_a", enabled=True)
    next_due = rig.store.get("sched_a").next_due
    assert next_due == MON_0330Z + 4 * WEEK == next_slot(KOLKATA, rig.clock())
    assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []
    rig.clock.set(next_due - timedelta(seconds=1))
    assert rig.ticker.tick().fired == 0
    rig.clock.set(next_due)
    assert rig.ticker.tick().fired == 1
    (run,) = rig.starter.started
    assert (run.slot, run.skipped) == (next_due, 0)
    assert rig.store.get("sched_a").next_due == next_due + WEEK


def test_FR_AGT_14_reenable_on_the_slot_instant_moves_strictly_after_now() -> None:
    """`next_due` equal to the store's now is 'at or before': it moves to the slot strictly after now."""
    rig = make_tick_rig([make_record("sched_a", enabled=False)], now=MON_0330Z)
    rig.store.update("sched_a", enabled=True)
    assert rig.store.get("sched_a").next_due == MON_0330Z + WEEK
    assert rig.ticker.tick().fired == 0


def test_FR_AGT_14_reenable_uses_the_stores_clock_not_the_wall_clock() -> None:
    """Both instants are fixed in 2026-10, in the past or the future of the real wall clock alike."""
    rig = make_tick_rig([make_record("sched_a", enabled=False, next_due=MON_0330Z)], now=MON_0330Z - timedelta(hours=1))
    rig.store.update("sched_a", enabled=True)
    assert rig.store.get("sched_a").next_due == MON_0330Z  # in the store's future: untouched
    rig2 = make_tick_rig(
        [make_record("sched_a", enabled=False, next_due=MON_0330Z)], now=datetime(2027, 3, 1, 12, 0, tzinfo=UTC)
    )
    rig2.store.update("sched_a", enabled=True)
    assert rig2.store.get("sched_a").next_due == next_slot(KOLKATA, datetime(2027, 3, 1, 12, 0, tzinfo=UTC))


def test_FR_AGT_14_a_reenabled_stale_schedule_never_makes_a_catch_up_burst() -> None:
    """Many schedules disabled for months and switched on together: none is due at once (the 20-a-tick limit and the
    catch-up collapse are for other cases; here nothing is due at all)."""
    records = [make_record(f"sched_p{n:02d}", enabled=False, next_due=MON_0330Z) for n in range(MAX_FIRES_PER_TICK + 5)]
    rig = make_tick_rig(records, now=MON_0330Z + 12 * WEEK + timedelta(days=3))
    for record in records:
        rig.store.update(record.schedule_id, enabled=True)
    assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []
