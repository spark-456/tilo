"""RUN-SPEED (live, 21 Oct 2026, run r_2FZWK8503E9VAD3MHC3XVKF28W on tilo-api 00113): nine units (browser research, a
PDF with figures, a spreadsheet and a website) failed at U7 with "a step's model call did not fit the credits left": the
grant was the 60-credit floor because the Director's estimate under-priced the plan. The confirm card now shows (so a
Start grants) at least what the approach's plan needs for every unit to afford a call, never above one run's ceiling or
the per-user cap. Prices from config/models.yaml and prices.yaml; no model, no network."""

from __future__ import annotations

import copy
import dataclasses
import math

import pytest
from _clint1_lib import Flow, brief_reply, make_spy_safety
from tilo_api import deps, tasks
from tilo_planning.compiler import _with_deliver
from tilo_planning.deliverable_teams import with_design_team
from tilo_planning.grant import NOMINAL_INPUT_CHARS, plan_need
from tilo_providers.router import call_floor

BRIEF = {
    "goal": "Research a topic in the browser and deliver a report, a sheet and a site",
    "deliverables": [
        {"title": "Report with figures", "format": "pdf"},
        {"title": "Data sheet", "format": "xlsx"},
        {"title": "Site", "format": "website"},
    ],
}
APPROACH = {"id": "a1", "dimensions": {"parallelism": 3}, "credits": {"min": 20, "max": 40}}  # under-priced


def _unit(n: int, role: str, after: list[int]) -> dict:
    return {
        "id": f"U{n}", "unit_type": "research" if role == "specialist" else "work", "title": f"Step {n}", "role": role,
        "district": "D1", "skills": [], "connectors": [], "actions": [], "depends_on": [f"U{d}" for d in after],
    }  # fmt: skip


def _live_plan() -> list[dict]:
    """The live run's shape: six Director units (browser and web research, data, figures, a check, a draft), then the
    deliver unit code adds for each of the three deliverables."""
    own = [
        _unit(1, "specialist", []), _unit(2, "specialist", []), _unit(3, "specialist", [1, 2]),
        _unit(4, "specialist", [3]), _unit(5, "verifier", [3, 4]), _unit(6, "writer", [5]),
    ]  # fmt: skip
    return with_design_team(_with_deliver(own, BRIEF), BRIEF)


@pytest.fixture
def floor(monkeypatch):
    monkeypatch.delenv("TILO_MODELS_FILE", raising=False)
    config = deps.providers_config()
    return config, lambda role: call_floor(config, role, NOMINAL_INPUT_CHARS)


def test_RUN_SPEED_the_nine_unit_plan_gets_a_grant_every_unit_can_afford_a_call_from(floor):
    config, least = floor
    plan = _live_plan()
    assert len(plan) == 9 and [u["role"] for u in plan[6:]] == ["writer"] * 3
    every_call = math.fsum(least(u["role"]) for u in plan)  # each unit's least call, all made one after another
    old_grant = max(APPROACH["credits"]["max"], deps.min_run_grant())
    assert old_grant < every_call, "the live failure: the floor grant could not pay one call per unit"

    grant = max(old_grant, tasks._plan_floor(BRIEF, APPROACH, config, config.prices.credit_usd))

    assert grant >= every_call, f"{grant} cannot pay one call for each of the nine units ({every_call})"
    left = grant
    for unit in plan:  # even when every unit before spent its whole least call, the next still affords its own
        assert left >= least(unit["role"]), unit["id"]
        left -= least(unit["role"])
    assert plan_need(plan, least) <= deps.budget_cap_ceiling()


def test_RUN_SPEED_the_plan_grant_never_passes_the_run_ceiling_or_the_per_user_cap(floor, monkeypatch):
    config, _least = floor
    big = {**BRIEF, "deliverables": [{"title": f"Deck {n}", "format": "pptx"} for n in range(5)]}
    widest = {**APPROACH, "dimensions": {"parallelism": 6}}
    assert tasks._plan_floor(big, widest, config, config.prices.credit_usd) == deps.budget_cap_ceiling()
    tight = dataclasses.replace(deps.get_spend_caps(), uid_lifetime_minor=5_000)  # INR 50: ~105 credits at the meter
    monkeypatch.setattr(deps, "get_spend_caps", lambda: tight)
    assert tasks._plan_floor(big, widest, config, config.prices.credit_usd) == pytest.approx(
        5_000 / 9_500 / config.prices.credit_usd
    )
    assert tasks._plan_floor(BRIEF, APPROACH, object(), 0.005) == 0.0, "unpriced (dev): the estimate and floor stand"


def test_RUN_SPEED_the_confirm_card_shows_the_plan_grant_and_a_start_grants_it(repo_root, store):
    flow = Flow(repo_root, store, make_spy_safety(), copy.deepcopy(brief_reply([])))
    try:
        for approach in flow.provider.approaches["approaches"]:
            approach["credits"] = {"min": 3, "max": 8}  # far below what any plan needs
        intake = flow.new_task()
        body = flow.approaches(intake["task_id"]).json()
        config = deps.providers_config()
        brief = flow.store.tasks[intake["task_id"]].brief
        for shown, stored in zip(body["approaches"], flow.store.tasks[intake["task_id"]].approaches, strict=True):
            need = tasks._plan_floor(brief, stored, config, config.prices.credit_usd)
            assert shown["credits"]["max"] == max(8, body["min_grant"], need) and stored["credits"]["max"] == 8
        chosen = next(a for a in body["approaches"] if a["id"] == body["recommended"])
        cap = min(math.ceil(chosen["credits"]["max"]), body["budget_ceiling"])  # what the web's Start sends
        assert flow.approve(intake["task_id"], body["recommended"], cap).status_code == 200
        assert [g["data"]["cap"] for g in flow.events(intake["world_id"], "budget.granted")] == [cap]
    finally:
        flow.close()
