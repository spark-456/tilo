"""RUN-SPEED live failure (21 Oct 2026, run r_7DNAXPJ0G85M0DPTPKXS2P716Y on tilo-api 00114; SEC-16, GEN-06): three
ready units split the credits too thin for any candidate (a unit failed where one-by-one fitted), and an aborted
spend-ledger transaction became ReplayOnly. Now a call gets at least its need or queues, and a spend check that stays
busy is `SpendCheckUnavailable` (retryable, never replay, nothing sent). No model, no network."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig
from _adr35_l2_fake import OccFirestore, OccTransaction
from _sec16_lib import AT, JUDGE_A, ORG, make_caps, make_ledger
from google.api_core import exceptions as gexc
from test_SEC_16_api_spend_cap import BIG_LIMIT
from test_SEC_16_GOLIVE_935_metering import FakeRouter, attempt, metered
from tilo_api import deps, spend
from tilo_api.run_tools import RunBudget
from tilo_harness.failure import crash_reason
from tilo_metering.flags import InMemoryFlagStore
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import BudgetExceededError, call_floor

NEED, SPEND = 4.0, 3.0  # a call needs 4 free credits to be sent and spends 3: 10 fit three calls one by one


def _quoted(seen: list[float], extra: float = 0.0) -> Any:
    """Priced like the Router's pre-flight: refused (nothing sent) under NEED, else it spends SPEND + `extra`."""

    def method(*, budget: float) -> Any:
        seen.append(budget)
        if budget < NEED:
            raise BudgetExceededError("PL-03: over budget", [SimpleNamespace(error_type="BudgetExceededError")])
        return SimpleNamespace(budget=budget - SPEND - extra)

    return method


def _three_ready_units(budget: RunBudget, method: Any, need: float) -> tuple[list[Any], list[BaseException]]:
    """Three units the plan lets run now (`expect(3)`), started together, each making one call."""
    budget.expect(3)
    results: list[Any] = []
    errors: list[BaseException] = []
    start = threading.Barrier(3)

    def unit() -> None:
        try:
            with budget.unit():
                start.wait(5)
                results.append(budget.call(method, need=need))
        except BaseException as error:  # noqa: BLE001 - reported to the test
            errors.append(error)

    threads = [threading.Thread(target=unit) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert not any(t.is_alive() for t in threads), "a unit never finished: the budget deadlocked"
    return results, errors


@pytest.mark.parametrize("need", [NEED, 0.0], ids=["need_known", "need_too_low"])
def test_RUN_SPEED_LIVE_three_ready_units_that_fit_one_by_one_queue_instead_of_splitting_too_thin(need):
    budget, seen = RunBudget(10), []
    assert 10 / 3 < NEED, "the live shape: a three-way split is under what any candidate needs"

    results, errors = _three_ready_units(budget, _quoted(seen), need=need)

    assert errors == [] and len(results) == 3
    if need:
        assert min(seen) >= NEED and len(seen) == 3, f"each call was handed its need the first time: {seen}"
    else:  # the need is an estimate (the Router counts tokens its own way): a refused share asks again and fits
        assert min(seen) < NEED <= max(seen)
    assert budget.left == pytest.approx(10 - 3 * SPEND) and budget.reserved == pytest.approx(0)
    assert budget.root.holding == 0 and not budget.root.queue


def test_RUN_SPEED_LIVE_a_call_that_does_not_fit_even_alone_still_fails_with_the_budget_reason():
    budget = RunBudget(10)  # each spends 4: two fit one after another, the third cannot even alone

    results, errors = _three_ready_units(budget, _quoted([], extra=1.0), need=NEED)

    assert len(results) == 2 and len(errors) == 1 and isinstance(errors[0], BudgetExceededError)
    assert crash_reason(errors[0]) == rig.BUDGET_LINE
    assert budget.left == pytest.approx(2) and budget.reserved == pytest.approx(0) and budget.root.holding == 0


def test_RUN_SPEED_LIVE_on_the_real_router_three_units_that_fit_one_by_one_all_answer(monkeypatch):
    """A real Router on config/models.yaml and prices.yaml (fake SDK) and the need `deps._call_need` reads from it. A
    third of the cap is refused by the Router itself (the live failure); the three units' calls all answer."""
    monkeypatch.delenv("TILO_MODELS_FILE", raising=False)
    monkeypatch.delenv("LIVE", raising=False)
    router = rig._router(rig.FakeModels())
    request = GenerateRequest(prompt="Research rarely explored stops on the route from Chennai to Gokarna. " * 8)
    need = deps._call_need(router, "specialist", request)
    assert need == router.call_floor("specialist", len(request.prompt)) > 0
    router.generate("specialist", request, budget=need)  # sent at its floor
    cap = 1.5 * need  # one call at a time fits (each spends far less than half its need); a third of it does not
    with pytest.raises(BudgetExceededError):
        router.generate("specialist", request, budget=cap / 3)
    budget, handed = RunBudget(cap), []

    def method(*, budget: float) -> Any:
        handed.append(budget)
        return router.generate("specialist", request, budget=budget)

    results, errors = _three_ready_units(budget, method, need=need)

    assert errors == [] and all(result.response is not None for result, _spent in results) and len(results) == 3
    assert min(handed) >= need - 1e-9, handed
    assert 0 <= budget.left <= cap and budget.reserved == pytest.approx(0)
    assert call_floor(object(), "specialist", 10) == 0.0 and deps._call_need(object(), "writer", request) == 0.0


# --- 2. a contended spend check is asked again, and never replay ---------------------------------------------------


class AbortsFirst:
    """The production in-memory ledger behind a store whose first `count` reserve and spent_minor calls each abort, as
    a Firestore transaction that lost a race to a concurrent unit does (nothing written)."""

    def __init__(self, inner: Any, count: int) -> None:
        self._inner, self.left, self.aborted = inner, {"reserve": count, "spent_minor": count}, []

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)

        def call(*args: Any, **kwargs: Any) -> Any:
            if self.left.get(name, 0) > 0:
                self.left[name] -= 1
                self.aborted.append(name)
                raise gexc.Aborted("409 the transaction was aborted: documents it read changed")
            return target(*args, **kwargs)

        return call if name in self.left else target


@pytest.fixture
def pauses(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(spend.time, "sleep", slept.append)
    return slept


def test_RUN_SPEED_LIVE_an_aborted_spend_transaction_is_asked_again_and_the_call_goes_live(pauses):
    inner = make_ledger(**BIG_LIMIT)
    ledger = AbortsFirst(inner, count=2)
    router = FakeRouter(inner, attempts=[attempt(tokens_in=1_000, tokens_out=500)])

    metered(router, ledger).generate("specialist", object())

    assert router.calls == [("generate", "specialist")], "the unit went live once the store settled"
    assert sorted(set(ledger.aborted)) == ["reserve", "spent_minor"]
    assert pauses == [*spend.STORE_RETRY_DELAYS_S[:2]] * 2, "each check backed off, longer each time"
    assert inner.settled_minor(JUDGE_A) == inner.spent_minor(JUDGE_A) == 28, "one unit, settled once"


def test_RUN_SPEED_LIVE_a_spend_check_that_stays_aborted_is_a_plain_retryable_stop_never_replay(pauses):
    inner = make_ledger(**BIG_LIMIT)
    router = FakeRouter(inner)

    with pytest.raises(spend.SpendCheckUnavailable) as caught:
        metered(router, AbortsFirst(inner, count=99)).generate("specialist", object())

    assert not isinstance(caught.value, deps.ReplayOnly) and router.calls == [], "nothing reached the provider"
    assert len(pauses) == len(spend.STORE_RETRY_DELAYS_S) and inner.spent_minor(JUDGE_A) == 0
    assert crash_reason(caught.value) == spend.SpendCheckUnavailable.plain_reason
    from tilo_api import app

    answer = app.exception_handlers[spend.SpendCheckUnavailable](None, caught.value)  # 503, retry later, not replay
    assert answer.status_code == 503 and answer.headers["Retry-After"] == "5"
    assert json.loads(answer.body) == {"detail": spend.SPEND_CHECK_UNAVAILABLE, "code": "spend_check_unavailable"}


def test_RUN_SPEED_LIVE_a_reserve_is_asked_again_only_after_a_lost_race_and_the_switch_still_wins(pauses):
    caps, ledger, tries = make_caps(**BIG_LIMIT), make_ledger(**BIG_LIMIT), []

    def lost(**_: Any) -> Any:
        tries.append(1)
        raise gexc.ServiceUnavailable("503: the reply was lost")  # the hold may have been written

    ledger.reserve = lost
    guard = spend.SpendGuard(AbortsFirst(ledger, count=1), InMemoryFlagStore(), caps)
    plan = guard.begin_unit("live", uid=JUDGE_A, run_id="r_1", org_id=ORG, estimate_minor=100, at=AT)
    assert plan.reason == "unavailable" and tries == [1], "never reserved twice after a reply that may have written"
    ledger.trip_replay_only("test")
    assert guard.live_check(JUDGE_A) == "replay_only", "the durable switch still wins over a busy store"


class Losing(OccTransaction):
    def _commit(self) -> list:  # the store's first `aborts` commits lose their race (`Aborted`, nothing written)
        if self._db.aborts > 0:
            self._db.aborts -= 1
            self._ops, self.reads, self._id = [], {}, None
            raise gexc.Aborted("409 contention")
        return super()._commit()


class ContendedStore(OccFirestore):
    aborts = 0

    def transaction(self, **_: Any) -> OccTransaction:
        return Losing(self)


def test_RUN_SPEED_LIVE_the_firestore_ledger_rides_out_contention_with_jittered_backoff(monkeypatch):
    from tilo_api import spend_firestore

    slept: list[float] = []
    monkeypatch.setattr(spend_firestore.time, "sleep", slept.append)
    db = ContendedStore()
    db.aborts = 6  # more than the library's five tries for one transaction
    ledger = spend_firestore.FirestoreSpendLedger(db, make_caps(**BIG_LIMIT), org_id=ORG)

    held = ledger.reserve(uid=JUDGE_A, run_id="r_1", org_id=ORG, amount_minor=100, at=AT)

    assert not hasattr(held, "reason") and ledger.spent_minor(JUDGE_A) == 100
    assert len(slept) == 1 and 0.1 <= slept[0] <= 0.3, "one jittered pause before the second try"
    db.aborts = 10_000  # contended for good: an Aborted the guard retries, then fails closed
    with pytest.raises(gexc.Aborted):
        ledger.reserve(uid=JUDGE_A, run_id="r_2", org_id=ORG, amount_minor=100, at=AT)
    assert ledger.spent_minor(JUDGE_A) == 100, "a lost race writes nothing"
