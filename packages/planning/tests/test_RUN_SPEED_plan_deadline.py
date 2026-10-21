"""RUN-SPEED (owner, 21 Oct 2026; FR-INT-09, PL-03): the Director's plan call at run start has a per-call deadline.

Live evidence: the plan call took 86 to 206 s on 21 Oct because one attempt hung about 120 s before a 5xx. With a
deadline the router gives a candidate that has a fallback behind it only its share of the time left, so a hung primary
hands over and the fallback answers. A real Router over a hung primary and an answering fallback; no network.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest
import yaml
from _planning_contracts_lib import (
    _TEST_MODELS_CONFIG,
    _TEST_PRICES_CONFIG,
    ScriptedCall,
    ScriptedModelProvider,
    load_brief_fixture,
)
from test_FR_INT_09_plan_compilation import _inputs, _units
from tilo_planning.brief import complete_brief
from tilo_planning.compiler import PlanCompileError, compile_plan
from tilo_providers.config import load_providers_config
from tilo_providers.router import Deadline, Router

CAP = 42.5


class Hung:
    """A primary that never answers in time (the live 120 s hang): it waits until the test lets it go, then fails."""

    def __init__(self) -> None:
        self.calls, self.release = 0, threading.Event()

    def generate(self, request: Any) -> Any:
        self.calls += 1
        self.release.wait(30)
        raise RuntimeError("answered after the caller had moved on")


def _router(tmp_path, primary: Any, fallback: Any) -> Router:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "models.yaml").write_text(yaml.safe_dump(_TEST_MODELS_CONFIG), encoding="utf-8")
    (config_dir / "prices.yaml").write_text(yaml.safe_dump(_TEST_PRICES_CONFIG), encoding="utf-8")
    config = load_providers_config(config_dir / "models.yaml", config_dir / "prices.yaml")
    return Router(config, provider_for_profile=lambda profile: primary if profile == "large" else fallback)


@pytest.fixture()
def hung():
    primary = Hung()
    yield primary
    primary.release.set()  # the abandoned attempt ends; its answer is dropped


def _compile(router: Router, deadline: Any) -> Any:
    inputs = _inputs()
    approach = next(a for a in inputs.approaches if a["id"] == "quick")
    brief = complete_brief(load_brief_fixture("valid_market_scan"))
    return compile_plan(brief, approach, CAP, inputs, router=router, deadline=deadline)


def test_RUN_SPEED_a_hung_primary_hands_the_plan_to_the_fallback_within_its_share(tmp_path, hung):
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text=json.dumps({"units": _units()}))])
    started = time.monotonic()
    result = _compile(_router(tmp_path, hung, fallback), lambda: Deadline.after(2.0, 0.25))
    elapsed = time.monotonic() - started
    assert result.plan["units"] and hung.calls == 1 and len(fallback.calls) == 1
    attempts = result.runs[0].attempts
    assert [(a.profile_id, a.error_type) for a in attempts][0] == ("large", "AttemptTimeoutError")
    assert attempts[-1].profile_id == "medium" and elapsed < 10.0  # the primary got 0.5 s, never its 30 s hang


def test_RUN_SPEED_each_plan_attempt_gets_a_fresh_deadline(tmp_path):
    looped = _units()
    looped[0]["depends_on"] = [looped[0]["id"]]  # a unit that waits for itself breaks a plan rule: one repair follows
    provider = ScriptedModelProvider(
        "large", [ScriptedCall(text=json.dumps({"units": looped})), ScriptedCall(text=json.dumps({"units": _units()}))]
    )
    made: list[Deadline] = []

    def factory() -> Deadline:
        made.append(Deadline.after(60.0, 0.3))
        return made[-1]

    result = _compile(_router(tmp_path, provider, provider), factory)
    assert result.plan["units"] and len(result.runs) == 2 and len(made) == 2


def test_RUN_SPEED_when_every_candidate_runs_out_of_time_the_plan_fails_plainly_and_soon(tmp_path, hung):
    other = Hung()
    try:
        started = time.monotonic()
        with pytest.raises(PlanCompileError, match="no plan from the Director"):
            _compile(_router(tmp_path, hung, other), lambda: Deadline.after(1.0, 0.3))
        assert time.monotonic() - started < 10.0  # the run's own failure line, not a wait for the 30 s hang
    finally:
        other.release.set()


def test_RUN_SPEED_without_a_deadline_the_call_is_unchanged(tmp_path):
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps({"units": _units()}))])
    result = _compile(_router(tmp_path, provider, provider), None)
    assert result.plan["units"] and len(provider.calls) == 1
