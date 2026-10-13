"""SEC-16 / GOLIVE-935 (BQ-SEC16-1, BQ-GOLIVE935-4): every live model call is a unit on the uid ledger.

Pinned (`tilo_api.spend_units`, `deps.get_router`, `deps.get_safety`, the run seams):

* a live call reserves BEFORE the provider is reached and settles after it, from the usage the provider reported and
  `config/prices.yaml` (never less than one paisa; unpriced settles the whole reserve); nothing that reached a model
  is released, and a failure, an exception or a cancellation releases the hold: no reservation leaks;
* a refused unit (the uid at its cap, the run's cap, the durable switch, a ledger that cannot be read) never reaches the
  provider: its mock records zero calls;
* every path that gets its providers from the deps seams is metered by construction: the Director's brief and the
  approaches (`POST /intake`, `/tasks/{id}/approaches`), the intake safety screen, the plan compile, the run units and
  the must-ask judge; deployed and live with no meter (no uid, no ledger, unreadable team limits, the tick) the
  providers are the replay ones, never unmetered live ones;
* Quick and the Meeting Hall hold their own unit, so they get the Router unmetered and hold exactly one.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from _clint1_lib import APPROACHES_REPLY, RoleScriptedProvider, brief_reply, build_router
from _sec15_lib import REPO_ROOT
from _sec16_lib import AT, JUDGE_A, ORG, SpyLedger, make_caps, make_ledger
from test_SEC_16_api_spend_cap import BIG_LIMIT, assert_cap_refusal, declared, fill

UNIT = 100  # `_sec16_lib.DEFAULT_CAPS["unit_reserve_minor"]`


def attempt(**kw: Any) -> Any:
    from tilo_providers.router import RouterAttempt

    return RouterAttempt(**{"profile_id": "flash-38", "provider": "google", "outcome": "ok", **kw})


class FakeRouter:
    """A Router stand-in: records calls and the ledger's state when each arrived."""

    def __init__(self, ledger: Any, *, attempts: Any = None, fail: BaseException | None = None) -> None:
        self.ledger, self.attempts, self.fail, self.calls, self.held_at_call = ledger, attempts, fail, [], []

    def generate(self, role: str, request: Any, **kw: Any) -> Any:
        self.calls.append(("generate", role))
        self.held_at_call.append(self.ledger.spent_minor(JUDGE_A))
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(attempts=self.attempts or [], budget=None, response=None)

    def search(self, role: str, query: str, **kw: Any) -> Any:
        self.calls.append(("search", role))
        self.held_at_call.append(self.ledger.spent_minor(JUDGE_A))
        return SimpleNamespace(attempts=self.attempts or [], budget=None, search_result=None)

    def embed(self, *a: Any) -> Any:
        raise AssertionError("embed must never be reachable through the meter")


def meter_over(ledger: Any, caps: Any = None, run: str = "r_unit", uid: str = JUDGE_A) -> Any:
    from tilo_api.spend import SpendGuard
    from tilo_api.spend_units import SpendMeter
    from tilo_metering.flags import InMemoryFlagStore
    from tilo_providers.config import load_providers_config

    caps = caps or make_caps(**BIG_LIMIT)
    config = load_providers_config(REPO_ROOT / "config" / "models.yaml", REPO_ROOT / "config" / "prices.yaml")
    guard = SpendGuard(ledger, InMemoryFlagStore(), caps)
    return SpendMeter(guard, uid=uid, run_id=run, org_id=ORG, unit_minor=caps.unit_reserve_minor, config=config)


def metered(raw: Any, ledger: Any, **kw: Any) -> Any:
    from tilo_api.spend_units import MeteredRouter

    return MeteredRouter(raw, meter_over(ledger, **kw))


# --- one unit: reserve before, settle after, release on failure -----------------------------------------------


def test_SEC_16_a_live_call_reserves_before_the_provider_and_settles_what_it_cost():
    ledger = SpyLedger(make_ledger(**BIG_LIMIT))
    router = FakeRouter(ledger, attempts=[attempt(tokens_in=1_000, tokens_out=500)])

    metered(router, ledger).generate("director", object())

    assert router.held_at_call == [UNIT], "the unit was reserved before the call reached the provider"
    # flash-38: (1000 * 0.825 + 500 * 4.125) / 1e6 US$ = 0.0028875, at 8,000 minor units per US$ = 23.1 -> 24 paise
    assert ledger.settled_minor(JUDGE_A) == ledger.spent_minor(JUDGE_A) == 24
    assert [n for n in ledger.names if n in ("reserve", "settle", "release")] == ["reserve", "settle"]


def test_SEC_16_a_call_with_no_reported_usage_settles_the_whole_reserve():
    ledger = make_ledger(**BIG_LIMIT)
    metered(FakeRouter(ledger, attempts=[attempt()]), ledger).generate("director", object())
    assert ledger.settled_minor(JUDGE_A) == UNIT


def test_SEC_16_search_is_a_unit_too_priced_by_its_queries():
    ledger = make_ledger(**BIG_LIMIT)
    router = FakeRouter(
        ledger, attempts=[attempt(profile_id="search-google", search_queries=1, tokens_in=0, tokens_out=0)]
    )
    metered(router, ledger).search("search", "a question")
    assert router.held_at_call == [UNIT]
    assert ledger.settled_minor(JUDGE_A) == 112  # US$14 per 1,000 queries = US$0.014 = 112 paise


def test_SEC_16_a_failed_call_releases_its_hold():
    from tilo_providers.router import RouterError

    ledger = SpyLedger(make_ledger(**BIG_LIMIT))
    failing = FakeRouter(ledger, fail=RouterError("down", [attempt(outcome="error", error_type="QuotaError")]))

    with pytest.raises(RouterError):
        metered(failing, ledger).generate("director", object())

    assert ledger.spent_minor(JUDGE_A) == 0
    assert [n for n in ledger.names if n in ("reserve", "settle", "release")] == ["reserve", "release"]


def test_SEC_16_a_failed_call_that_was_billed_stays_charged():
    from tilo_providers.router import RouterError

    ledger = make_ledger(**BIG_LIMIT)
    failing = FakeRouter(
        ledger, fail=RouterError("bad reply", [attempt(outcome="schema_invalid", tokens_in=1_000, tokens_out=500)])
    )
    with pytest.raises(RouterError):
        metered(failing, ledger).generate("director", object())
    assert ledger.settled_minor(JUDGE_A) == 24


@pytest.mark.parametrize("boom", [RuntimeError("x"), asyncio.CancelledError(), KeyboardInterrupt()])
def test_SEC_16_any_exception_and_a_cancellation_release_the_hold(boom):
    ledger = make_ledger(**BIG_LIMIT)
    with pytest.raises(type(boom)):
        metered(FakeRouter(ledger, fail=boom), ledger).generate("director", object())
    assert ledger.spent_minor(JUDGE_A) == 0


def test_SEC_16_the_meter_exposes_no_unmetered_router_method():
    ledger = make_ledger(**BIG_LIMIT)
    router = metered(FakeRouter(ledger), ledger)
    for name in ("embed", "stream", "_config"):
        assert not hasattr(router, name)
    assert router.raw is not None


# --- a refused unit never reaches the provider -----------------------------------------------------------------


def test_SEC_16_a_uid_at_its_cap_never_reaches_the_provider():
    from tilo_api.spend import SpendCapReached

    caps = make_caps(**BIG_LIMIT)
    ledger = make_ledger(caps)
    held = ledger.reserve(uid=JUDGE_A, run_id="r_x", org_id=ORG, amount_minor=caps.uid_lifetime_minor, at=AT)
    ledger.settle(held, caps.uid_lifetime_minor)
    router = FakeRouter(ledger)

    with pytest.raises(SpendCapReached):
        metered(router, ledger, caps=caps).generate("director", object())

    assert router.calls == []


def test_SEC_16_under_the_cap_with_less_than_a_unit_left_one_call_at_a_time_runs_then_the_uid_is_capped():
    from tilo_api.spend import SpendCapReached

    caps = make_caps(**BIG_LIMIT)
    ledger = make_ledger(caps)
    held = ledger.reserve(uid=JUDGE_A, run_id="r_x", org_id=ORG, amount_minor=caps.uid_lifetime_minor - 50, at=AT)
    ledger.settle(held, caps.uid_lifetime_minor - 50)  # under the cap, but a unit (100) no longer fits
    router = FakeRouter(ledger, attempts=[attempt(tokens_in=1_000, tokens_out=500)])  # a call costs 24 paise
    meter = metered(router, ledger, caps=caps)

    for held_at_call in (caps.uid_lifetime_minor, caps.uid_lifetime_minor, caps.uid_lifetime_minor):
        meter.generate("director", object())  # held for what is left (50, then 26, then 2), settled at 24
        assert router.held_at_call[-1] <= held_at_call, "a hold never takes the uid past its cap"
    assert len(router.calls) == 3
    assert ledger.spent_minor(JUDGE_A) == caps.uid_lifetime_minor - 50 + 3 * 24  # over by less than one call (22)

    with pytest.raises(SpendCapReached):
        meter.generate("director", object())
    assert len(router.calls) == 3, "once capped the provider is never reached"


def test_SEC_16_the_durable_switch_never_reaches_the_provider():
    from tilo_api.deps import ReplayOnly

    ledger = make_ledger(**BIG_LIMIT)
    ledger.trip_replay_only("test")
    router = FakeRouter(ledger)
    with pytest.raises(ReplayOnly):
        metered(router, ledger).generate("director", object())
    assert router.calls == []


def test_SEC_16_the_runs_cap_never_reaches_the_provider():
    from tilo_api.deps import ReplayOnly

    caps = make_caps(**BIG_LIMIT, run_minor=150)
    ledger = make_ledger(caps)
    router = FakeRouter(ledger, attempts=[attempt()])
    first = metered(router, ledger, caps=caps)
    first.generate("director", object())  # settles the whole reserve: 100 of the run's 150
    with pytest.raises(ReplayOnly):
        first.generate("director", object())
    assert len(router.calls) == 1


def test_SEC_16_an_unreadable_ledger_never_reaches_the_provider():
    from _sec16_lib import DeadLedger
    from tilo_api.deps import ReplayOnly

    dead = DeadLedger()
    router = FakeRouter(make_ledger(**BIG_LIMIT))
    with pytest.raises(ReplayOnly):
        metered(router, dead).generate("director", object())
    assert router.calls == []


# --- the safety screen -----------------------------------------------------------------------------------------


class Screen:
    def __init__(self, ledger: Any, *, flagged: bool = False, fail: bool = False) -> None:
        self.ledger, self.flagged, self.fail, self.calls, self.held = ledger, flagged, fail, [], []

    def check(self, text: str, **kw: Any) -> Any:
        self.calls.append(text)
        self.held.append(self.ledger.spent_minor(JUDGE_A))
        if self.fail:
            raise ConnectionError("armor down")
        return {"flagged": self.flagged, "reason": "r" if self.flagged else None}

    def redact(self, text: str) -> str:
        return text


def test_SEC_16_a_safety_check_is_a_unit_priced_by_the_tokens_it_screened():
    from tilo_api.spend_units import MeteredSafety

    ledger = make_ledger(**BIG_LIMIT)
    screen = Screen(ledger, flagged=True)
    safety = MeteredSafety(screen, meter_over(ledger))  # type: ignore[arg-type]

    assert safety.check("a" * 3_000)["flagged"] is True  # the verdict passes through

    assert screen.held == [UNIT]
    assert ledger.settled_minor(JUDGE_A) == 1, "1,000 tokens at US$0.10 per million is a paisa: never zero"


def test_SEC_16_a_failed_safety_check_releases_and_a_capped_uid_never_reaches_it():
    from tilo_api.spend import SpendCapReached
    from tilo_api.spend_units import MeteredSafety

    ledger = make_ledger(**BIG_LIMIT)
    down = Screen(ledger, fail=True)
    with pytest.raises(ConnectionError):
        MeteredSafety(down, meter_over(ledger)).check("hello")  # type: ignore[arg-type]
    assert ledger.spent_minor(JUDGE_A) == 0

    caps = make_caps(**BIG_LIMIT)
    full = make_ledger(caps)
    full.settle(
        full.reserve(uid=JUDGE_A, run_id="r", org_id=ORG, amount_minor=caps.uid_lifetime_minor, at=AT),
        caps.uid_lifetime_minor,
    )
    never = Screen(full)
    with pytest.raises(SpendCapReached):
        MeteredSafety(never, meter_over(full, caps)).check("hello")  # type: ignore[arg-type]
    assert never.calls == []


# --- the seams: metered by construction, replay when it cannot be metered --------------------------------------


@pytest.fixture
def wired(sec16_factory, monkeypatch):
    """The deployed harness on its in-memory ledger, with `router_for_mode` and the safety builder replaced by
    counting stand-ins, so a test sees exactly what reached a provider (the `deps` seams are the real ones)."""
    from tilo_api import app, deps

    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    provider = RoleScriptedProvider(brief_reply([]), APPROACHES_REPLY)
    scripted = build_router(REPO_ROOT, provider)
    seen: list[str] = []
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: seen.append(mode) or scripted)
    from _clint1_lib import make_spy_safety

    screen = make_spy_safety()
    monkeypatch.setattr(deps, "build_safety_provider", lambda *a, **kw: screen)
    app.dependency_overrides.pop(deps.get_safety, None)  # the real safety seam, over the counting provider
    return SimpleNamespace(h=h, provider=provider, screen=screen, modes=seen)


def writes(h: Any) -> list[str]:
    return [n for n in h.ledger.names if n in ("reserve", "settle", "release")]


def test_SEC_16_the_director_and_the_safety_screen_of_intake_are_units(wired):
    h = wired.h

    response = h.intake()

    assert response.status_code == 201, response.text
    assert wired.provider.calls, "the Director was called"
    assert wired.screen.calls, "the text was screened"
    ops = writes(h)
    assert ops and ops.count("reserve") == ops.count("settle") + ops.count("release") >= 2
    assert ops[0] == "reserve", "no call before its reservation"
    assert h.ledger.spent_minor(JUDGE_A) == h.ledger.settled_minor(JUDGE_A) > 0, "nothing is left held"


def test_SEC_16_approaches_are_units_too(wired):
    h = wired.h
    task = h.intake().json()
    before = writes(h).count("reserve")

    approaches = h.client.get(f"/tasks/{task['task_id']}/approaches")

    assert approaches.status_code == 200, approaches.text
    assert writes(h).count("reserve") > before
    assert h.ledger.spent_minor(JUDGE_A) == h.ledger.settled_minor(JUDGE_A)


def test_SEC_16_a_cap_reached_inside_one_request_refuses_the_next_before_any_provider_call(wired):
    h = wired.h
    fill(h, JUDGE_A, h.caps.uid_lifetime_minor - UNIT // 2)  # live is allowed (under the cap), less than a unit left

    assert h.intake().status_code in (201, 403)  # the last calls run on what is left, then the uid is capped
    calls = (len(wired.provider.calls), len(wired.screen.calls))
    assert h.ledger.spent_minor(JUDGE_A) >= h.caps.uid_lifetime_minor

    assert_cap_refusal(h.intake())
    assert (len(wired.provider.calls), len(wired.screen.calls)) == calls


def test_SEC_16_quick_holds_its_own_unit_and_gets_the_router_unmetered(wired):
    h = wired.h

    h.client.post("/intake", data={"text": "What is a purchase order?", "mode": "quick"})

    # Quick's own one hold for the ask, plus one unit per safety check: never one per model call
    assert h.ledger.names.count("reserve") == 1 + len(wired.screen.calls)
    assert h.ledger.spent_minor(JUDGE_A) == h.ledger.settled_minor(JUDGE_A), "no hold is left open"


def test_SEC_16_deployed_and_live_with_no_ledger_the_providers_are_replay(sec16_factory, monkeypatch):
    from tilo_api import app, deps

    h = sec16_factory(declarations=declared(), ledger=None, **BIG_LIMIT)
    seen: list[str] = []
    monkeypatch.setattr(
        deps,
        "router_for_mode",
        lambda mode: (
            seen.append(mode) or build_router(REPO_ROOT, RoleScriptedProvider(brief_reply([]), APPROACHES_REPLY))
        ),
    )
    forced: list[bool] = []
    monkeypatch.setattr(
        deps, "build_safety_provider", lambda *a, **kw: forced.append(kw.get("force_replay")) or h.safety
    )
    app.dependency_overrides.pop(deps.get_safety, None)

    assert h.intake().status_code == 201
    assert set(seen) == {"replay"} and set(forced) == {True}


def test_SEC_16_the_seams_build_replay_providers_when_deployed_live_has_no_meter(monkeypatch):
    from tilo_api import deps

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    seen: list[str] = []
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: seen.append(mode) or object())

    deps.get_router("live")
    deps._seam_router("live")
    deps._worker_models("live")

    assert seen == ["replay", "replay", "replay"]


def test_SEC_16_off_cloud_run_the_user_own_live_switch_is_unchanged(monkeypatch):
    from tilo_api import deps

    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    raw = object()
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: raw if mode == "live" else None)
    assert deps.get_router("live") is raw


def test_SEC_16_a_meter_makes_the_run_seams_metered(monkeypatch):
    from tilo_api import deps
    from tilo_api.spend_units import MeteredRouter

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: object())
    meter = object()

    models = deps.get_must_ask_providers("live", meter=meter)
    runner = deps.get_unit_runner("live", meter=meter)

    for role_model in models.values():
        assert isinstance(role_model._router, MeteredRouter)
    assert runner.meter is meter
    assert isinstance(deps._seam_router("live", meter), MeteredRouter)
    assert not isinstance(deps._seam_router("live", None), MeteredRouter), "no meter: replay, never a live router"


def test_SEC_16_the_run_binds_a_metered_safety_screen_and_router(monkeypatch):
    from tilo_api import deps
    from tilo_api.run_tools import ApiUnitRunner
    from tilo_api.spend_units import MeteredRouter, MeteredSafety

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: object())
    monkeypatch.setattr(deps, "build_safety_provider", lambda *a, **kw: object())
    run = SimpleNamespace(cap=10.0, store=SimpleNamespace(), world_id="w", seams=None, plan={"units": []}, brief={})
    meter = object()

    bound = ApiUnitRunner({}, mode="live", clock=lambda: None, meter=meter).bind_run(
        run, SimpleNamespace(append=lambda *a: None)
    )  # type: ignore[arg-type]

    assert isinstance(bound.safety, MeteredSafety) and isinstance(bound.router, MeteredRouter)


def test_SEC_16_the_meter_is_never_a_request_input(wired):
    h = wired.h
    response = h.client.post("/intake?meter=1&mode=live", data={"text": "Prepare the weekly supplier summary."})
    assert response.status_code == 201, response.text
    assert h.ledger.names.count("reserve") >= 1
