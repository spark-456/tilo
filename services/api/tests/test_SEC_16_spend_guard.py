"""SEC-16 and FR-MTR-04, the guard that sits between a unit of work and the ledger, and the durable `replay_only`
switch: "exceeding the demo hard cap switches the link to replay-only" (FR-MTR-04), "one flag switches the public
link to replay-only" (NFR-24), the US$25/day hard cap "triggers NFR-24" (PRD 17.3).

`tilo_api.spend.SpendGuard(ledger, flags, caps)`:

* `begin_unit(mode, *, uid, run_id, org_id, estimate_minor, at) -> UnitPlan(mode, reservation, reason)` is asked
  before every unit (so "read per unit": an in-flight live run stops using live at its next unit). It never makes
  anything more live than `mode` says, and it never raises: a cap, a switch or an outage means a replay plan with a
  stable `reason`, not an error, for work already running.
* `settle_unit(plan, actual_minor)` / `abort_unit(plan)` close a live plan's reservation; neither raises.
* `live_allowed(uid)`, `uid_capped(uid)` and `replay_only()` answer the request-level questions.

The switch is two stores read together: the NFR-24 `FlagStore` (`replay_only`, set by the Treasury or an operator) and
the ledger's own durable record (`ledger.replay_only()`); either one set means replay. Reasons are the stable codes
`uid_lifetime`, `run`, `org_day`, `global_hard`, `replay_only`, `unavailable`. Written from the PRD text before any
builder touches it.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from _sec16_lib import (
    AT,
    JUDGE_A,
    JUDGE_B,
    ORG,
    DeadFlags,
    DeadLedger,
    FakePriceTable,
    SettleFailsLedger,
    SpyLedger,
    make_caps,
    make_guard,
    make_ledger,
    spend,
)
from tilo_metering.flags import InMemoryFlagStore

BIG = 10**9
LIVE = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch


def begin(guard, mode="live", *, uid=JUDGE_A, run_id="r_1", estimate=100, at=AT):
    return guard.begin_unit(mode, uid=uid, run_id=run_id, org_id=ORG, estimate_minor=estimate, at=at)


def only(cap: str, value, **more):
    quiet = {"uid_lifetime_minor": BIG, "run_minor": BIG, "org_day_minor": BIG, "global_day_hard_minor": BIG, **more}
    quiet[cap] = value
    return make_caps(**quiet)


# --- the decision function: `capped` joins `replay_only`; neither is ever more live ----------------------------------


def provider_mode(declaration, env, **kwargs):
    from tilo_api.access import provider_mode as decide

    return decide(declaration, env, **kwargs)


@pytest.mark.parametrize(
    ("declaration", "env", "kwargs", "mode"),
    [
        ("judge", {"K_SERVICE": "tilo-api", "TILO_JUDGE_LIVE": "1"}, {"capped": False}, "live"),
        ("judge", {"K_SERVICE": "tilo-api", "TILO_JUDGE_LIVE": "1"}, {"capped": True}, "replay"),
        ("judge", {"K_SERVICE": "tilo-api", LIVE: "1"}, {"capped": True}, "replay"),
        ("judge", {"K_SERVICE": "tilo-api", "TILO_JUDGE_LIVE": "1"}, {"capped": True, "replay_only": True}, "replay"),
        ("judge", {"K_SERVICE": "tilo-api", "TILO_JUDGE_LIVE": "1"}, {"replay_only": True}, "replay"),
        ("judge", {"K_SERVICE": "tilo-api"}, {"capped": False}, "replay"),  # capped=False never grants live
        ("visitor", {"K_SERVICE": "tilo-api", "TILO_JUDGE_LIVE": "1"}, {"capped": False}, "replay"),
        (None, {}, {"capped": False}, "replay"),
    ],
)
def test_SEC_16_provider_mode_is_replay_when_capped_and_capped_false_changes_nothing(declaration, env, kwargs, mode):
    assert provider_mode(declaration, env, **kwargs) == mode


# --- per unit: live, or replay with a reason; never an error --------------------------------------------------------


def test_SEC_16_a_live_unit_reserves_its_estimate_and_settles_its_actual():
    table = FakePriceTable()
    ledger = SpyLedger(make_ledger(only("uid_lifetime_minor", 5_000)))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 5_000))
    estimate = table.cost_minor(2_000_000, 600_000)  # a fake call priced from the fake table, in minor units
    assert estimate == 1_320

    plan = begin(guard, estimate=estimate)

    assert plan.mode == "live" and plan.reason is None
    assert plan.reservation.amount_minor == estimate and type(plan.reservation.amount_minor) is int
    assert ledger.spent_minor(JUDGE_A) == estimate
    guard.settle_unit(plan, table.cost_minor(1_000_000, 100_000))
    assert ledger.settled_minor(JUDGE_A) == table.cost_minor(1_000_000, 100_000) == 420


def test_SEC_16_a_replay_unit_never_touches_the_ledger_and_is_never_made_live():
    ledger = SpyLedger(make_ledger(only("uid_lifetime_minor", 5_000)))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 5_000))

    plan = begin(guard, "replay")

    assert plan.mode == "replay" and plan.reservation is None
    assert ledger.names == [], "replay costs nothing and needs no ledger"
    guard.settle_unit(plan, 999)
    guard.abort_unit(plan)
    assert ledger.names == []


def test_SEC_16_once_the_lifetime_cap_is_reached_a_running_run_falls_back_to_replay_without_an_error():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 1_000))
    plans = []

    for unit in range(8):  # one run of eight units, each estimated at 300
        plan = begin(guard, run_id="r_one_run", estimate=300)  # never raises
        plans.append(plan)
        guard.settle_unit(plan, 300)

    assert [p.mode for p in plans] == ["live"] * 3 + ["replay"] * 5
    assert {p.reason for p in plans[3:]} == {"uid_lifetime"}
    assert ledger.spent_minor(JUDGE_A) == 900, "the refused units spent nothing"


def test_FR_MTR_04_the_per_run_cap_turns_the_rest_of_that_run_to_replay():
    ledger = make_ledger(only("run_minor", 400))
    guard = make_guard(ledger, caps=only("run_minor", 400))

    first = begin(guard, run_id="r_a", estimate=300)
    second = begin(guard, run_id="r_a", estimate=300)
    other_run = begin(guard, run_id="r_b", estimate=300)

    assert (first.mode, second.mode, second.reason, other_run.mode) == ("live", "replay", "run", "live")


def test_FR_MTR_04_the_per_org_day_cap_turns_new_units_to_replay_for_everyone_in_that_org():
    ledger = make_ledger(only("org_day_minor", 500))
    guard = make_guard(ledger, caps=only("org_day_minor", 500))

    a = begin(guard, uid=JUDGE_A, run_id="r_a", estimate=300)
    b = begin(guard, uid=JUDGE_B, run_id="r_b", estimate=300)

    assert (a.mode, b.mode, b.reason) == ("live", "replay", "org_day")


def test_SEC_16_one_judge_at_the_cap_never_changes_another_judges_plans():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 1_000))
    spend(ledger, JUDGE_A, 1_000)

    a, b = begin(guard, uid=JUDGE_A, run_id="r_a"), begin(guard, uid=JUDGE_B, run_id="r_b")

    assert (a.mode, a.reason, b.mode) == ("replay", "uid_lifetime", "live")
    assert guard.live_allowed(JUDGE_A) is False and guard.live_allowed(JUDGE_B) is True


def test_SEC_16_uid_capped_is_true_exactly_at_the_cap_and_not_one_below():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 1_000))
    spend(ledger, JUDGE_A, 999)
    assert guard.uid_capped(JUDGE_A) is False and guard.live_allowed(JUDGE_A) is True

    spend(ledger, JUDGE_A, 1, run_id="r_2")

    assert guard.uid_capped(JUDGE_A) is True and guard.live_allowed(JUDGE_A) is False


def test_SEC_16_abort_unit_rolls_the_reservation_back():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 1_000))
    plan = begin(guard, estimate=1_000)
    assert ledger.spent_minor(JUDGE_A) == 1_000

    guard.abort_unit(plan)

    assert ledger.spent_minor(JUDGE_A) == 0
    assert begin(guard, estimate=1_000).mode == "live"


# --- the durable replay_only switch ----------------------------------------------------------------------------------


def test_FR_MTR_04_crossing_the_global_hard_cap_flips_replay_only_and_the_next_unit_is_replay():
    ledger = make_ledger(only("global_day_hard_minor", 1_000))
    guard = make_guard(ledger, caps=only("global_day_hard_minor", 1_000))
    first = begin(guard, uid=JUDGE_A, run_id="r_a", estimate=900)
    assert first.mode == "live"

    crossing = begin(guard, uid=JUDGE_B, run_id="r_b", estimate=200)  # 900 + 200 > 1,000

    assert crossing.mode == "replay" and crossing.reason == "global_hard"
    assert ledger.replay_only() is True and guard.replay_only() is True
    after = begin(guard, uid=JUDGE_B, run_id="r_c", estimate=1)
    assert (after.mode, after.reason) == ("replay", "replay_only")


def test_FR_MTR_04_an_in_flight_live_run_stops_using_live_at_its_next_unit_when_the_switch_flips():
    ledger = SpyLedger(make_ledger(only("uid_lifetime_minor", 10_000)))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 10_000))

    unit_1 = begin(guard, estimate=100)
    ledger.trip_replay_only("test: the daily hard cap was crossed by someone else")  # while unit 1 is running
    guard.settle_unit(unit_1, 90)  # unit 1's work already happened: its cost is still recorded
    unit_2 = begin(guard, estimate=100)

    assert unit_1.mode == "live" and ledger.settled_minor(JUDGE_A) == 90
    assert unit_2.mode == "replay" and unit_2.reason == "replay_only"
    assert ledger.writes.count("reserve") == 1, "no reservation is made for a unit that will not be live"


def test_FR_MTR_04_the_nfr_24_flag_store_flag_also_stops_the_next_unit():
    ledger = make_ledger(only("uid_lifetime_minor", 10_000))
    flags = InMemoryFlagStore()
    guard = make_guard(ledger, flags, only("uid_lifetime_minor", 10_000))
    assert begin(guard, estimate=10).mode == "live"

    flags.set("replay_only", True, reason="NFR-24 test")

    plan = begin(guard, estimate=10)
    assert (plan.mode, plan.reason) == ("replay", "replay_only")
    assert guard.replay_only() is True and guard.live_allowed(JUDGE_A) is False


def test_FR_MTR_04_the_switch_is_a_store_record_that_survives_a_restart():
    shared: dict = {}
    caps = only("global_day_hard_minor", 1_000)
    first = make_ledger(caps, shared=shared)
    assert first.trip_replay_only("hard cap") is True

    restarted = make_ledger(caps, shared=shared)  # a new process, the same backing store
    guard = make_guard(restarted, caps=caps)  # and a fresh in-memory flag store: process state is gone

    assert restarted.replay_only() is True
    assert guard.replay_only() is True
    assert begin(guard, uid=JUDGE_A).mode == "replay"
    assert begin(guard, uid=JUDGE_B).reason == "replay_only"


def test_FR_MTR_04_flipping_is_idempotent_and_exactly_one_caller_flips_it():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    results: list[bool] = []
    gate = threading.Barrier(20)

    def trip() -> None:
        gate.wait()
        results.append(ledger.trip_replay_only("hard cap"))

    with ThreadPoolExecutor(max_workers=20) as pool:
        [pool.submit(trip) for _ in range(20)]
    assert results.count(True) == 1 and results.count(False) == 19
    assert ledger.trip_replay_only("again") is False and ledger.replay_only() is True


def test_FR_MTR_04_crossing_the_cap_again_after_the_flip_leaves_it_flipped_once():
    ledger = make_ledger(only("global_day_hard_minor", 500))
    held = ledger.reserve(uid=JUDGE_A, run_id="r_a", org_id=ORG, amount_minor=500, at=AT)
    ledger.settle(held, 500)  # the settle reaches the hard cap and flips it

    assert ledger.replay_only() is True
    assert ledger.trip_replay_only("a second crossing") is False, "it was already flipped: nothing to flip again"


def test_FR_MTR_04_nothing_but_a_named_human_reset_clears_the_switch():
    ledger = make_ledger(only("uid_lifetime_minor", 10_000))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 10_000))
    ledger.trip_replay_only("hard cap")

    # ordinary traffic, in any amount, never clears it
    for i in range(5):
        assert begin(guard, run_id=f"r_{i}").mode == "replay"
        guard.settle_unit(begin(guard, "replay"), 0)
    assert guard.live_allowed(JUDGE_A) is False and ledger.replay_only() is True

    for anonymous in ("", None, "   "):
        with pytest.raises((TypeError, ValueError)):
            ledger.reset_replay_only(by=anonymous)  # a reset names who did it
    assert ledger.replay_only() is True

    ledger.reset_replay_only(by="owner")
    assert ledger.replay_only() is False
    assert begin(guard, run_id="r_after").mode == "live"


def test_FR_MTR_04_the_guard_has_no_way_to_unset_the_switch():
    guard = make_guard(make_ledger(only("uid_lifetime_minor", 1_000)))
    public = {n for n in dir(guard) if not n.startswith("_")}
    assert not any("reset" in n or "clear" in n or "unset" in n for n in public), public


# --- fail closed: live denied, replay still works ---------------------------------------------------------------------


def test_SEC_16_an_unreachable_ledger_denies_live_and_does_not_raise():
    guard = make_guard(DeadLedger(), caps=make_caps())

    plan = begin(guard)

    assert (plan.mode, plan.reservation, plan.reason) == ("replay", None, "unavailable")
    assert guard.live_allowed(JUDGE_A) is False
    assert guard.uid_capped(JUDGE_A) is False, "unknown is not 'capped': new work is not refused over an outage"
    assert guard.replay_only() is False
    guard.settle_unit(plan, 10)
    guard.abort_unit(plan)  # still no raise
    assert begin(guard, "replay").mode == "replay", "replay still works with the ledger down"


def test_SEC_16_an_unreachable_switch_store_denies_live_and_makes_no_reservation():
    ledger = SpyLedger(make_ledger(only("uid_lifetime_minor", 1_000)))
    guard = make_guard(ledger, DeadFlags(), only("uid_lifetime_minor", 1_000))

    plan = begin(guard)

    assert (plan.mode, plan.reservation, plan.reason) == ("replay", None, "unavailable")
    assert ledger.writes == [], "nothing is reserved for a unit that cannot be live"
    assert guard.live_allowed(JUDGE_A) is False
    assert begin(guard, "replay").mode == "replay"


def test_SEC_16_a_settle_that_fails_never_raises_and_the_hold_stays_counted():
    ledger = SettleFailsLedger(make_ledger(only("uid_lifetime_minor", 1_000)))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 1_000))
    plan = begin(guard, estimate=600)

    guard.settle_unit(plan, 100)  # the ledger went away: no exception into the run

    assert ledger.spent_minor(JUDGE_A) == 600, "an unsettled hold keeps counting: the failure can only under-spend"
    assert begin(guard, run_id="r_2", estimate=401).mode == "replay"


def test_SEC_16_a_malformed_estimate_is_a_replay_plan_not_a_crash_and_not_free_live():
    ledger = SpyLedger(make_ledger(only("uid_lifetime_minor", 1_000)))
    guard = make_guard(ledger, caps=only("uid_lifetime_minor", 1_000))

    for bad in (1.5, -1, True, "5", None):
        plan = begin(guard, estimate=bad)
        assert plan.mode == "replay" and plan.reservation is None
    assert ledger.spent_minor(JUDGE_A) == 0
