"""FR-AGT-14d item 3 (security follow-up of the scheduled-runs review): a skip that must NOT count.

`run_seams_unwired` is a global condition (the whole service cannot start any run), not a fault of one schedule. Counted
against each schedule it disabled every schedule after about eight and a half hours of an outage (MAX_FAILURES), so:

- `StartSkipped` has `count: bool = True`; with `count=False` the Ticker releases the claim and records NO failure
  and NO backoff (`failures`, `last_error`, `backoff_until` and `next_due` all unchanged), and logs the fixed code
  ONCE per
  tick however many schedules were skipped;
- a skip with the default `count=True` behaves exactly as before (both `advance` spellings);
- 25 schedules and unwired seams for 20 ticks disable none of them.

Interface: services/api/tests/API_FR_AGT_14d.md. Fakes: fr_agt_14_store_support.py. The API side (the real
`ScheduleStarter` raising `StartSkipped("run_seams_unwired", count=False)`) is in services/api/tests.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from fr_agt_14_store_support import MON_0330Z, WEEK, RaisingStarter, make_record, make_tick_rig
from tilo_harness.schedule import StartSkipped
from tilo_harness.schedule_store import MAX_FAILURES

CODE = "run_seams_unwired"


def _unwired(_run: object) -> Exception:
    return StartSkipped(CODE, count=False)


def test_FR_AGT_14_start_skipped_counts_by_default_and_carries_the_flag() -> None:
    assert StartSkipped("x_code").count is True
    assert StartSkipped("x_code", advance=True).count is True
    skipped = StartSkipped(CODE, count=False)
    assert skipped.count is False and skipped.code == CODE and skipped.advance is False
    assert isinstance(skipped, Exception)


def test_FR_AGT_14_an_uncounted_skip_records_nothing_and_releases_the_claim() -> None:
    starter = RaisingStarter(exc_for=_unwired)
    rig = make_tick_rig(starter=starter)
    assert rig.ticker.tick().fired == 0
    got = rig.store.get("sched_a")
    assert (got.enabled, got.failures, got.last_error, got.backoff_until) == (True, 0, None, None)
    assert got.next_due == MON_0330Z and got.last_slot is None and got.last_world_id is None
    assert rig.alerts == []
    assert rig.store.claim("sched_a", MON_0330Z) is True  # the claim was released
    rig.store.release("sched_a", MON_0330Z)
    assert len(starter.attempts) == 1


def test_FR_AGT_14_an_uncounted_skip_gives_up_nothing_even_when_it_is_asked_to_advance() -> None:
    """`count=False` wins over `advance`: a global outage must never move a schedule to next week either."""
    rig = make_tick_rig(starter=RaisingStarter(exc_for=lambda run: StartSkipped(CODE, advance=True, count=False)))
    assert rig.ticker.tick().fired == 0
    got = rig.store.get("sched_a")
    assert (got.next_due, got.failures, got.last_error, got.backoff_until) == (MON_0330Z, 0, None, None)


def test_FR_AGT_14_the_same_slot_fires_on_the_next_tick_once_the_condition_is_gone() -> None:
    state = {"unwired": True}
    starter = RaisingStarter(exc_for=lambda run: _unwired(run) if state["unwired"] else None)
    rig = make_tick_rig(starter=starter)
    for _ in range(3):
        rig.clock.advance(timedelta(minutes=1))
        assert rig.ticker.tick().fired == 0
    state["unwired"] = False
    rig.clock.advance(timedelta(minutes=1))
    assert rig.ticker.tick().fired == 1  # no backoff to wait for
    assert [r.slot for r in starter.started] == [MON_0330Z]  # the same slot, once
    got = rig.store.get("sched_a")
    assert (got.failures, got.next_due) == (0, MON_0330Z + WEEK)


def test_FR_AGT_14_a_counted_skip_is_unchanged_by_the_new_flag() -> None:
    rig = make_tick_rig(starter=RaisingStarter(exc_for=lambda run: StartSkipped("snapshot_missing")))
    assert rig.ticker.tick().fired == 0
    got = rig.store.get("sched_a")
    assert (got.failures, got.last_error, got.next_due) == (1, "snapshot_missing", MON_0330Z)
    assert got.backoff_until is not None and got.backoff_until > rig.clock()


def test_FR_AGT_14_the_fixed_code_is_logged_once_per_tick_not_once_per_schedule(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = make_tick_rig([make_record(f"sched_l{n:02d}") for n in range(12)], starter=RaisingStarter(exc_for=_unwired))
    caplog.set_level(logging.DEBUG)
    for tick in range(3):
        before = len(caplog.records)
        rig.clock.advance(timedelta(minutes=1))
        rig.ticker.tick()
        about = [r for r in caplog.records[before:] if CODE in r.getMessage()]
        assert len(about) == 1, f"tick {tick}: {[r.getMessage() for r in about]}"
    assert "sched_l" not in caplog.text  # a schedule id is never in the line


def test_FR_AGT_14_a_tick_with_nothing_due_logs_no_code() -> None:
    rig = make_tick_rig([make_record("sched_a", next_due=MON_0330Z + WEEK)], starter=RaisingStarter(exc_for=_unwired))
    assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []


def test_FR_AGT_14_twenty_five_schedules_and_unwired_seams_for_twenty_ticks_disable_none() -> None:
    schedules = [make_record(f"sched_u{n:02d}") for n in range(25)]
    starter = RaisingStarter(exc_for=_unwired)
    rig = make_tick_rig(schedules, starter=starter)
    assert 20 > MAX_FAILURES  # more ticks than the failure limit: counted, they would all be disabled by now
    for _ in range(20):
        rig.clock.advance(timedelta(minutes=1))
        assert rig.ticker.tick().fired == 0
    assert starter.attempts, "the ticks never tried to start anything"
    for s in schedules:
        got = rig.store.get(s.schedule_id)
        assert (got.enabled, got.failures, got.last_error, got.backoff_until, got.next_due) == (
            True,
            0,
            None,
            None,
            MON_0330Z,
        ), s.schedule_id
