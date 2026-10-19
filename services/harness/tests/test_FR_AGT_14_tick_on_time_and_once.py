"""FR-AGT-14 (PRD 8.6, 6.3): "A weekly schedule fires on time" and fires exactly once per slot.

Given a weekly schedule, when a tick runs at or after `next_due`, then the run starts in that same tick; a tick
before it
starts nothing. A repeated or concurrent tick (Cloud Scheduler retries, two instances) never starts a slot twice: the
slot
is claimed in the store before the run starts, and the same `slot_key` is the idempotency key of the start. Fake
clock, fake
store and starter (schedule_support.py), no sleeps. Interface: API_FR_AGT_14.md.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from schedule_support import MON_0330Z, WEEK, make_rig, make_schedule
from tilo_harness.schedule import MAX_FIRES_PER_TICK, Cadence, RunStart, next_slot, slot_key


def test_FR_AGT_14_a_tick_before_next_due_starts_nothing_and_changes_nothing():
    rig = make_rig(now=MON_0330Z - timedelta(milliseconds=1))
    assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []
    assert rig.store.get("sched_a").next_due == MON_0330Z
    assert rig.store.held() == {}


def test_FR_AGT_14_a_tick_at_exactly_next_due_starts_the_run_in_that_same_tick():
    rig = make_rig(now=MON_0330Z)
    assert rig.ticker.tick().fired == 1
    assert len(rig.starter.started) == 1
    assert rig.starter.clock_at_start == [MON_0330Z]


def test_FR_AGT_14_a_tick_after_next_due_starts_the_run_and_the_schedule_moves_one_week_on():
    rig = make_rig(now=MON_0330Z + timedelta(minutes=1))
    assert rig.ticker.tick().fired == 1
    after = rig.store.get("sched_a")
    assert after.next_due == MON_0330Z + WEEK
    assert after.last_slot == slot_key("sched_a", MON_0330Z)
    assert after.last_world_id == rig.starter.world_ids[0]
    assert rig.store.held() == {}


def test_FR_AGT_14_the_run_start_carries_the_approved_brief_budget_owner_and_title():
    rig = make_rig([make_schedule(budget_cap=12.5, title="Weekly supplier digest", approved_brief_ref="w_approved_7")])
    rig.ticker.tick()
    run: RunStart = rig.starter.started[0]
    assert run.schedule_id == "sched_a"
    assert run.owner_user_id == "u_owner"
    assert run.title == "Weekly supplier digest"
    assert run.approved_brief_ref == "w_approved_7"
    assert run.budget_cap == 12.5
    assert run.slot == MON_0330Z
    assert run.skipped == 0
    assert run.cache_namespace == "sched_a"


def test_FR_AGT_14_the_idempotency_key_is_the_schedule_and_slot_and_nothing_else():
    key = slot_key("sched_a", MON_0330Z)
    assert key.startswith("sched_a:")
    assert slot_key("sched_a", MON_0330Z) == key
    assert slot_key("sched_b", MON_0330Z) != key
    assert slot_key("sched_a", MON_0330Z + WEEK) != key
    assert (
        slot_key("sched_a", MON_0330Z.astimezone(datetime.now().astimezone().tzinfo)) == key
    )  # an instant, not a zone
    rig = make_rig()
    rig.ticker.tick()
    assert rig.starter.started[0].idempotency_key == key


def test_FR_AGT_14_repeated_ticks_in_the_same_instant_start_the_slot_once():
    rig = make_rig()
    results = [rig.ticker.tick().fired for _ in range(10)]
    assert results == [1] + [0] * 9
    assert len(rig.starter.attempts) == 1


def test_FR_AGT_14_a_weekly_schedule_fires_at_each_slot_over_five_weeks_with_a_tick_every_15_minutes():
    rig = make_rig(now=MON_0330Z - timedelta(hours=2))
    horizon = MON_0330Z + 4 * WEEK + timedelta(hours=2)
    while rig.clock() <= horizon:
        rig.ticker.tick()
        rig.clock.advance(15 * 60)
    assert rig.starter.clock_at_start == [MON_0330Z + k * WEEK for k in range(5)]  # exactly on time, never late
    assert [r.slot for r in rig.starter.started] == [MON_0330Z + k * WEEK for k in range(5)]
    assert len({r.idempotency_key for r in rig.starter.started}) == 5


def test_FR_AGT_14_a_weekly_schedule_keeps_its_local_time_through_a_dst_change():
    new_york_monday_0900 = Cadence(weekday=0, hour=9, minute=0, tz="America/New_York")
    first = datetime(2026, 10, 19, 13, 0, tzinfo=UTC)  # 09:00 EDT
    rig = make_rig([make_schedule(cadence=new_york_monday_0900, next_due=first)], now=first - timedelta(hours=1))
    horizon = datetime(2026, 11, 9, 16, 0, tzinfo=UTC)
    while rig.clock() <= horizon:
        rig.ticker.tick()
        rig.clock.advance(15 * 60)
    assert rig.starter.clock_at_start == [
        datetime(2026, 10, 19, 13, 0, tzinfo=UTC),  # EDT
        datetime(2026, 10, 26, 13, 0, tzinfo=UTC),  # EDT
        datetime(2026, 11, 2, 14, 0, tzinfo=UTC),  # EST, clocks went back on 1 Nov
        datetime(2026, 11, 9, 14, 0, tzinfo=UTC),  # EST
    ]


def test_FR_AGT_14_two_schedules_due_together_both_fire_once_in_one_tick():
    rig = make_rig([make_schedule("sched_a"), make_schedule("sched_b")])
    assert rig.ticker.tick().fired == 2
    assert sorted(r.schedule_id for r in rig.starter.started) == ["sched_a", "sched_b"]
    assert rig.ticker.tick().fired == 0


def test_FR_AGT_14_at_most_the_rate_limit_of_runs_start_per_tick_and_the_rest_stay_due():
    assert MAX_FIRES_PER_TICK == 20  # design brief rule 8, PRD 6.3 "start runs with rate limits"
    schedules = [make_schedule(f"sched_{i:02d}") for i in range(25)]
    rig = make_rig(schedules)
    assert rig.ticker.tick().fired == 20
    assert len(rig.starter.started) == 20
    still_due = [s for s in schedules if rig.store.get(s.schedule_id).next_due == MON_0330Z]
    assert len(still_due) == 5
    assert rig.ticker.tick().fired == 5  # the rest fire on the next tick
    assert rig.ticker.tick().fired == 0
    assert sorted(r.schedule_id for r in rig.starter.started) == sorted(s.schedule_id for s in schedules)  # each once


def test_FR_AGT_14_a_claim_is_taken_before_the_run_starts_and_released_by_completing_it():
    rig = make_rig()
    seen: dict[str, dict[str, datetime]] = {}
    real_start = rig.starter.start

    def start_and_look(run: RunStart) -> str:
        seen["held_during_start"] = rig.store.held()
        return real_start(run)

    rig.starter.start = start_and_look  # type: ignore[method-assign]
    rig.ticker.tick()
    assert seen["held_during_start"] == {"sched_a": MON_0330Z}
    assert rig.store.held() == {}


def test_FR_AGT_14_concurrent_ticks_start_each_slot_exactly_once():
    """Eight threads tick at the same instant over three due schedules. Every start blocks inside the starter until the
    losers have finished, so a tick that did not win its claim and started anyway would be seen as a second start."""
    n_threads, names = 8, ("sched_a", "sched_b", "sched_c")
    rig = make_rig([make_schedule(n) for n in names])
    rig.starter.gate = threading.Event()
    done, finished = threading.Condition(), []

    def worker() -> None:
        try:
            rig.ticker.tick()
        finally:
            with done:
                finished.append(1)
                done.notify_all()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n_threads)]
    for t in threads:
        t.start()
    with done:  # at most len(names) threads can be parked inside a start; every other tick must return
        done.wait_for(lambda: len(finished) >= n_threads - len(names), timeout=5)
    rig.starter.gate.set()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads)
    assert sorted(r.schedule_id for r in rig.starter.started) == sorted(names)
    assert len(rig.starter.attempts) == len(names)
    assert all(rig.store.get(n).next_due == MON_0330Z + WEEK for n in names)


def test_FR_AGT_14_a_second_instance_ticking_while_the_first_is_mid_start_starts_nothing():
    rig = make_rig()
    rig.starter.gate = threading.Event()
    first = threading.Thread(target=rig.ticker.tick, daemon=True)
    first.start()
    assert rig.starter.entered.wait(timeout=5)
    assert rig.ticker.tick().fired == 0  # the other instance: the slot is claimed
    assert len(rig.starter.attempts) == 1
    rig.starter.gate.set()
    first.join(timeout=10)
    assert len(rig.starter.started) == 1
    assert rig.store.get("sched_a").next_due == MON_0330Z + WEEK


def test_FR_AGT_14_many_threads_ticking_repeatedly_while_time_passes_never_double_start():
    rig = make_rig([make_schedule("sched_a"), make_schedule("sched_b", next_due=MON_0330Z + timedelta(minutes=5))])
    stop = threading.Event()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            while not stop.is_set():
                rig.ticker.tick()
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(6)]
    for t in threads:
        t.start()
    for _ in range(3 * 7 * 24 * 4):  # three weeks in 15-minute steps, while the workers spin
        rig.clock.advance(15 * 60)
    stop.set()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    keys = [r.idempotency_key for r in rig.starter.started]
    assert len(keys) == len(set(keys)), "a slot was started twice"
    for run, at in zip(rig.starter.started, rig.starter.clock_at_start, strict=True):
        assert run.slot <= at, "a slot started before it was due"


# ---------------------------------------------------------------------------
# Property: random ticking with random start failures keeps the one-run-per-slot and never-early rules.

ops = st.lists(
    st.one_of(
        st.tuples(st.just("advance"), st.integers(1, 3 * 24 * 3600)),
        st.tuples(st.just("back"), st.integers(1, 2 * 24 * 3600)),
        st.tuples(st.just("tick"), st.just(0)),
        st.tuples(st.just("fail"), st.integers(1, 2)),
    ),
    min_size=1,
    max_size=60,
)


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(operations=ops)
def test_FR_AGT_14_property_one_success_per_slot_never_early_never_re_fired_and_always_recoverable(operations):
    rig = make_rig(
        [
            make_schedule("sched_a"),
            make_schedule(
                "sched_b",
                cadence=Cadence(6, 20, 15, "Europe/London"),
                next_due=datetime(2026, 10, 11, 19, 15, tzinfo=UTC),
            ),
        ]
    )
    seen_at: list[tuple[datetime, RunStart]] = []
    real_start = rig.starter.start

    def spy(run: RunStart) -> str:
        seen_at.append((rig.clock(), run))
        return real_start(run)

    rig.starter.start = spy  # type: ignore[method-assign]
    for op, arg in operations:
        if op == "advance":
            rig.clock.advance(arg)
        elif op == "back":
            rig.clock.advance(-arg)
        elif op == "fail":
            rig.starter.fail_next(arg)
        else:
            rig.ticker.tick()
    # (a) a slot is never started successfully twice
    keys = [r.idempotency_key for r in rig.starter.started]
    assert len(keys) == len(set(keys))
    # (b) a slot is never started before it is due, whatever the clock did
    assert all(run.slot <= at for at, run in seen_at)
    # (c) per schedule the started slots strictly increase: a clock that went back never re-fires an older slot
    for sid in ("sched_a", "sched_b"):
        slots = [r.slot for r in rig.starter.started if r.schedule_id == sid]
        assert slots == sorted(set(slots))
    # (d) nothing is stuck: once failures stop and time is past every slot, a tick or two catch up, no claim held
    rig.starter.clear_failures()
    far = max(rig.clock(), MON_0330Z) + timedelta(days=30)
    rig.clock.set(far)
    for _ in range(3):
        rig.ticker.tick()
    assert rig.store.held() == {}
    for sid in ("sched_a", "sched_b"):
        assert rig.store.get(sid).next_due > far
        assert rig.store.get(sid).next_due == next_slot(
            rig.store.get(sid).cadence, rig.store.get(sid).next_due - timedelta(days=1)
        )
