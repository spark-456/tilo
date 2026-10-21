"""RUN-SPEED (owner, 21 Oct 2026; SEC-16, GEN-06): the run's budget no longer holds its lock through a model call.

Before, `RunBudget.call` kept the run's lock while the model answered, so two units that the plan let run at the same
time made their model calls one after another. Now a call reserves under the lock, calls outside it and settles under
it. The cap stays exact: the credits handed out at once never pass what is free, the router never reports spending
more than it was handed, and what a call did not spend goes back. No model, no network.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import threading
import time
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig
from tilo_api.run_tools import ApiUnitRunner, RunBudget
from tilo_planning.compiler import _with_deliver
from tilo_providers.router import BudgetExceededError


def _spender(seen: list[float], *, spend: float | None = None, hold: threading.Event | None = None):
    def method(*, budget: float) -> Any:
        seen.append(budget)
        if hold is not None:
            assert hold.wait(5), "the other call never ran at the same time"
        used = budget if spend is None else min(spend, budget)
        return SimpleNamespace(budget=budget - used)

    return method


def _in_units(budget: RunBudget, count: int, work: Any) -> list[Any]:
    """`count` units running at once, each making one call through `work(i)`."""
    results: list[Any] = [None] * count
    errors: list[BaseException] = []
    started = threading.Barrier(count)

    def unit(i: int) -> None:
        try:
            with budget.unit():
                started.wait(5)
                results[i] = budget.call(work(i))
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    threads = [threading.Thread(target=unit, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors, errors
    return results


def test_RUN_SPEED_two_units_call_the_model_at_the_same_time_and_the_cap_holds():
    budget, seen = RunBudget(10), []
    both = threading.Barrier(2)

    def work(_i: int) -> Any:
        def method(*, budget: float) -> Any:
            seen.append(budget)
            both.wait(5)  # only passes when both calls are inside the model at once
            return SimpleNamespace(budget=0.0)  # each spends all it was handed

        return method

    results = _in_units(budget, 2, work)
    assert sum(seen) <= 10 + 1e-9 and all(s > 0 for s in seen)
    assert budget.left == pytest.approx(10 - sum(s for _r, s in results)) and budget.left >= -1e-9
    assert budget.reserved == pytest.approx(0) and budget.root.holding == 0


def test_RUN_SPEED_many_units_spending_everything_never_pass_the_cap():
    budget = RunBudget(12)
    results = _in_units(budget, 6, lambda i: _spender([]))
    spent = sum(s for _r, s in results)
    assert spent == pytest.approx(12) and budget.left == pytest.approx(0)
    with pytest.raises(ValueError, match="exhausted"):
        budget.call(_spender([]))


def test_RUN_SPEED_a_call_alone_is_handed_everything_free_as_before():
    budget, seen = RunBudget(10), []
    with budget.unit():
        budget.call(_spender(seen, spend=2))
    budget.call(_spender(seen, spend=2))  # outside any unit (a search the run makes): still everything free
    assert seen == [10, 8] and budget.left == 6


def test_RUN_SPEED_a_share_too_small_for_any_candidate_waits_for_the_others_then_asks_for_everything():
    budget = RunBudget(10)
    release, entered = threading.Event(), threading.Event()
    seen_big: list[float] = []

    def holder(*, budget: float) -> Any:
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(budget=budget - 1)  # spends 1 of its share, gives the rest back

    def big(*, budget: float) -> Any:
        seen_big.append(budget)
        if budget < 8:  # the router's pre-flight: no candidate fits, nothing is sent
            raise BudgetExceededError("PL-03: over budget", [SimpleNamespace(error_type="BudgetExceededError")])
        return SimpleNamespace(budget=budget - 3)

    out: dict[str, Any] = {}

    def first() -> None:
        with budget.unit():
            out["first"] = budget.call(holder)

    with budget.unit():  # two units are running
        thread = threading.Thread(target=first)
        thread.start()
        assert entered.wait(5)
        timer = threading.Timer(0.3, release.set)
        timer.start()
        out["big"] = budget.call(big)
        thread.join(5)
    assert seen_big[0] < 8 and seen_big[-1] >= 8  # its share was too small; it waited, then got everything free
    assert out["big"][1] == 3 and out["first"][1] == 1 and budget.left == pytest.approx(6)


def test_RUN_SPEED_a_real_refusal_still_raises_and_a_failed_or_invalid_call_gives_its_credits_back():
    budget = RunBudget(4)

    def refuse(*, budget: float) -> Any:
        raise BudgetExceededError("PL-03: over budget", [SimpleNamespace(error_type="BudgetExceededError")])

    with pytest.raises(BudgetExceededError):
        budget.call(refuse)  # alone and handed everything: nothing more could free up
    with pytest.raises(RuntimeError):
        budget.call(lambda *, budget: (_ for _ in ()).throw(RuntimeError("provider down")))
    for remaining in [-1, 5, float("nan")]:
        with pytest.raises(ValueError, match="budget"):
            budget.call(lambda *, budget, remaining=remaining: SimpleNamespace(budget=remaining))
    assert budget.left == 4 and budget.reserved == 0 and budget.root.holding == 0


def test_RUN_SPEED_a_design_portion_shares_the_runs_lock_and_counts_against_both():
    run = RunBudget(10)
    design = run.portion(0.3)
    results = _in_units(run, 2, lambda i: _spender([], spend=2))  # two units' calls on the run at once
    with design.unit():
        design.call(_spender([], spend=2))
    assert design.root is run and design.lock is run.lock
    assert run.left == pytest.approx(10 - sum(s for _r, s in results) - 2) and design.left == pytest.approx(1)
    assert run.reserved == pytest.approx(0) and design.reserved == pytest.approx(0)


# ---- on the production unit runner ---------------------------------------------------------------------------------


class OverlapModels(rig.FakeModels):
    """The rig's fake SDK, recording how many calls are inside the model at once. Until two have been inside together,
    a call waits (up to 5 s) for a second one to come in: under a budget that held its lock through the call, no
    second call could, so `most` stays 1."""

    def __init__(self) -> None:
        super().__init__()
        self.inside, self.most = 0, 0
        self.met = threading.Condition()

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        with self.met:
            self.inside += 1
            self.most = max(self.most, self.inside)
            self.met.notify_all()
            deadline = time.monotonic() + 5.0
            while self.most < 2 and time.monotonic() < deadline:
                self.met.wait(deadline - time.monotonic())
        try:
            return super().generate_content(model=model, contents=contents, config=config)
        finally:
            with self.met:
                self.inside -= 1


def test_RUN_SPEED_two_independent_units_make_their_model_calls_at_the_same_time(tmp_path, monkeypatch):
    monkeypatch.setattr(rig, "FakeModels", OverlapModels)
    run, state, _asking, models = rig._run(tmp_path, monkeypatch, cap=60)
    plan = run.seams.compiler()
    first = next(u for u in plan["units"] if u["id"] == "U1")
    second = {**copy.deepcopy(first), "id": "U2", "title": "Research the road conditions on the route"}
    plan["units"] = _with_deliver([first, second], run.brief)
    workers = run.seams.runner._providers
    runner = ApiUnitRunner(workers, mode="replay", clock=lambda: date(2026, 10, 21))
    run.seams = dataclasses.replace(run.seams, compiler=lambda **_: copy.deepcopy(plan), runner=runner)
    asyncio.run(asyncio.wait_for(run._execute(), timeout=90))
    events = state.events[rig.WORLD]
    assert [e for e in events if e["type"] == "world.failed"] == [], [
        e["data"] for e in events if e["type"] == "world.failed"
    ]
    assert events[-1]["type"] == "world.completed"
    assert models.most >= 2, "the two units' model calls never overlapped: the budget serialised them"
