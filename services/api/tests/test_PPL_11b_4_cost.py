"""PPL-11b slice 11b-4, FR-PA-19 panel cost (API_PPL_11b.md sections 9 and 10.4; EFF-01, EFF-03, FR-MTR-06): the
assistant is cheap by construction. Rules answer first; the `assistant` model role is asked only when no rule
reads the question, with the per-call caps 8,000 tokens in and 1,000 out (a call over its cap is compacted or
refused, never silently sent); each call reserves its worst case against a 50-credit daily allowance per person
(UTC day) BEFORE it is sent, atomically; after the allowance only rule answers; a cache holds MODEL decisions only,
in a per-person partition keyed on the person and every input the model saw, and a hit is vetted again; a hit
saves its origin cost and writes `memory.hit`.

Most tests drive the real `MeteredDecider` over a fake inner decider (so this slice runs beside 11b-3); the
per-call-cap and wiring tests use the real `ModelDecider`, the real `Router` and a scripted provider (needs 11b-3).
No network, no paid call, no `LIVE`.

Written before any implementation: every test fails today (`tilo_api.assistant.metering` does not exist).
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import hashlib
import json
import os
import re

import pytest
import yaml
from _ppl11b_lib import (
    CALL_COST,
    DECLINES,
    NOW,
    PRIYA,
    REPO_ROOT,
    SAM,
    UNMATCHED,
    UNMATCHED_2,
    WORST_CASE,
    FakeInner,
    FakeSafety,
    LockedEventWriter,
    ScriptedDecider,
    ScriptedProvider,
    add_hours,
    assert_body_shape,
    assert_events_valid,
    build_world,
    decision,
    intent_context,
    load_intents,
    load_questions,
    make_model_rig,
    make_plate,
    make_providers_config,
    make_router,
    mod,
    model_decision,
    navigate_to,
    plate_s0,
    plate_s1,
    plate_s2,
    priced_intent,
    principal,
    request_size,
    run_answer,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from _ppl11b_lib import world as world  # noqa: PLC0414  (the fixture)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_api import deps

DAY = NOW[:10]
CAP = 50.0
DECLINE = json.dumps({"choice": "decline"})


def _ok(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert_body_shape(body)
    return body


def _config():
    return mod("tilo_api.assistant.config").load_assistant_config()


class Metered:
    """A `MeteredDecider` over a fake inner decider, with its own ledger and cache (both inspectable)."""

    def __init__(self, inner, *, ledger=None, cache=None):
        m, cfg = mod("tilo_api.assistant.metering"), _config()
        self.inner = inner
        self.ledger = ledger or m.InMemorySpendLedger()
        self.cache = cache or m.InMemoryDecisionCache(
            per_user_entries=cfg.cache_per_user_entries, ttl_hours=cfg.cache_ttl_hours
        )
        self.decider = m.MeteredDecider(inner, ledger=self.ledger, cache=self.cache, config=cfg)

    def decide(self, ask):
        return self.decider.decide(ask)

    def preload(self, user, day, amount):
        """Makes `spent(user, day) == amount` through the ledger's own API."""
        reservation = self.ledger.reserve(user, day, amount, 1e9)
        assert reservation is not None
        self.ledger.commit(reservation, amount)


def _ask_for(world, question=UNMATCHED, *, plate=None, user=SAM, record=None, route="/plate", now=NOW):
    spy = ScriptedDecider(default=decision("decline"))
    run_answer(world, plate or plate_s1(), question, decider=spy, user=user, record=record, route=route, now=now)
    return spy.asks[0]


# --------------------------------------------------------------------------------------------- A19-1 config
def _yaml(name):
    return yaml.safe_load((REPO_ROOT / "config" / name).read_text(encoding="utf-8"))


def test_FR_PA_19_A19_1_the_assistant_role_is_the_cheapest_json_profile_that_is_not_a_fake():
    prices = _yaml("prices.yaml")["profiles"]
    for name in ("models.yaml", "models.gemini.yaml"):
        models = _yaml(name)
        candidates = {
            p: prices[p]["input"] + prices[p]["output"]
            for p, doc in models["profiles"].items()
            if "json" in doc["caps"] and doc["provider"] != "fake"
        }
        cheapest = min(candidates, key=candidates.get)
        assert models["roles"]["assistant"]["primary"] == cheapest, name


def test_FR_PA_19_A19_1_every_models_file_caps_the_role_at_8000_in_1000_out_with_a_fallback():
    seen = []
    for path in sorted((REPO_ROOT / "config").glob("models*.yaml")):
        roles = yaml.safe_load(path.read_text(encoding="utf-8"))["roles"]
        if "assistant" not in roles:
            continue
        seen.append(path.name)
        role = roles["assistant"]
        assert (role["max_input_tokens"], role["max_output_tokens"]) == (8000, 1000), path.name
        assert role.get("fallback"), f"{path.name}: NFR-25 wants a fallback on every role"
    assert {"models.yaml", "models.gemini.yaml"} <= set(seen)


def test_FR_PA_19_A19_1_the_dev_profile_has_no_assistant_role_and_the_daily_cap_is_50():
    assert "assistant" not in _yaml("models.dev.yaml")["roles"]
    assert _yaml("assistant.yaml")["cost"]["user_day_credits"] == 50
    assert _config().user_day_credits == 50


def test_FR_PA_19_A19_1_the_dev_profile_gives_no_decider_so_the_dev_panel_is_rules_only(monkeypatch):
    monkeypatch.setenv("TILO_MODELS_FILE", str(REPO_ROOT / "config" / "models.dev.yaml"))
    assert deps.get_assistant_decider() is None


# --------------------------------------------------------------------------------------------- the factory (wiring)
def _wire_models(monkeypatch, tmp_path, replies=(), **kw):
    providers = make_providers_config(tmp_path)
    provider = ScriptedProvider("ast-main", replies, **kw)
    router = make_router(providers, provider)
    monkeypatch.setattr(deps, "providers_config", lambda: providers)
    monkeypatch.setattr(deps, "get_router", lambda: router)
    monkeypatch.setattr(deps, "get_safety", lambda: FakeSafety())
    for cached in (deps.get_spend_ledger, deps.get_decision_cache):
        cached.cache_clear()
    return providers, provider


@pytest.fixture(autouse=False)
def _fresh_process_state():
    yield
    for name in ("get_spend_ledger", "get_decision_cache"):
        getattr(getattr(deps, name, None), "cache_clear", lambda: None)()


def test_FR_PA_19_the_ledger_and_the_cache_are_process_wide_in_memory_objects(_fresh_process_state):
    m = mod("tilo_api.assistant.metering")
    assert deps.get_spend_ledger() is deps.get_spend_ledger()
    assert deps.get_decision_cache() is deps.get_decision_cache()
    assert isinstance(deps.get_spend_ledger(), m.InMemorySpendLedger)
    assert isinstance(deps.get_decision_cache(), m.InMemoryDecisionCache)


def test_FR_PA_19_the_factory_builds_the_metered_model_decider_or_none(monkeypatch, tmp_path, _fresh_process_state):
    m = mod("tilo_api.assistant.metering")
    _wire_models(monkeypatch, tmp_path)
    assert isinstance(deps.get_assistant_decider(), m.MeteredDecider)
    from fastapi import HTTPException  # noqa: PLC0415

    def unavailable():
        raise HTTPException(status_code=503, detail="not configured")

    monkeypatch.setattr(deps, "get_router", unavailable)
    assert deps.get_assistant_decider() is None
    monkeypatch.setattr(deps, "get_router", lambda: object())
    monkeypatch.setattr(deps, "get_safety", unavailable)
    assert deps.get_assistant_decider() is None
    monkeypatch.setattr(deps, "get_safety", lambda: FakeSafety())
    monkeypatch.setattr(deps, "providers_config", lambda: make_providers_config(tmp_path / "x", max_in=None))
    assert deps.get_assistant_decider() is None, "a role with no caps is unusable: rules only"


def test_FR_PA_19_end_to_end_a_real_decider_prices_a_call_and_the_second_ask_is_a_cache_hit(
    rig_factory, monkeypatch, tmp_path, _fresh_process_state
):
    providers, provider = _wire_models(monkeypatch, tmp_path, [json.dumps({"choice": "intent", "intent": "pins"})])
    rig = rig_factory(decider=None)
    rig.unwire("get_assistant_decider")
    first = _ok(rig.ask(UNMATCHED))
    assert (first["outcome"], first["decided_by"], first["cached"]) == ("answered", "model", False)
    assert first["cost"]["model_calls"] == 1 and first["cost"]["credits"] == pytest.approx(CALL_COST)
    assert deps.get_spend_ledger().spent(SAM, DAY) == pytest.approx(CALL_COST)
    second = _ok(rig.ask(UNMATCHED))
    assert second["cached"] is True and second["cost"]["model_calls"] == 0 and second["cost"]["credits"] == 0.0
    assert second["cost"]["saved_credits"] == pytest.approx(first["cost"]["credits"])
    assert second["text"] == first["text"] and len(provider.calls) == 1
    hit = rig.events()[-1]
    assert hit["type"] == "memory.hit" and hit["data"]["saved"] == pytest.approx(CALL_COST)
    assert deps.get_spend_ledger().spent(SAM, DAY) == pytest.approx(CALL_COST), "a hit costs nothing"


def test_FR_PA_19_end_to_end_the_daily_cap_is_enforced_by_the_real_wiring(
    rig_factory, monkeypatch, tmp_path, _fresh_process_state
):
    providers, provider = _wire_models(monkeypatch, tmp_path, default=DECLINE)
    rig = rig_factory(decider=None)
    rig.unwire("get_assistant_decider")
    ledger = deps.get_spend_ledger()
    reservation = ledger.reserve(SAM, DAY, CAP - WORST_CASE + 0.001, 1e9)
    ledger.commit(reservation, CAP - WORST_CASE + 0.001)
    over = _ok(rig.ask(UNMATCHED))
    assert (over["text"], over["decided_by"], over["cost"]["model_calls"]) == (DECLINES["budget"], "rules", 0)
    assert _ok(rig.ask("What is on my plate?"))["outcome"] == "answered", "the rule answers keep working"
    assert provider.calls == []


def test_FR_PA_19_A19_7_the_dev_profile_panel_answers_unmatched_questions_unknown_with_no_call(
    rig_factory, monkeypatch, _fresh_process_state
):
    assert os.environ.get("LIVE") != "1", "EFF-01: no test runs live"
    monkeypatch.setenv("TILO_MODELS_FILE", str(REPO_ROOT / "config" / "models.dev.yaml"))
    rig = rig_factory(decider=None)
    rig.unwire("get_assistant_decider")
    body = _ok(rig.ask(UNMATCHED))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", DECLINES["unknown"])
    assert body["cost"] == {"model_calls": 0, "credits": 0.0, "saved_credits": 0.0}
    assert _ok(rig.ask("What is on my plate?"))["outcome"] == "answered"


# --------------------------------------------------------------------------------------------- the ledger
def _ledger():
    return mod("tilo_api.assistant.metering").InMemorySpendLedger()


def test_FR_PA_19_ledger_reserves_up_to_the_cap_inclusive_and_nothing_beyond():
    ledger = _ledger()
    a = ledger.reserve(SAM, DAY, 30.0, CAP)
    assert a is not None and ledger.reserve(SAM, DAY, 20.001, CAP) is None
    b = ledger.reserve(SAM, DAY, 20.0, CAP)
    assert b is not None and a != b and ledger.reserve(SAM, DAY, 0.001, CAP) is None
    assert ledger.spent(SAM, DAY) == 0.0, "`spent` counts committed spend only"


def test_FR_PA_19_ledger_commit_adds_the_actual_and_frees_the_rest_release_adds_nothing():
    ledger = _ledger()
    a = ledger.reserve(SAM, DAY, 4.0, CAP)
    ledger.commit(a, 0.432)
    assert ledger.spent(SAM, DAY) == pytest.approx(0.432)
    b = ledger.reserve(SAM, DAY, 4.0, CAP)
    ledger.release(b)
    assert ledger.spent(SAM, DAY) == pytest.approx(0.432)
    assert ledger.reserve(SAM, DAY, CAP - 0.432, CAP) is not None, "what was reserved and not spent is free again"


def test_FR_PA_19_ledger_ignores_a_reservation_that_is_unknown_or_already_closed():
    ledger = _ledger()
    a = ledger.reserve(SAM, DAY, 4.0, CAP)
    ledger.commit(a, 1.0)
    ledger.commit(a, 1.0)
    ledger.release(a)
    ledger.commit("not-a-reservation", 9.0)
    ledger.release("not-a-reservation")
    assert ledger.spent(SAM, DAY) == 1.0


def test_FR_PA_19_ledger_keeps_each_person_and_each_utc_day_apart():
    ledger = _ledger()
    ledger.commit(ledger.reserve(SAM, DAY, 40.0, CAP), 40.0)
    assert ledger.reserve(SAM, DAY, 20.0, CAP) is None
    assert ledger.reserve(PRIYA, DAY, 20.0, CAP) is not None
    assert ledger.reserve(SAM, "2026-10-07", 20.0, CAP) is not None
    assert (ledger.spent(SAM, DAY), ledger.spent(PRIYA, DAY), ledger.spent(SAM, "2026-10-07")) == (40.0, 0.0, 0.0)


def test_FR_PA_19_ledger_a_provider_that_reports_more_usage_is_committed_in_full_and_closes_the_day():
    ledger = _ledger()
    ledger.commit(ledger.reserve(SAM, DAY, 4.0, CAP), 51.0)
    assert ledger.spent(SAM, DAY) == 51.0 and ledger.reserve(SAM, DAY, 0.001, CAP) is None


def test_FR_PA_19_ledger_many_threads_never_hold_more_than_the_cap_at_once():
    ledger, granted = _ledger(), []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: ledger.reserve(SAM, DAY, 1.0, 10.0), range(64)))
    granted = [r for r in results if r is not None]
    assert len(granted) == 10 and len(set(granted)) == 10, "exactly the cap, each reservation its own id"
    for r in granted:
        ledger.commit(r, 0.9)
    assert ledger.spent(SAM, DAY) == pytest.approx(9.0)


@settings(max_examples=150, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(["reserve", "commit", "release"]), st.integers(1, 20)), max_size=40))
def test_FR_PA_19_property_committed_plus_open_never_passes_the_cap(ops):
    ledger, open_amounts = _ledger(), {}
    for op, n in ops:
        if op == "reserve":
            rid = ledger.reserve(SAM, DAY, float(n), CAP)
            if rid is not None:
                open_amounts[rid] = float(n)
        elif open_amounts:
            rid = sorted(open_amounts)[n % len(open_amounts)]
            amount = open_amounts.pop(rid)
            ledger.commit(rid, min(amount, float(n))) if op == "commit" else ledger.release(rid)
        assert ledger.spent(SAM, DAY) + sum(open_amounts.values()) <= CAP + 1e-9


# --------------------------------------------------------------------------------------------- the cache
def _cache(**kw):
    return mod("tilo_api.assistant.metering").InMemoryDecisionCache(
        per_user_entries=kw.get("entries", 64), ttl_hours=kw.get("ttl", 24)
    )


def _value(**kw):
    m = mod("tilo_api.assistant.metering")
    base = {"choice": "intent", "intent": "plate", "action": None, "origin_cost": 0.4, "stored_at": NOW}
    return m.CachedDecision(**{**base, **kw})


def test_FR_PA_19_A19_5_one_persons_cache_can_never_serve_another():
    cache = _cache()
    cache.put(SAM, "k", _value())
    assert cache.get(SAM, "k", NOW) == _value()
    assert cache.get(PRIYA, "k", NOW) is None
    cache.put(PRIYA, "k", _value(intent="pins"))
    assert cache.get(SAM, "k", NOW).intent == "plate" and cache.get(PRIYA, "k", NOW).intent == "pins"


def test_FR_PA_19_A19_5_an_entry_older_than_the_ttl_is_a_miss():
    cache = _cache(ttl=24)
    cache.put(SAM, "k", _value())
    assert cache.get(SAM, "k", add_hours(NOW, 23)) is not None
    assert cache.get(SAM, "k", add_hours(NOW, 25)) is None


def test_FR_PA_19_the_cache_is_least_recently_used_per_person():
    cache = _cache(entries=2)
    cache.put(SAM, "k1", _value(intent="plate"))
    cache.put(SAM, "k2", _value(intent="pins"))
    assert cache.get(SAM, "k1", NOW) is not None
    cache.put(SAM, "k3", _value(intent="mail"))
    assert cache.get(SAM, "k2", NOW) is None and cache.get(SAM, "k1", NOW) is not None
    assert cache.get(SAM, "k3", NOW) is not None
    for n in range(5):
        cache.put(PRIYA, f"p{n}", _value())
    assert cache.get(SAM, "k1", NOW) is not None, "another person's traffic never evicts mine"


def test_FR_PA_19_the_cache_hands_out_and_keeps_copies():
    cache = _cache()
    action = navigate_to("plate", {"kind": "work_item", "id": "wi_rate_sheet"})
    cache.put(SAM, "k", _value(choice="navigate", intent=None, action=action))
    action["route"] = "settings"
    got = cache.get(SAM, "k", NOW)
    assert got.action["route"] == "plate"
    got.action["route"] = "autonomy"
    assert cache.get(SAM, "k", NOW).action["route"] == "plate"


def _expected_key(ask, version, fingerprint):
    doc = {
        "v": 1,
        "org": ask.org_id,
        "user": ask.user,
        "q": ask.question_key,
        "screen": ask.screen,
        "context": None if ask.context is None else {"kind": ask.context.kind, "id": ask.context.id},
        "plate": ask.plate_fingerprint,
        "menu": ask.menu.fingerprint,
        "decider": version,
        "config": fingerprint,
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_FR_PA_19_A19_5_the_cache_key_covers_the_person_and_every_input_the_model_saw(world):
    key = mod("tilo_api.assistant.metering").cache_key
    ask = _ask_for(world, record="mt_samsync1")
    assert ask.context is not None
    base = key(ask, decider_version="v1", config_fingerprint="c1")
    assert base == _expected_key(ask, "v1", "c1") and key(ask, decider_version="v1", config_fingerprint="c1") == base
    other_menu = dataclasses.replace(ask.menu, fingerprint="0" * 64)
    variants = {
        "user": dataclasses.replace(ask, user=PRIYA),
        "org": dataclasses.replace(ask, org_id="org_other"),
        "question": dataclasses.replace(ask, question_key="something else"),
        "screen": dataclasses.replace(ask, screen="calendar"),
        "context": dataclasses.replace(ask, context=None),
        "plate": dataclasses.replace(ask, plate_fingerprint="1" * 64),
        "menu": dataclasses.replace(ask, menu=other_menu),
    }
    for name, changed in variants.items():
        assert key(changed, decider_version="v1", config_fingerprint="c1") != base, name
    assert key(ask, decider_version="v2", config_fingerprint="c1") != base
    assert key(ask, decider_version="v1", config_fingerprint="c2") != base
    assert key(dataclasses.replace(ask, now=add_hours(NOW, 3)), decider_version="v1", config_fingerprint="c1") == base


# --------------------------------------------------------------------------------------------- MeteredDecider
def test_FR_PA_19_a_miss_reserves_the_worst_case_calls_once_commits_the_actual_and_caches(world):
    inner = FakeInner(priced_intent())
    metered = Metered(inner)
    ask = _ask_for(world)
    first = metered.decide(ask)
    assert inner.budgets == [WORST_CASE], "the call's budget is the reservation, sized at the worst case"
    assert (first.choice, first.intent, first.model_calls, first.cached, first.saved) == (
        "intent",
        "plate",
        1,
        False,
        0.0,
    )
    assert first.credits == pytest.approx(CALL_COST)
    assert metered.ledger.spent(SAM, DAY) == pytest.approx(CALL_COST)
    second = metered.decide(ask)
    assert inner.calls == 1
    assert (second.choice, second.intent, second.cached, second.model_calls, second.credits) == (
        "intent",
        "plate",
        True,
        0,
        0.0,
    )
    assert second.saved == pytest.approx(CALL_COST)
    assert metered.ledger.spent(SAM, DAY) == pytest.approx(CALL_COST), "a hit reserves and spends nothing"


CACHEABLE = {
    "intent": lambda: model_decision("intent", intent="pins", credits=0.3),
    "navigate": lambda: model_decision("navigate", action=navigate_to("autonomy"), credits=0.3),
    "decline": lambda: model_decision("decline", credits=0.3),
    "dropped": lambda: model_decision("dropped", credits=0.3),
}
NOT_CACHEABLE = {
    "unavailable": lambda: decision("unavailable", model_calls=2),
    "budget": lambda: decision("budget"),
    "flagged": lambda: decision("flagged"),
    "no_model_call": lambda: decision("intent", intent="plate", model_calls=0),
}


@pytest.mark.parametrize("name", sorted(CACHEABLE))
def test_FR_PA_19_every_model_decision_is_cached_and_comes_back_as_it_was(world, name):
    decided = CACHEABLE[name]()
    metered = Metered(FakeInner(decided))
    ask = _ask_for(world)
    metered.decide(ask)
    hit = metered.decide(ask)
    assert (hit.choice, hit.intent, hit.action, hit.cached, hit.model_calls) == (
        decided.choice,
        decided.intent,
        decided.action,
        True,
        0,
    )
    assert hit.saved == pytest.approx(0.3)


@pytest.mark.parametrize("name", sorted(NOT_CACHEABLE))
def test_FR_PA_19_what_is_not_a_paid_model_decision_is_never_cached(world, name):
    decided = NOT_CACHEABLE[name]()
    inner = FakeInner(decided, default=decided)
    metered = Metered(inner)
    ask = _ask_for(world)
    metered.decide(ask)
    again = metered.decide(ask)
    assert inner.calls == 2 and again.cached is False


def test_FR_PA_19_with_the_allowance_used_up_the_model_is_not_called(world):
    inner = FakeInner(priced_intent())
    metered = Metered(inner)
    metered.preload(SAM, DAY, CAP - WORST_CASE + 0.001)
    got = metered.decide(_ask_for(world))
    assert got.choice == "budget" and inner.calls == 0 and got.model_calls == 0 and got.credits == 0.0


def test_FR_PA_19_A19_4_one_credit_of_room_decides_the_boundary_exactly(world):
    exact = Metered(FakeInner(priced_intent()))
    exact.preload(SAM, DAY, CAP - WORST_CASE)
    assert exact.decide(_ask_for(world)).choice == "intent" and exact.inner.calls == 1
    over = Metered(FakeInner(priced_intent()))
    over.preload(SAM, DAY, CAP - WORST_CASE + 0.001)
    assert over.decide(_ask_for(world)).choice == "budget" and over.inner.calls == 0


def test_FR_PA_19_the_worst_case_is_held_open_while_the_call_is_in_flight(world):
    ledger_box = {}

    def during(ask):
        ledger = ledger_box["ledger"]
        ledger_box["too_much"] = ledger.reserve(SAM, DAY, CAP - WORST_CASE + 0.001, CAP)
        ledger_box["fits"] = ledger.reserve(SAM, DAY, CAP - WORST_CASE, CAP)
        return priced_intent()

    metered = Metered(FakeInner(during))
    ledger_box["ledger"] = metered.ledger
    metered.decide(_ask_for(world))
    assert ledger_box["too_much"] is None, "the reservation was open (at the worst case) before the call"
    assert ledger_box["fits"] is not None


def test_FR_PA_19_an_inner_failure_releases_the_reservation_and_charges_nothing(world):
    metered = Metered(FakeInner(raises=RuntimeError("provider down")))
    got = metered.decide(_ask_for(world))
    assert got.choice == "unavailable" and got.model_calls == 0 and got.credits == 0.0
    assert metered.ledger.spent(SAM, DAY) == 0.0
    assert metered.ledger.reserve(SAM, DAY, CAP, CAP) is not None, "no reservation is left open"


def test_FR_PA_19_an_overrun_is_committed_in_full_and_the_next_call_is_refused(world):
    metered = Metered(FakeInner(model_decision("intent", intent="plate", credits=7.0)))
    metered.preload(SAM, DAY, CAP - 1.5 * WORST_CASE)  # 44.0: room for one worst case (4.0), not for 7.0
    first = metered.decide(_ask_for(world))
    assert first.credits == 7.0 and metered.ledger.spent(SAM, DAY) == CAP - 1.5 * WORST_CASE + 7.0 > CAP
    assert metered.decide(_ask_for(world, UNMATCHED_2)).choice == "budget"


def test_FR_PA_19_the_allowance_is_per_utc_day_and_the_cache_outlives_it_within_the_ttl(world):
    inner = FakeInner(priced_intent())
    metered = Metered(inner)
    late = "2026-10-06T23:59:59.000Z"
    ask = _ask_for(world, now=late)
    metered.decide(ask)
    assert metered.ledger.spent(SAM, "2026-10-06") == pytest.approx(CALL_COST)
    next_day = dataclasses.replace(ask, now="2026-10-07T00:00:01.000Z")
    hit = metered.decide(next_day)
    assert hit.cached is True and metered.ledger.spent(SAM, "2026-10-07") == 0.0
    metered.preload(SAM, "2026-10-07", CAP - WORST_CASE)
    fresh = metered.decide(dataclasses.replace(next_day, question_key="a different question"))
    assert fresh.choice == "intent", "a new UTC day is a new allowance"


def test_FR_PA_19_A19_4_two_concurrent_questions_at_the_edge_make_exactly_one_call(world):
    inner = FakeInner(priced_intent(), priced_intent(), delay_s=0.3)
    metered = Metered(inner)
    metered.preload(SAM, DAY, CAP - 1.5 * WORST_CASE)
    asks = [_ask_for(world, UNMATCHED), _ask_for(world, UNMATCHED_2)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        got = list(pool.map(metered.decide, asks))
    assert sorted(g.choice for g in got) == ["budget", "intent"] and inner.calls == 1
    assert metered.ledger.spent(SAM, DAY) <= CAP


def test_FR_PA_19_A19_4_a_burst_never_has_more_in_flight_than_the_allowance_can_cover(world):
    inner = FakeInner(default=None, delay_s=0.15)
    metered = Metered(inner)
    asks = [dataclasses.replace(_ask_for(world), question_key=f"question number {n}") for n in range(24)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        got = list(pool.map(metered.decide, asks))
    assert inner.max_in_flight <= int(CAP // WORST_CASE) == 12
    assert metered.ledger.spent(SAM, DAY) <= CAP
    assert sum(g.choice == "budget" for g in got) + inner.calls == 24


# --------------------------------------------------------------------------------------------- through the route
def _route(rig_factory, inner, *, plates=None, **kw):
    metered = Metered(inner)
    rig = rig_factory(decider=metered, **({"plates": plates} if plates is not None else {}), **kw)
    rig.writer = LockedEventWriter(rig.store)
    return metered, rig


def _data_without_ids(event):
    return {k: v for k, v in event["data"].items() if k not in ("conversation_id", "message_ref")}


def test_FR_PA_19_A19_5_the_second_identical_question_is_a_hit_that_saves_its_origin_cost(rig_factory):
    metered, rig = _route(rig_factory, FakeInner(priced_intent()))
    first = _ok(rig.ask(UNMATCHED))
    assert (first["cached"], first["decided_by"]) == (False, "model")
    assert first["cost"] == {"model_calls": 1, "credits": pytest.approx(CALL_COST), "saved_credits": 0.0}
    second = _ok(rig.ask(UNMATCHED))
    assert second["cached"] is True and second["decided_by"] == "model"
    assert second["cost"]["model_calls"] == 0 and second["cost"]["credits"] == 0.0
    assert second["cost"]["saved_credits"] == pytest.approx(first["cost"]["credits"]) and first["cost"]["credits"] > 0
    assert metered.inner.calls == 1 and second["text"] == first["text"]
    evs = rig.events()
    assert [e["type"] for e in evs] == [
        "assistant.asked",
        "assistant.replied",
        "assistant.asked",
        "assistant.replied",
        "memory.hit",
    ]
    hit, replied = evs[4], evs[3]
    assert hit["data"] == {"origin_cost": pytest.approx(CALL_COST), "lookup_cost": 0, "saved": pytest.approx(CALL_COST)}
    assert (hit["cause"], hit["actor"], hit["target"], hit["credits"]) == (replied["id"], "A_assistant", SAM, 0)
    assert replied["credits"] == 0 and set(replied["trace"].values()) == {None} and replied["data"]["cached"] is True
    assert evs[1]["credits"] == pytest.approx(CALL_COST)
    assert_events_valid(evs)


def test_FR_PA_19_A19_5_a_changed_input_misses_the_cache(rig_factory):
    metered, rig = _route(rig_factory, FakeInner(default=None))
    _ok(rig.ask(UNMATCHED))
    _ok(rig.ask(UNMATCHED.upper()))  # the same question after normalisation: a hit
    assert metered.inner.calls == 1
    _ok(rig.ask(UNMATCHED, route="/calendar"))  # another screen
    assert metered.inner.calls == 2
    _ok(rig.ask(UNMATCHED, record="wi_budget_notes"))  # another selection
    assert metered.inner.calls == 3
    rows = [dict(r) for r in plate_s1()["rows"]]
    rows[0] = {**rows[0], "title": "A different title"}
    rig.plate_source.plates[SAM] = make_plate(SAM, rows)  # another plate fingerprint
    _ok(rig.ask(UNMATCHED))
    assert metered.inner.calls == 4
    _ok(rig.ask(UNMATCHED_2))  # another question
    assert metered.inner.calls == 5


def test_FR_PA_19_A19_5_two_people_with_equal_plate_fingerprints_never_share_a_cache_entry(rig_factory):
    metered, rig = _route(rig_factory, FakeInner(default=None), plates={SAM: plate_s0(SAM), PRIYA: plate_s0(PRIYA)})
    assert plate_s0(SAM)["fingerprint"] == plate_s0(PRIYA)["fingerprint"]
    sam = _ok(rig.ask(UNMATCHED))
    rig.set_principal(principal(PRIYA))
    priya = _ok(rig.ask(UNMATCHED))
    assert (sam["cached"], priya["cached"]) == (False, False) and metered.inner.calls == 2
    assert priya["cost"]["model_calls"] == 1
    assert [e["type"] for e in rig.events(PRIYA)] == ["assistant.asked", "assistant.replied"]
    rig.set_principal(principal(SAM))
    assert _ok(rig.ask(UNMATCHED))["cached"] is True, "and each person still hits their own entry"
    assert metered.inner.calls == 2


def test_FR_PA_19_A19_5_a_cache_hit_is_vetted_again_like_any_reply(rig_factory):
    m = mod("tilo_api.assistant.metering")
    inner = FakeInner(default=None)
    metered, rig = _route(rig_factory, inner)
    ask = _ask_for(rig.world)
    poisoned = m.CachedDecision(
        choice="navigate",
        intent=None,
        action=navigate_to("plate", {"kind": "work_item", "id": "wi_priya_1"}),
        origin_cost=0.4,
        stored_at=NOW,
    )
    metered.cache.put(
        SAM, m.cache_key(ask, decider_version=inner.version, config_fingerprint=_config().fingerprint), poisoned
    )
    body = _ok(rig.ask(UNMATCHED))
    assert inner.calls == 0, "the poisoned entry was a hit"
    assert (body["outcome"], body["text"], body["ui_action"]) == ("declined", DECLINES["dropped"], None)


def test_FR_PA_19_A19_5_the_core_vets_a_cached_navigate_to_a_ref_the_gate_now_refuses(world):
    action = navigate_to("plate", {"kind": "work_item", "id": "wi_rate_sheet"})
    hit = model_decision("navigate", action=action, cached=True, model_calls=0, saved=0.4)
    refusing = _refusing_gate(world, {("work_item", "wi_rate_sheet")})
    answer = run_answer(world, plate_s1(), UNMATCHED, decider=ScriptedDecider(hit), gate=refusing)
    assert (answer.outcome, answer.decline, answer.ui_action) == ("declined", "dropped", None)
    allowed = run_answer(world, plate_s1(), UNMATCHED, decider=ScriptedDecider(hit))
    assert allowed.outcome == "navigated" and allowed.ui_action == action


def _refusing_gate(world, refused):
    from _ppl11b_lib import make_gate  # noqa: PLC0415

    gate_mod = mod("tilo_api.assistant.gate")

    class RefusingGate(gate_mod.RefGate):
        def allows(self, ref):
            return (ref.kind, ref.id) not in refused and super().allows(ref)

    return make_gate(world, plate_s1(), gate_cls=RefusingGate)


def test_FR_PA_19_the_cache_is_ttl_bound_but_not_day_bound(rig_factory):
    metered, rig = _route(rig_factory, FakeInner(default=None))
    _ok(rig.ask(UNMATCHED))
    rig.now = add_hours(NOW, 23)  # the next UTC day, still inside the 24 h ttl
    assert _ok(rig.ask(UNMATCHED))["cached"] is True and metered.inner.calls == 1
    rig.now = add_hours(NOW, 25)
    assert _ok(rig.ask(UNMATCHED))["cached"] is False and metered.inner.calls == 2


def test_FR_PA_19_rule_answers_never_touch_the_ledger_or_the_cache(rig_factory):
    inner = FakeInner(default=None)
    metered, rig = _route(rig_factory, inner)
    calls = []
    real_get, real_reserve = metered.cache.get, metered.ledger.reserve
    metered.cache.get = lambda *a, **k: calls.append("cache") or real_get(*a, **k)
    metered.ledger.reserve = lambda *a, **k: calls.append("reserve") or real_reserve(*a, **k)
    for q in load_questions():
        _ok(rig.ask(q["text"]))
    for intent in load_intents():
        if intent["by"] == "rules":
            _ok(rig.ask(intent["text"], **intent_context(intent)))
    _ok(rig.ask("What is on Priya's plate?"))
    assert calls == [] and inner.calls == 0 and metered.ledger.spent(SAM, DAY) == 0.0


def test_FR_PA_19_A19_6_at_least_40_of_50_phrasings_make_no_model_call(rig_factory):
    inner = FakeInner(default=model_decision("decline", credits=0.1))
    metered, rig = _route(rig_factory, inner)
    bodies = [_ok(rig.ask(q["text"])) for q in load_questions()]
    bodies += [_ok(rig.ask(i["text"], **intent_context(i))) for i in load_intents()]
    free = sum(b["cost"]["model_calls"] == 0 for b in bodies)
    assert len(bodies) == 50 and free >= 40 and free / 50 >= 0.8
    assert inner.calls == 50 - free
    assert free == 48, "with config/assistant.yaml only intents 27 and 28 need the model"


def test_FR_PA_19_A19_4_after_the_cap_the_rules_still_answer_all_50(rig_factory):
    metered, rig = _route(rig_factory, FakeInner(default=None))
    metered.preload(SAM, DAY, CAP - WORST_CASE + 0.001)
    over = _ok(rig.ask(UNMATCHED))
    assert (over["outcome"], over["decided_by"], over["text"]) == ("declined", "rules", DECLINES["budget"])
    assert over["cost"]["model_calls"] == 0 and metered.inner.calls == 0
    answered = [_ok(rig.ask(q["text"]))["outcome"] for q in load_questions()]
    assert answered == ["answered"] * 20
    navigated = [_ok(rig.ask(i["text"], **intent_context(i)))["outcome"] for i in load_intents() if i["by"] == "rules"]
    assert navigated == ["navigated"] * 28
    assert metered.ledger.spent(SAM, DAY) == pytest.approx(CAP - WORST_CASE + 0.001)


def test_FR_PA_19_A19_4_two_concurrent_panel_questions_at_the_edge_make_one_provider_call(rig_factory):
    inner = FakeInner(priced_intent(), priced_intent(), delay_s=0.3)
    metered, rig = _route(rig_factory, inner)
    metered.preload(SAM, DAY, CAP - 1.5 * WORST_CASE)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(rig.ask, [UNMATCHED, UNMATCHED_2]))
    bodies = [_ok(r) for r in responses]
    assert inner.calls == 1 and sorted(b["text"] == DECLINES["budget"] for b in bodies) == [False, True]
    assert metered.ledger.spent(SAM, DAY) <= CAP


def test_FR_PA_19_a_decider_that_fails_costs_nothing_and_the_answer_is_rules_only(rig_factory):
    metered, rig = _route(rig_factory, FakeInner(raises=RuntimeError("provider down")))
    body = _ok(rig.ask(UNMATCHED))
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", DECLINES["rules_only"])
    assert body["cost"]["credits"] == 0.0 and metered.ledger.spent(SAM, DAY) == 0.0


# ---------------------------------------- A19-2, A19-3 (real decider)
def _real_route(
    rig_factory, tmp_path, replies=(), *, default=None, plates=None, world=None, max_in=8000, count="chars"
):
    mr = make_model_rig(tmp_path, replies, default=default, count=count, max_in=max_in)
    m = mod("tilo_api.assistant.metering")
    cfg = _config()
    ledger = m.InMemorySpendLedger()
    cache = m.InMemoryDecisionCache(per_user_entries=cfg.cache_per_user_entries, ttl_hours=cfg.cache_ttl_hours)
    metered = m.MeteredDecider(mr.decider, ledger=ledger, cache=cache, config=cfg)
    kw = {"decider": metered}
    if plates is not None:
        kw["plates"] = plates
    if world is not None:
        kw["world"] = world
    return mr, ledger, rig_factory(**kw)


def _strip_blocks(prompt):
    prompt = re.sub(r"<<<QUESTION.*?QUESTION>>>", "<<<QUESTION>>>", prompt, flags=re.S)
    return re.sub(r"<<<ROWS.*?ROWS>>>", "<<<ROWS>>>", prompt, flags=re.S)


def test_FR_PA_19_A19_2_a_second_question_in_a_conversation_carries_no_history(rig_factory, tmp_path):
    mr, ledger, rig = _real_route(rig_factory, tmp_path, default=DECLINE, count="words")
    conversation = "01JB5VQ0000000000000009999"
    _ok(rig.ask("zebraquartz what should I look at first?", conversation_id=conversation))
    _ok(rig.ask(UNMATCHED_2, conversation_id=conversation))
    first, second = mr.main.calls
    assert "zebraquartz" in first.prompt and "zebraquartz" not in second.prompt and "zebraquartz" not in second.system
    assert second.system == first.system
    assert _strip_blocks(second.prompt) == _strip_blocks(first.prompt), (
        "system, the delimited question, ROWS: nothing else"
    )
    assert UNMATCHED_2 in second.prompt
    assert all(c.max_output_tokens == 1000 for c in mr.main.calls)


def test_FR_PA_19_A19_3_a_request_over_the_cap_is_compacted_in_the_rows_and_still_answered_by_one_call(
    rig_factory, tmp_path
):
    # the size of the request with an empty ROWS block, on a provider that counts one token per character
    probe, _, probe_rig = _real_route(rig_factory, tmp_path / "probe", default=DECLINE, plates={SAM: plate_s0()})
    _ok(probe_rig.ask(UNMATCHED))
    cap = request_size(probe.main.calls[0]) + 300
    # the same question over 14 rows with 140-character titles, first unconstrained (the fixture is over the cap) ...
    big = plate_s2(build_world(long_titles=True))
    free, _, free_rig = _real_route(
        rig_factory, tmp_path / "free", default=DECLINE, plates={SAM: big}, world=build_world(long_titles=True)
    )
    _ok(free_rig.ask(UNMATCHED))
    assert request_size(free.main.calls[0]) > cap, "the fixture really is over the cap"
    # ... then under the cap
    mr, ledger, rig = _real_route(
        rig_factory,
        tmp_path / "capped",
        default=DECLINE,
        plates={SAM: big},
        world=build_world(long_titles=True),
        max_in=cap,
    )
    body = _ok(rig.ask(UNMATCHED))
    assert (body["decided_by"], body["outcome"]) == ("model", "declined") and len(mr.main.calls) == 1
    sent = mr.main.calls[0]
    assert request_size(sent) <= cap, "EFF-03: a call over its cap is compacted, never sent over it"
    assert UNMATCHED in sent.prompt, "the question is never what gets compacted"
    assert sent.max_output_tokens == 1000


def test_FR_PA_19_A19_3_a_cap_the_fixed_text_alone_exceeds_sends_nothing_and_charges_nothing(rig_factory, tmp_path):
    mr, ledger, rig = _real_route(rig_factory, tmp_path, default=DECLINE, max_in=50)
    body = _ok(rig.ask(UNMATCHED))
    assert mr.main.calls == [], "refused, nothing sent"
    assert (body["outcome"], body["decided_by"], body["text"]) == ("declined", "rules", DECLINES["rules_only"])
    assert body["cost"]["credits"] == 0.0 and body["cost"]["model_calls"] == 0
    assert ledger.spent(SAM, DAY) == 0.0
    assert ledger.reserve(SAM, DAY, CAP, CAP) is not None, "and the reservation was released"


def test_FR_PA_19_the_real_decider_charges_the_actual_cost_through_the_metered_wrapper(rig_factory, tmp_path):
    mr, ledger, rig = _real_route(
        rig_factory, tmp_path, default=json.dumps({"choice": "intent", "intent": "pins"}), count="words"
    )
    first = _ok(rig.ask(UNMATCHED))
    assert first["cost"]["credits"] == pytest.approx(CALL_COST) and ledger.spent(SAM, DAY) == pytest.approx(CALL_COST)
    again = _ok(rig.ask(UNMATCHED))
    assert again["cached"] is True and len(mr.main.calls) == 1
