"""SEC-16 and FR-MTR-04, the spend ledger: "a lifetime spend cap of 1,000 INR per uid" (SEC-16) and "per-run,
per-user and per-org caps; hard cap triggers the kill switch" (FR-MTR-04, PRD 14.1, 17.3).

`tilo_api.spend.InMemorySpendLedger(caps, *, shared=None)` implements the pinned `SpendLedger` protocol
(API_SEC_16.md): atomic `reserve` then `settle` (or `release` to roll back), all money in integer minor units, one
durable `replay_only` record. `reserve` answers a `Reservation` or a `Refused` (which has `.reason`; a `Reservation`
never does). Written from the PRD text before any builder touches it: tests/SEC-16-spend-caps.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from _sec16_lib import AT, JUDGE_A, JUDGE_B, NEXT_DAY, ORG, OTHER_ORG, make_caps, make_ledger, spend
from hypothesis import given, settings
from hypothesis import strategies as st

BIG = 10**9  # a cap that never binds in a test about another cap


def reserve(ledger, uid=JUDGE_A, amount=100, *, run_id="r_1", org_id=ORG, at=AT):
    return ledger.reserve(uid=uid, run_id=run_id, org_id=org_id, amount_minor=amount, at=at)


def refused(result) -> bool:
    return hasattr(result, "reason")


def only(cap: str, value: int, **more):
    """Caps where just `cap` binds."""
    quiet = {
        "uid_lifetime_minor": BIG,
        "run_minor": BIG,
        "org_day_minor": BIG,
        "global_day_hard_minor": BIG,
        **more,
    }
    quiet[cap] = value
    return make_caps(**quiet)


# --- boundaries: exactly the cap passes, one over is refused, a refusal changes nothing ----------------------------


def test_SEC_16_a_uid_may_spend_exactly_its_lifetime_cap_and_not_one_paisa_more():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))

    first = reserve(ledger, amount=600, run_id="r_1")
    second = reserve(ledger, amount=400, run_id="r_2")  # 600 + 400 = exactly the cap
    assert not refused(first) and not refused(second)
    over = reserve(ledger, amount=1, run_id="r_3")

    assert refused(over) and over.reason == "uid_lifetime"
    assert ledger.spent_minor(JUDGE_A) == 1_000


def test_SEC_16_one_request_over_the_whole_cap_is_refused_on_a_fresh_uid():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    result = reserve(ledger, amount=1_001)
    assert refused(result) and result.reason == "uid_lifetime"
    assert ledger.spent_minor(JUDGE_A) == 0


def test_SEC_16_settled_and_outstanding_both_count_toward_the_cap():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    spend(ledger, JUDGE_A, 700, run_id="r_done")  # settled
    held = reserve(ledger, amount=300, run_id="r_live")  # outstanding

    assert not refused(held)
    assert refused(reserve(ledger, amount=1, run_id="r_x")), "700 settled + 300 held is the cap"
    assert ledger.settled_minor(JUDGE_A) == 700
    assert ledger.spent_minor(JUDGE_A) == 1_000


def test_SEC_16_a_cap_is_for_life_not_for_a_day():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    spend(ledger, JUDGE_A, 1_000, at=AT)

    tomorrow = reserve(ledger, amount=1, at=NEXT_DAY)

    assert refused(tomorrow) and tomorrow.reason == "uid_lifetime", "a lifetime cap does not reset at midnight"


def test_SEC_16_a_refusal_has_no_side_effect():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    spend(ledger, JUDGE_A, 900, run_id="r_1")
    before = (ledger.spent_minor(JUDGE_A), ledger.settled_minor(JUDGE_A), ledger.replay_only())

    for amount in (101, 5_000, BIG):
        assert refused(reserve(ledger, amount=amount, run_id="r_2"))

    assert (ledger.spent_minor(JUDGE_A), ledger.settled_minor(JUDGE_A), ledger.replay_only()) == before
    # and no ghost hold: the 100 that is really left can still be reserved
    assert not refused(reserve(ledger, amount=100, run_id="r_3"))


def test_SEC_16_one_judges_cap_never_touches_another_judge():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    spend(ledger, JUDGE_A, 1_000)

    assert refused(reserve(ledger, JUDGE_A, 1, run_id="r_a"))
    b = reserve(ledger, JUDGE_B, 1_000, run_id="r_b")  # B has the whole cap of their own
    assert not refused(b)
    assert ledger.spent_minor(JUDGE_B) == 1_000 and ledger.spent_minor(JUDGE_A) == 1_000


def test_FR_MTR_04_a_run_cap_binds_per_run_and_a_second_run_has_its_own():
    ledger = make_ledger(only("run_minor", 400))

    assert not refused(reserve(ledger, amount=400, run_id="r_1"))  # exactly the run cap
    over = reserve(ledger, amount=1, run_id="r_1")
    assert refused(over) and over.reason == "run"
    assert not refused(reserve(ledger, amount=400, run_id="r_2")), "the cap is per run, not per person"


def test_FR_MTR_04_the_run_cap_counts_settled_and_outstanding_spend_of_that_run():
    ledger = make_ledger(only("run_minor", 400))
    first = reserve(ledger, amount=250, run_id="r_1")
    ledger.settle(first, 250)
    held = reserve(ledger, amount=150, run_id="r_1")

    assert not refused(held)
    assert refused(reserve(ledger, amount=1, run_id="r_1"))
    ledger.release(held)
    assert not refused(reserve(ledger, amount=150, run_id="r_1")), "a released hold frees the run's budget"


def test_FR_MTR_04_an_org_day_cap_binds_per_org_per_utc_day():
    ledger = make_ledger(only("org_day_minor", 500))

    assert not refused(reserve(ledger, JUDGE_A, 300, run_id="r_1"))
    assert not refused(reserve(ledger, JUDGE_B, 200, run_id="r_2"))  # two people, one org: exactly 500
    over = reserve(ledger, JUDGE_A, 1, run_id="r_3")
    assert refused(over) and over.reason == "org_day"
    assert not refused(reserve(ledger, JUDGE_A, 500, run_id="r_4", org_id=OTHER_ORG)), "another org has its own cap"
    assert not refused(reserve(ledger, JUDGE_A, 500, run_id="r_5", at=NEXT_DAY)), "the next UTC day has its own cap"


def test_FR_MTR_04_a_null_org_cap_means_no_org_cap_but_the_other_caps_still_hold():
    ledger = make_ledger(only("org_day_minor", None, uid_lifetime_minor=1_000))
    assert not refused(reserve(ledger, amount=1_000, run_id="r_1"))
    assert refused(reserve(ledger, amount=1, run_id="r_2"))


def test_FR_MTR_04_the_global_day_cap_refuses_over_it_and_flips_the_kill_switch():
    ledger = make_ledger(only("global_day_hard_minor", 2_000))
    users = [f"u_sec16_{i}" for i in range(4)]

    for i, uid in enumerate(users):
        assert not refused(reserve(ledger, uid, 500, run_id=f"r_{i}")), "up to exactly the hard cap is allowed"
    assert ledger.replay_only() is False, "reserving is not spending: the switch flips on the crossing, not before"
    over = reserve(ledger, "u_sec16_5", 1, run_id="r_x")

    assert refused(over) and over.reason == "global_hard"
    assert ledger.replay_only() is True, "FR-MTR-04: exceeding the hard cap triggers the kill switch"


def test_FR_MTR_04_settling_spend_up_to_the_global_hard_cap_flips_the_kill_switch_once():
    ledger = make_ledger(only("global_day_hard_minor", 1_000))
    a = reserve(ledger, JUDGE_A, 600, run_id="r_a")
    b = reserve(ledger, JUDGE_B, 400, run_id="r_b")
    ledger.settle(a, 600)
    assert ledger.replay_only() is False, "600 of 1,000 is under the hard cap"

    ledger.settle(b, 400)  # the day's settled spend now equals the hard cap

    assert ledger.replay_only() is True


def test_FR_MTR_04_the_global_cap_counts_per_utc_day_but_a_flipped_switch_does_not_reset_with_the_day():
    ledger = make_ledger(only("global_day_hard_minor", 1_000))
    spend(ledger, JUDGE_A, 800, at=AT)
    assert ledger.replay_only() is False
    assert not refused(reserve(ledger, JUDGE_B, 1_000, run_id="r_b", at=NEXT_DAY)), "a new day, a new global total"

    over = reserve(ledger, JUDGE_B, 201, run_id="r_c", at=AT)
    assert refused(over) and over.reason == "global_hard"
    assert ledger.replay_only() is True
    assert refused(reserve(ledger, JUDGE_B, 1, run_id="r_d", at=NEXT_DAY)), (
        "one-way until a human resets it: midnight is not a reset"
    )


# --- settle, release, rollback --------------------------------------------------------------------------------


def test_SEC_16_settling_below_the_reservation_gives_the_difference_back():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    held = reserve(ledger, amount=500)
    assert ledger.spent_minor(JUDGE_A) == 500

    result = ledger.settle(held, 120)

    assert result.overrun is False
    assert ledger.spent_minor(JUDGE_A) == ledger.settled_minor(JUDGE_A) == 120
    assert not refused(reserve(ledger, amount=880, run_id="r_2")), "the 380 not spent is spendable again"


def test_SEC_16_an_actual_above_its_reservation_is_recorded_in_full_and_flagged():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    held = reserve(ledger, amount=300)

    result = ledger.settle(held, 450)

    assert result.overrun is True
    assert ledger.settled_minor(JUDGE_A) == 450, "the real cost is never clipped to the reservation (MT-03)"
    assert refused(reserve(ledger, amount=551, run_id="r_2"))
    assert not refused(reserve(ledger, amount=550, run_id="r_3"))


def test_SEC_16_a_released_reservation_is_rolled_back_completely():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    held = reserve(ledger, amount=1_000)
    assert refused(reserve(ledger, amount=1, run_id="r_2"))

    ledger.release(held)

    assert ledger.spent_minor(JUDGE_A) == ledger.settled_minor(JUDGE_A) == 0
    assert not refused(reserve(ledger, amount=1_000, run_id="r_3"))


def test_SEC_16_a_reservation_settles_or_releases_once_never_twice():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    a, b = reserve(ledger, amount=100, run_id="r_a"), reserve(ledger, amount=100, run_id="r_b")
    ledger.settle(a, 100)
    ledger.release(b)

    with pytest.raises(KeyError):
        ledger.settle(a, 100)
    with pytest.raises(KeyError):
        ledger.release(a)
    with pytest.raises(KeyError):
        ledger.settle(b, 100)
    assert ledger.settled_minor(JUDGE_A) == 100, "a second settle must not double count"


@pytest.mark.parametrize("bad", [1.5, 100.0, -1, True, False, "100", None])
def test_SEC_16_money_is_an_integer_in_minor_units_on_reserve(bad):
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    with pytest.raises((TypeError, ValueError)):
        reserve(ledger, amount=bad)
    assert ledger.spent_minor(JUDGE_A) == 0, "a malformed amount leaves nothing behind"


@pytest.mark.parametrize("bad", [1.5, 100.0, -1, True, "100", None])
def test_SEC_16_money_is_an_integer_in_minor_units_on_settle(bad):
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    held = reserve(ledger, amount=300)
    with pytest.raises((TypeError, ValueError)):
        ledger.settle(held, bad)
    assert ledger.spent_minor(JUDGE_A) == 300, "the hold is still there, unchanged, after a bad settle"
    ledger.settle(held, 300)  # and it can still be settled properly


def test_SEC_16_the_totals_are_integers():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    spend(ledger, JUDGE_A, 333)
    assert type(ledger.spent_minor(JUDGE_A)) is int and type(ledger.settled_minor(JUDGE_A)) is int


def test_SEC_16_a_new_ledger_over_the_same_backing_sees_the_same_totals_and_holds():
    shared: dict = {}
    first = make_ledger(only("uid_lifetime_minor", 1_000), shared=shared)
    spend(first, JUDGE_A, 600)
    held = reserve(first, amount=300, run_id="r_live")

    second = make_ledger(only("uid_lifetime_minor", 1_000), shared=shared)  # a restarted process

    assert second.spent_minor(JUDGE_A) == 900
    assert refused(reserve(second, amount=101, run_id="r_2"))
    second.settle(held, 300)  # the hold from before the restart settles
    assert second.settled_minor(JUDGE_A) == 900 and first.settled_minor(JUDGE_A) == 900


# --- atomicity: concurrent requests cannot overspend ----------------------------------------------------------


def test_SEC_16_fifty_concurrent_reservations_never_overspend_the_lifetime_cap():
    ledger = make_ledger(only("uid_lifetime_minor", 1_000))
    outcomes: list[bool] = []
    gate = threading.Barrier(50)

    def attempt(i: int) -> None:
        gate.wait()
        outcomes.append(not refused(reserve(ledger, amount=100, run_id=f"r_{i}")))

    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(attempt, range(50)))

    assert outcomes.count(True) == 10, f"exactly cap/amount reservations succeed, got {outcomes.count(True)}"
    assert ledger.spent_minor(JUDGE_A) == 1_000


def test_FR_MTR_04_concurrent_reservations_never_overspend_the_run_or_org_caps_either():
    run_ledger = make_ledger(only("run_minor", 400))
    org_ledger = make_ledger(only("org_day_minor", 700))
    results: dict[str, list[bool]] = {"run": [], "org": []}
    gate = threading.Barrier(40)

    def attempt(i: int) -> None:
        gate.wait()
        results["run"].append(not refused(reserve(run_ledger, amount=100, run_id="r_same")))
        results["org"].append(not refused(reserve(org_ledger, f"u_{i}", 100, run_id=f"r_{i}")))

    with ThreadPoolExecutor(max_workers=40) as pool:
        list(pool.map(attempt, range(40)))

    assert results["run"].count(True) == 4
    assert results["org"].count(True) == 7


def test_SEC_16_concurrent_settles_and_releases_keep_the_books_exact():
    ledger = make_ledger(only("uid_lifetime_minor", 10_000))
    holds = [reserve(ledger, amount=100, run_id=f"r_{i}") for i in range(60)]
    assert not any(refused(h) for h in holds)
    gate = threading.Barrier(60)

    def finish(i: int) -> None:
        gate.wait()
        if i % 3 == 0:
            ledger.release(holds[i])
        else:
            ledger.settle(holds[i], 60)

    with ThreadPoolExecutor(max_workers=60) as pool:
        list(pool.map(finish, range(60)))

    assert ledger.settled_minor(JUDGE_A) == 40 * 60
    assert ledger.spent_minor(JUDGE_A) == 40 * 60, "no hold is left outstanding"


_OPS = st.lists(
    st.tuples(
        st.sampled_from(["reserve", "settle", "release"]),
        st.sampled_from([JUDGE_A, JUDGE_B]),
        st.integers(min_value=0, max_value=700),
        st.integers(min_value=0, max_value=100),
    ),
    max_size=60,
)


@settings(max_examples=100, deadline=None)
@given(ops=_OPS)
def test_SEC_16_property_a_uid_never_spends_more_than_its_cap_when_actuals_stay_within_estimates(ops):
    """Model check: after every operation the ledger agrees with a plain-Python model, and no uid's settled plus
    outstanding spend is ever above the lifetime cap (no overrun in this property: settle <= reserve)."""
    cap = 1_000
    ledger = make_ledger(only("uid_lifetime_minor", cap))
    model_settled = {JUDGE_A: 0, JUDGE_B: 0}
    holds: list[tuple[str, int, object]] = []  # (uid, amount, reservation)
    for n, (op, uid, amount, pct) in enumerate(ops):
        outstanding = sum(a for u, a, _ in holds if u == uid)
        if op == "reserve":
            result = reserve(ledger, uid, amount, run_id=f"r_{n}")
            fits = model_settled[uid] + outstanding + amount <= cap
            assert refused(result) != fits, f"op {n}: reserve {amount} with {model_settled[uid] + outstanding} held"
            if not refused(result):
                holds.append((uid, amount, result))
        elif holds:
            hold_uid, hold_amount, reservation = holds.pop(0)
            if op == "settle":
                actual = hold_amount * pct // 100
                ledger.settle(reservation, actual)
                model_settled[hold_uid] += actual
            else:
                ledger.release(reservation)
        for u in (JUDGE_A, JUDGE_B):
            held = sum(a for hu, a, _ in holds if hu == u)
            assert ledger.settled_minor(u) == model_settled[u]
            assert ledger.spent_minor(u) == model_settled[u] + held <= cap
