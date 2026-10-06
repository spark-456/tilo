"""FR-AGT-14b (design decision 6; PRD 6.3, 8.6): the `Ticker` over the REAL schedule store, and the issuer check.

PR #446's tests run the `Ticker` over a fake store that never backs off; they stay as they are. These cases pin what
changes when the store is the production one:

- a start that raises is recorded by the Ticker through `store.record_failure(id, due, *, error, next_due=None)`
  (a fixed code, never the exception's text), the slot stays claimable, the schedule is out of `due()` for its backoff,
  and the same slot (same idempotency key) is retried when the backoff has passed;
- `StartSkipped(code, advance=...)` is a start that deliberately did nothing: recorded the same way, and `advance=True`
  also moves `next_due` to the first slot after the one skipped (the owner's budget policy did not cover it: retry
  next week, not every minute);
- 20 failing schedules do not starve a healthy 21st; one schedule's failing `complete`, `record_failure` or slot
  arithmetic never aborts the tick for the others;
- the harness tick route also checks the token's issuer (`TickWiring` verification, design decision 7).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fr_agt_14_store_support import MON_0330Z, WEEK, RaisingStarter, make_record, make_tick_rig
from schedule_support import (
    AUDIENCE,
    GOOGLE_ISSUER,
    SCHEDULE_SA,
    FakeOidcVerifier,
    StartFailed,
    bearer,
    make_rig,
)
from tilo_harness import schedule as schedule_module
from tilo_harness.app import create_app
from tilo_harness.schedule import StartSkipped, TickWiring, next_slot, slot_key
from tilo_harness.schedule_store import MAX_FAILURES, InMemoryScheduleStore, backoff_for

CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _doc(rig: Any, schedule_id: str = "sched_a") -> dict[str, Any]:
    return rig.store.read_doc(schedule_id)


# --- a start that raises --------------------------------------------------------------------------------------------


def test_FR_AGT_14_a_failed_start_is_recorded_with_a_fixed_code_and_never_the_exception_text() -> None:
    rig = make_tick_rig()
    rig.starter.fail_next(1, exc=StartFailed("provider said: api key s3cret-value rejected for alice@example.com"))
    assert rig.ticker.tick().fired == 0
    doc = _doc(rig)
    assert doc["failures"] == 1 and doc["next_due"] == MON_0330Z and doc["enabled"] is True
    assert CODE.match(doc["last_error"]), doc["last_error"]
    assert "s3cret" not in doc["last_error"] and "alice" not in doc["last_error"]
    assert doc["backoff_until"] == rig.clock() + backoff_for(1)


def test_FR_AGT_14_a_backed_off_slot_is_not_retried_every_tick_and_is_retried_with_the_same_key_after() -> None:
    rig = make_tick_rig()
    rig.starter.fail_next(1)
    rig.ticker.tick()
    for _ in range(3):  # the Scheduler's next three minutes: nothing
        rig.clock.advance(timedelta(seconds=20))
        assert rig.ticker.tick().fired == 0
    assert len(rig.starter.attempts) == 1
    rig.clock.set(_doc(rig)["backoff_until"])  # the backoff has passed
    assert rig.ticker.tick().fired == 1
    first, second = rig.starter.attempts
    assert first.idempotency_key == second.idempotency_key == slot_key("sched_a", MON_0330Z)
    got = rig.store.get("sched_a")
    assert got.next_due == MON_0330Z + WEEK and got.last_world_id == rig.starter.world_ids[0]


def test_FR_AGT_14_the_limit_of_failures_disables_the_schedule_and_it_never_starts_again() -> None:
    rig = make_tick_rig()
    rig.starter.fail_next(100)
    for _ in range(MAX_FAILURES):
        rig.ticker.tick()
        rig.clock.advance(timedelta(days=2))  # past any backoff
    assert len(rig.starter.attempts) == MAX_FAILURES
    assert _doc(rig)["enabled"] is False
    rig.clock.advance(10 * WEEK)
    assert rig.ticker.tick().fired == 0
    assert len(rig.starter.attempts) == MAX_FAILURES


def test_FR_AGT_14_a_start_that_succeeds_after_failures_still_completes_the_slot() -> None:
    rig = make_tick_rig()
    rig.starter.fail_next(2)
    rig.ticker.tick()
    rig.clock.advance(timedelta(days=1))
    rig.ticker.tick()
    rig.clock.advance(timedelta(days=1))
    assert rig.ticker.tick().fired == 1
    assert rig.store.get("sched_a").last_slot == slot_key("sched_a", MON_0330Z)


# --- a start that deliberately did nothing --------------------------------------------------------------------------


def test_FR_AGT_14_a_skipped_start_that_advances_moves_to_the_next_slot_and_backs_off() -> None:
    rig = make_tick_rig(now=MON_0330Z + timedelta(minutes=1))
    rig.starter.fail_next(1, exc=StartSkipped("budget_not_granted", advance=True))
    assert rig.ticker.tick().fired == 0
    got = rig.store.get("sched_a")
    assert got.next_due == next_slot(got.cadence, MON_0330Z) == MON_0330Z + WEEK
    assert (got.failures, got.last_error) == (1, "budget_not_granted")
    assert got.last_slot is None and got.last_world_id is None
    assert got.backoff_until > rig.clock()
    assert rig.alerts == []
    for _ in range(2):  # nothing more until next week
        rig.clock.advance(timedelta(days=2))
        assert rig.ticker.tick().fired == 0
    assert len(rig.starter.attempts) == 1
    rig.clock.set(MON_0330Z + WEEK)
    assert rig.ticker.tick().fired == 1
    assert rig.starter.started[0].slot == MON_0330Z + WEEK and rig.starter.started[0].skipped == 0


def test_FR_AGT_14_a_skipped_start_that_does_not_advance_keeps_the_slot_for_a_retry() -> None:
    rig = make_tick_rig()
    rig.starter.fail_next(1, exc=StartSkipped("snapshot_missing", advance=False))
    assert rig.ticker.tick().fired == 0
    got = rig.store.get("sched_a")
    assert (got.next_due, got.failures, got.last_error) == (MON_0330Z, 1, "snapshot_missing")
    assert rig.ticker.tick().fired == 0  # backed off
    rig.clock.set(got.backoff_until)
    assert rig.ticker.tick().fired == 1
    assert rig.starter.attempts[0].idempotency_key == rig.starter.attempts[1].idempotency_key


def test_FR_AGT_14_a_skipped_start_that_does_not_count_keeps_the_slot_with_no_failure_and_no_backoff() -> None:
    """FR-AGT-14d item 3 (this pinned `failures == 1` and a backoff for `run_seams_unwired` in FR-AGT-14b; changed
    deliberately): with `count=False` the claim is released and nothing is recorded; the slot is claimable at once."""
    rig = make_tick_rig()
    rig.starter.fail_next(1, exc=StartSkipped("run_seams_unwired", count=False))
    assert rig.ticker.tick().fired == 0
    got = rig.store.get("sched_a")
    assert (got.next_due, got.failures, got.last_error, got.backoff_until) == (MON_0330Z, 0, None, None)
    assert got.enabled is True
    assert rig.store.claim("sched_a", MON_0330Z) is True  # the claim was released (and then this test takes it)
    rig.store.release("sched_a", MON_0330Z)
    assert rig.ticker.tick().fired == 1  # no backoff to wait out: the very next tick fires the same slot
    assert rig.starter.attempts[0].idempotency_key == rig.starter.attempts[1].idempotency_key


def test_FR_AGT_14_a_skip_that_advances_collapses_missed_slots_to_the_one_after_the_latest() -> None:
    rig = make_tick_rig(now=MON_0330Z + 3 * WEEK + timedelta(days=2))
    rig.starter.fail_next(1, exc=StartSkipped("budget_not_granted", advance=True))
    rig.ticker.tick()
    assert rig.store.get("sched_a").next_due == MON_0330Z + 4 * WEEK  # not stepped one week at a time


def test_FR_AGT_14_start_skipped_carries_its_code_and_is_an_exception() -> None:
    skipped = StartSkipped("budget_not_granted", advance=True)
    assert isinstance(skipped, Exception) and skipped.code == "budget_not_granted" and skipped.advance is True
    assert StartSkipped("x_code").advance is False  # the default: the slot is retried, not given up


# --- a failing schedule never hides or stops another ----------------------------------------------------------------


def test_FR_AGT_14_twenty_failing_schedules_do_not_starve_a_healthy_twenty_first() -> None:
    failing = [make_record(f"sched_f{n:02d}", next_due=MON_0330Z - WEEK) for n in range(20)]
    healthy = make_record("sched_healthy")
    starter = RaisingStarter(exc_for=lambda run: StartFailed("down") if run.schedule_id.startswith("sched_f") else None)
    rig = make_tick_rig([*failing, healthy], starter=starter)
    assert rig.ticker.tick().fired == 0  # the rate limit: 20 attempts, every one failing, oldest first
    assert sorted(r.schedule_id for r in starter.attempts) == sorted(s.schedule_id for s in failing)
    assert rig.ticker.tick().fired == 1  # the very next tick: the 20 are backed off, the healthy one runs
    assert [r.schedule_id for r in starter.started] == ["sched_healthy"]
    assert len(starter.attempts) == 21


def test_FR_AGT_14_a_complete_that_raises_for_one_schedule_does_not_abort_the_tick_and_is_retried_safely() -> None:
    class FlakyComplete(InMemoryScheduleStore):
        broken = True

        def complete(self, schedule_id: str, due: Any, **kwargs: Any) -> None:
            if self.broken and schedule_id == "sched_a":
                raise RuntimeError("firestore unavailable")
            super().complete(schedule_id, due, **kwargs)

    base = make_tick_rig([])
    flaky = FlakyComplete(clock=base.clock)
    rig = _rebuild(base, flaky, [make_record("sched_a"), make_record("sched_b")])

    rig.ticker.tick()  # must not raise
    assert flaky.get("sched_b").next_due == MON_0330Z + WEEK  # the other schedule was started and completed
    assert [r.schedule_id for r in rig.starter.started] == ["sched_a", "sched_b"]
    assert flaky.get("sched_a").next_due == MON_0330Z  # not completed
    rig.ticker.tick()
    assert len(rig.starter.attempts) == 2  # the claim is still live: no second start inside the lease
    flaky.broken = False
    rig.clock.advance(timedelta(minutes=5, seconds=1))  # the lease lapsed
    rig.ticker.tick()
    keys = [r.idempotency_key for r in rig.starter.attempts if r.schedule_id == "sched_a"]
    assert len(keys) == 2 and keys[0] == keys[1]  # retried with the SAME key, so a real starter dedupes it
    assert flaky.get("sched_a").next_due == MON_0330Z + WEEK


def test_FR_AGT_14_a_record_failure_that_raises_does_not_abort_the_tick() -> None:
    class FlakyRecord(InMemoryScheduleStore):
        def record_failure(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("firestore unavailable")

    rig = _rebuild(make_tick_rig([]), None, [make_record("sched_a"), make_record("sched_b")], flaky=FlakyRecord)
    rig.starter.fail_next(1)  # sched_a fails, and so does the recording of that failure
    rig.ticker.tick()  # must not raise
    assert [r.schedule_id for r in rig.starter.started] == ["sched_b"]


def test_FR_AGT_14_slot_arithmetic_that_raises_after_the_claim_releases_it_and_spares_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = make_tick_rig([make_record("sched_a"), make_record("sched_b")])
    real = schedule_module.slot_key

    def flaky(schedule_id: str, due: Any) -> str:
        if schedule_id == "sched_a":
            raise OverflowError("bad slot")
        return real(schedule_id, due)

    with monkeypatch.context() as patched:
        patched.setattr(schedule_module, "slot_key", flaky)
        rig.ticker.tick()  # must not raise
    assert [r.schedule_id for r in rig.starter.started] == ["sched_b"]
    assert rig.store.get("sched_a").next_due == MON_0330Z
    rig.clock.advance(timedelta(days=1))  # past any backoff the failure earned; still inside the same week
    assert rig.ticker.tick().fired == 1  # the claim was not left held: sched_a starts, for the same slot
    assert [r.slot for r in rig.starter.started if r.schedule_id == "sched_a"] == [MON_0330Z]


def test_FR_AGT_14_replay_only_over_the_real_store_starts_nothing_and_counts_no_failure() -> None:
    rig = make_tick_rig()
    rig.flags.set("replay_only", True, reason="daily cap reached")
    for _ in range(3):
        assert rig.ticker.tick().fired == 0
    doc = _doc(rig)
    assert (doc["next_due"], doc["failures"], doc["last_error"], doc["backoff_until"]) == (MON_0330Z, 0, None, None)
    assert rig.starter.attempts == []
    rig.flags.set("replay_only", False, reason="cap lifted")
    assert rig.ticker.tick().fired == 1


def test_FR_AGT_14_a_quarantined_record_is_skipped_and_the_tick_goes_on() -> None:
    from tilo_harness.schedule_store import schedule_to_doc

    rig = make_tick_rig([make_record("sched_good")])
    rig.store.insert_raw({**schedule_to_doc(make_record("sched_bad")), "next_due": MON_0330Z + timedelta(minutes=1)})
    assert rig.ticker.tick().fired == 1
    assert [r.schedule_id for r in rig.starter.started] == ["sched_good"]
    assert rig.store.read_doc("sched_bad")["last_error"] == "invalid_record"


def _rebuild(rig: Any, store: Any, schedules: list[Any], flaky: Any = None) -> Any:
    """The same fakes with a store of our own (a subclass that misbehaves on one call)."""
    from fr_agt_14_store_support import TickRig
    from schedule_support import FakeFlags, FakeRunStarter
    from tilo_harness.schedule import Ticker

    store = store if store is not None else flaky(clock=rig.clock)
    for schedule in schedules:
        assert store.create(schedule, max_per_owner=1000) is True
    starter, flags, alerts = FakeRunStarter(rig.clock), FakeFlags(), []
    ticker = Ticker(
        store=store, starter=starter, flags=flags, clock=rig.clock, alerts=lambda w, kw: alerts.append((w, kw))
    )
    return TickRig(ticker, store, starter, flags, rig.clock, alerts)


# --- the issuer check on the harness tick route (design decision 7) ---------------------------------------------------


def _harness_client(verifier: FakeOidcVerifier):
    rig = make_rig()
    wiring = TickWiring(verifier=verifier, audience=AUDIENCE, service_account=SCHEDULE_SA, ticker=rig.ticker)
    return TestClient(create_app(schedule_tick=wiring)), rig


@pytest.mark.parametrize("issuer", [GOOGLE_ISSUER, "accounts.google.com"])
def test_FR_AGT_14_the_harness_tick_accepts_both_google_issuer_spellings(issuer: str) -> None:
    verifier = FakeOidcVerifier()
    client, rig = _harness_client(verifier)
    response = client.post("/internal/schedules/tick", headers=bearer(verifier.register(SCHEDULE_SA, iss=issuer)))
    assert (response.status_code, response.json()) == (200, {"fired": 1})
    assert len(rig.starter.started) == 1


@pytest.mark.parametrize(
    "issuer",
    [
        "https://evil.example.com",
        "http://accounts.google.com",
        "https://accounts.google.com.evil.test",
        "",
        "ACCOUNTS.GOOGLE.COM",
    ],
)
def test_FR_AGT_14_the_harness_tick_refuses_any_other_issuer_even_with_the_right_account(issuer: str) -> None:
    verifier = FakeOidcVerifier()
    client, rig = _harness_client(verifier)
    token = verifier.register(SCHEDULE_SA, iss=issuer)
    response = client.post("/internal/schedules/tick", headers=bearer(token))
    assert response.status_code in (401, 403)
    assert token not in response.text and "iam.gserviceaccount.com" not in response.text
    assert rig.starter.attempts == []


def test_FR_AGT_14_the_harness_tick_refuses_a_token_with_no_issuer_claim() -> None:
    verifier = FakeOidcVerifier()
    client, rig = _harness_client(verifier)
    token = verifier.register(SCHEDULE_SA)
    verifier._claims[token].pop("iss")  # type: ignore[attr-defined,union-attr]  # noqa: SLF001
    assert client.post("/internal/schedules/tick", headers=bearer(token)).status_code in (401, 403)
    assert rig.starter.attempts == []
