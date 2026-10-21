"""RUN-SPEED (owner, 21 Oct 2026): a run's Director plan call and its per-unit must-ask checks carry the Router's own
PL-03 deadline from `config/run_deadlines.yaml`, so a hung attempt hands over to the fallback instead of holding the
run (live: plan calls of 86 to 206 s on 21 Oct, one attempt hanging about 120 s). What is sent, checked and charged is
unchanged; a must-ask check that runs out of time is one the model could not answer (config/must_ask.yaml decides).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from tilo_api import deps
from tilo_api.run_deadlines import SHIPPED, CallDeadline, RunDeadlines, load_run_deadlines
from tilo_providers.router import Deadline, RouterDeadlineError


def test_RUN_SPEED_the_shipped_limits_are_config_and_an_unusable_file_keeps_them(tmp_path):
    assert load_run_deadlines() == RunDeadlines(plan=CallDeadline(180.0, 0.3), must_ask=CallDeadline(45.0, 0.5))
    assert load_run_deadlines() == SHIPPED
    for broken in ("plan: {seconds: 0, first_attempt_share: 0.3}", "plan: [1]", ": not yaml :", ""):
        path = tmp_path / "run_deadlines.yaml"
        path.write_text(broken, encoding="utf-8")
        assert load_run_deadlines(path) == SHIPPED
    path.write_text(
        "plan: {seconds: 99, first_attempt_share: 0.4}\nmust_ask: {seconds: 20, first_attempt_share: 0.6}\n",
        encoding="utf-8",
    )
    assert load_run_deadlines(path) == RunDeadlines(CallDeadline(99.0, 0.4), CallDeadline(20.0, 0.6))


def test_RUN_SPEED_a_call_deadline_starts_fresh_each_time():
    limit = CallDeadline(30.0, 0.25)
    first = limit.start()
    assert isinstance(first, Deadline) and first.first_share == 0.25 and 29.0 < first.remaining() <= 30.0
    assert limit.start() is not first


def test_RUN_SPEED_the_plan_compiler_hands_each_director_call_the_plan_deadline(monkeypatch):
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(deps, "_seam_router", lambda mode, meter=None: object())
    monkeypatch.setattr(
        deps, "compile_plan", lambda *args, **kwargs: seen.append(kwargs) or SimpleNamespace(plan={"units": []})
    )
    compiler = deps.get_plan_compiler()
    assert compiler(brief={}, approach={}, budget_cap=1.0, context=None) == {"units": []}
    (kwargs,) = seen
    deadline = kwargs["deadline"]()
    assert isinstance(deadline, Deadline) and deadline.first_share == SHIPPED.plan.first_attempt_share
    assert SHIPPED.plan.seconds - 1 < deadline.remaining() <= SHIPPED.plan.seconds


class _Router:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    def generate(self, role: str, request: Any, **kwargs: Any) -> Any:
        self.calls.append({"role": role, **kwargs})
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(response=SimpleNamespace(text='{"ask": false}'))


def test_RUN_SPEED_must_ask_models_carry_the_must_ask_deadline_and_unit_models_do_not(monkeypatch):
    router = _Router()
    monkeypatch.setattr(deps, "_seam_router", lambda mode, meter=None: router)
    for model in deps.get_must_ask_providers().values():
        model.generate(SimpleNamespace())
    assert len(router.calls) == 4 and all(isinstance(c["deadline"], Deadline) for c in router.calls)
    assert {c["deadline"].first_share for c in router.calls} == {SHIPPED.must_ask.first_attempt_share}
    router.calls.clear()
    worker = deps._worker_models()["writer"]
    worker.generate(SimpleNamespace())
    assert router.calls == [{"role": "writer"}]  # a unit's own work keeps its unbounded calls (long reports)


def test_RUN_SPEED_a_stand_in_must_ask_model_is_left_as_it_is(monkeypatch):
    stand_in = object()
    monkeypatch.setattr(deps, "_worker_models", lambda mode: {"specialist": stand_in})
    assert deps.get_must_ask_providers() == {"specialist": stand_in}


def test_RUN_SPEED_a_must_ask_check_that_runs_out_of_time_is_one_the_model_could_not_answer(monkeypatch):
    from tilo_harness.config import load_agents_config  # noqa: PLC0415
    from tilo_harness.must_ask import Assumption, MustAsk  # noqa: PLC0415

    router = _Router(fail=RouterDeadlineError("PL-03: role 'specialist' ran out of time", []))
    monkeypatch.setattr(deps, "_seam_router", lambda mode, meter=None: router)
    providers = deps.get_must_ask_providers()
    unit = {"id": "U1", "unit_type": "research", "title": "Read", "role": "specialist", "actions": [], "depends_on": []}
    assume = MustAsk(providers, config=load_agents_config(), card_sink=lambda c: None, model_questions="assume")
    assert asyncio.run(assume.assess(unit)) == Assumption("no_question", "", "no question needed",
                                                          "Assumed: no question needed")  # fmt: skip
    ask = MustAsk(providers, config=load_agents_config(), card_sink=lambda c: None, model_questions="ask")
    asked = asyncio.run(ask.assess(unit))
    assert asked is not None and asked.reason == "ambiguous_brief" and asked.proceed == 1  # asks, never guesses
    with pytest.raises(RouterDeadlineError):
        providers["specialist"].generate(SimpleNamespace())  # the error itself is the router's, unchanged
