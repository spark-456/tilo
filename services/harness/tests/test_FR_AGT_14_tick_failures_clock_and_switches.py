"""FR-AGT-14 (PRD 8.6, 6.3, NFR-24): the hard edges of "a weekly schedule fires on time".

- A start that raises leaves the slot claimable again and never advances `next_due`: the next tick retries the same
  slot with
  the same idempotency key (design brief rule 3).
- A clock that goes backwards never re-fires an older slot and never moves `next_due` back.
- Missed slots (an outage) collapse into one firing for the latest missed slot; the skipped count is one `alert.raised`
  (rule 4), so nothing is silent and nothing backfills.
- `replay_only` (the NFR-24 kill switch) starts nothing and does not advance `next_due` (rule 7); a disabled schedule
  never
  fires, even from a store that hands it back.
Fake clock, store, starter, flags (schedule_support.py). Interface: API_FR_AGT_14.md.
"""

from __future__ import annotations

import re
from datetime import timedelta

from schedule_support import MON_0330Z, WEEK, MemoryScheduleStore, StartFailed, make_rig, make_schedule
from tilo_harness.schedule import slot_key

ULID = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


# ---------------------------------------------------------------------------
# A start that raises


def test_FR_AGT_14_a_start_that_raises_leaves_the_slot_unclaimed_and_next_due_unmoved():
    rig = make_rig()
    rig.starter.fail_next(1)
    assert rig.ticker.tick().fired == 0  # never raises for one schedule's failure
    assert len(rig.starter.attempts) == 1
    assert rig.starter.started == []
    schedule = rig.store.get("sched_a")
    assert schedule.next_due == MON_0330Z
    assert schedule.last_slot is None
    assert schedule.last_world_id is None
    assert rig.store.held() == {}
    assert rig.alerts.calls == []


def test_FR_AGT_14_the_next_tick_retries_the_same_slot_with_the_same_idempotency_key_and_starts_it_once():
    rig = make_rig()
    rig.starter.fail_next(1)
    rig.ticker.tick()
    assert rig.ticker.tick().fired == 1  # no waiting, no sleep: it is claimable again at once
    assert rig.ticker.tick().fired == 0
    assert len(rig.starter.attempts) == 2
    assert len(rig.starter.started) == 1
    first, second = rig.starter.attempts
    assert first.idempotency_key == second.idempotency_key == slot_key("sched_a", MON_0330Z)
    assert rig.store.get("sched_a").next_due == MON_0330Z + WEEK


def test_FR_AGT_14_a_run_that_keeps_failing_is_retried_on_every_tick_and_never_skipped():
    rig = make_rig()
    rig.starter.fail_next(5)
    assert [rig.ticker.tick().fired for _ in range(5)] == [0] * 5
    assert rig.store.get("sched_a").next_due == MON_0330Z
    assert rig.ticker.tick().fired == 1
    assert len({r.idempotency_key for r in rig.starter.attempts}) == 1


def test_FR_AGT_14_one_schedule_failing_does_not_stop_the_others_in_the_same_tick():
    rig = make_rig([make_schedule("sched_a"), make_schedule("sched_b")])
    rig.starter.fail_next(1)  # the first attempt (sched_a, the oldest then the lowest id) fails
    assert rig.ticker.tick().fired == 1
    assert [r.schedule_id for r in rig.starter.started] == ["sched_b"]
    assert rig.store.get("sched_a").next_due == MON_0330Z
    assert rig.store.get("sched_b").next_due == MON_0330Z + WEEK
    assert rig.ticker.tick().fired == 1
    assert sorted(r.schedule_id for r in rig.starter.started) == ["sched_a", "sched_b"]


def test_FR_AGT_14_a_failed_start_in_a_slot_never_leaves_a_stale_prior_world_for_the_retry():
    rig = make_rig([make_schedule(last_world_id="w_previous_run")])
    rig.starter.fail_next(1)
    rig.ticker.tick()
    rig.ticker.tick()
    assert [r.prior_world_id for r in rig.starter.attempts] == ["w_previous_run", "w_previous_run"]
    assert rig.store.get("sched_a").last_world_id == rig.starter.world_ids[0]


def test_FR_AGT_14_a_failure_type_does_not_matter_any_exception_from_the_starter_keeps_the_slot_retryable():
    rig = make_rig()
    rig.starter.fail_next(1, exc=RuntimeError("boom"))
    assert rig.ticker.tick().fired == 0
    rig.starter.fail_next(1, exc=StartFailed("again"))
    assert rig.ticker.tick().fired == 0
    assert rig.ticker.tick().fired == 1


# ---------------------------------------------------------------------------
# A clock that goes backwards


def test_FR_AGT_14_a_clock_that_goes_backwards_never_re_fires_a_slot_or_moves_next_due_back():
    rig = make_rig()
    rig.ticker.tick()
    assert len(rig.starter.started) == 1
    for back in (timedelta(minutes=1), timedelta(days=3), timedelta(days=60)):
        rig.clock.set(MON_0330Z - back)
        assert rig.ticker.tick().fired == 0
    after = rig.store.get("sched_a")
    assert after.next_due == MON_0330Z + WEEK
    assert after.last_slot == slot_key("sched_a", MON_0330Z)
    assert len(rig.starter.attempts) == 1
    rig.clock.set(MON_0330Z + WEEK)  # and forward again: the next slot fires, once
    assert rig.ticker.tick().fired == 1
    assert [r.slot for r in rig.starter.started] == [MON_0330Z, MON_0330Z + WEEK]


def test_FR_AGT_14_a_clock_that_goes_back_before_a_failed_slot_waits_and_fires_it_when_time_returns():
    rig = make_rig()
    rig.starter.fail_next(1)
    rig.ticker.tick()
    rig.clock.set(MON_0330Z - timedelta(days=2))
    assert rig.ticker.tick().fired == 0
    assert rig.store.get("sched_a").next_due == MON_0330Z
    rig.clock.set(MON_0330Z + timedelta(seconds=30))
    assert rig.ticker.tick().fired == 1
    assert len(rig.starter.started) == 1


def test_FR_AGT_14_a_slot_is_never_started_before_it_is_due_even_one_millisecond():
    rig = make_rig()
    rig.clock.set(MON_0330Z - timedelta(milliseconds=1))
    for _ in range(3):
        assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []


# ---------------------------------------------------------------------------
# Missed slots


def test_FR_AGT_14_missed_slots_collapse_into_one_firing_for_the_latest_missed_slot():
    rig = make_rig(now=MON_0330Z + 3 * WEEK + timedelta(days=2))  # slots at +0, +1w, +2w, +3w are all past
    assert rig.ticker.tick().fired == 1
    assert len(rig.starter.attempts) == 1  # no backfill storm
    run = rig.starter.started[0]
    assert run.slot == MON_0330Z + 3 * WEEK
    assert run.idempotency_key == slot_key("sched_a", MON_0330Z + 3 * WEEK)
    assert run.skipped == 3
    assert rig.store.get("sched_a").next_due == MON_0330Z + 4 * WEEK
    assert rig.ticker.tick().fired == 0


def test_FR_AGT_14_the_skipped_slots_are_raised_as_exactly_one_info_alert_for_the_new_run():
    rig = make_rig(now=MON_0330Z + 3 * WEEK + timedelta(days=2))
    rig.ticker.tick()
    rig.ticker.tick()
    assert len(rig.alerts.calls) == 1
    world_id, kwargs = rig.alerts.calls[0]
    assert world_id == rig.starter.world_ids[0]
    assert kwargs["type"] == "alert.raised"
    assert kwargs["severity"] == "info"
    assert kwargs["target"] == world_id
    assert kwargs["data"]["card_id"] is None
    assert ULID.match(kwargs["data"]["alert_id"])
    assert "3" in kwargs["summary"]  # the count a person reads


def test_FR_AGT_14_an_on_time_firing_raises_no_alert():
    rig = make_rig()
    rig.ticker.tick()
    assert rig.starter.started[0].skipped == 0
    assert rig.alerts.calls == []


def test_FR_AGT_14_a_firing_one_slot_late_skips_nothing_when_no_slot_was_missed():
    rig = make_rig(now=MON_0330Z + timedelta(days=6, hours=23))  # still before the second slot
    rig.ticker.tick()
    assert rig.starter.started[0].skipped == 0
    assert rig.starter.started[0].slot == MON_0330Z
    assert rig.alerts.calls == []


def test_FR_AGT_14_no_alert_is_raised_for_a_start_that_failed_only_for_the_one_that_ran():
    rig = make_rig(now=MON_0330Z + 2 * WEEK + timedelta(hours=1))
    rig.starter.fail_next(1)
    rig.ticker.tick()
    assert rig.alerts.calls == []
    rig.ticker.tick()
    assert len(rig.alerts.calls) == 1
    assert rig.starter.started[0].skipped == 2


# ---------------------------------------------------------------------------
# Kill switch and disabled schedules


def test_FR_AGT_14_replay_only_starts_nothing_and_does_not_advance_next_due():
    rig = make_rig()
    rig.flags.set("replay_only", True, reason="daily cap reached")
    for _ in range(3):
        assert rig.ticker.tick().fired == 0
    assert "replay_only" in rig.flags.reads
    assert rig.starter.attempts == []
    schedule = rig.store.get("sched_a")
    assert (schedule.next_due, schedule.last_slot, schedule.last_world_id) == (MON_0330Z, None, None)
    assert rig.store.held() == {}
    assert rig.alerts.calls == []


def test_FR_AGT_14_when_replay_only_clears_the_held_slots_fire_once_for_the_latest_slot():
    rig = make_rig()
    rig.flags.set("replay_only", True, reason="daily cap reached")
    rig.clock.advance(3 * WEEK + timedelta(hours=1))
    assert rig.ticker.tick().fired == 0
    rig.flags.set("replay_only", False, reason="cap lifted")
    assert rig.ticker.tick().fired == 1
    assert rig.ticker.tick().fired == 0
    assert len(rig.starter.started) == 1
    run = rig.starter.started[0]
    assert (run.slot, run.skipped) == (MON_0330Z + 3 * WEEK, 3)
    assert len(rig.alerts.calls) == 1


def test_FR_AGT_14_a_disabled_schedule_never_fires():
    rig = make_rig([make_schedule("sched_off", enabled=False), make_schedule("sched_on")])
    rig.clock.advance(5 * WEEK)
    assert rig.ticker.tick().fired == 1
    assert [r.schedule_id for r in rig.starter.started] == ["sched_on"]
    assert rig.store.get("sched_off").next_due == MON_0330Z


def test_FR_AGT_14_a_disabled_schedule_never_fires_even_if_the_store_hands_it_back():
    store = MemoryScheduleStore([make_schedule("sched_off", enabled=False)], due_ignores_enabled=True)
    rig = make_rig(store=store)
    for _ in range(3):
        assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []
    assert store.get("sched_off").next_due == MON_0330Z
    assert store.held() == {}


def test_FR_AGT_14_a_schedule_disabled_by_the_store_after_it_was_seen_due_does_not_fire():
    """The owner is revoked (design rule 7: the store disables the schedule) between the due query and the claim."""
    rig = make_rig()
    real_due = rig.store.due

    def due_then_disable(now, limit):
        rows = real_due(now, limit)
        rig.store.add(make_schedule(enabled=False))
        return rows

    rig.store.due = due_then_disable  # type: ignore[method-assign]
    assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []
