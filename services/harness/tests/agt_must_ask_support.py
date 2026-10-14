"""Shared, non-test support for the FR-AGT-05 acceptance tests (must-ask rules, PRD 8.3, 8.6).

THE INTERFACE THESE TESTS PIN (the PRD names no class; chosen here, logged as BQ-198..BQ-201 in
docs/open-questions.md; a builder implements exactly this in `tilo_harness/must_ask.py`):

    MustAsk(providers, *, config, card_sink, owner="u_owner", covered_actions=())
        providers        Mapping[str, ModelProvider] keyed by role, the shape DefaultUnitRunner takes (PL-01).
                         The assessment of a unit uses providers[unit["role"]].
        config           the loaded AgentsConfig (retries.max_attempts is the PRD 8.3 "fails 3 times").
        card_sink        Callable[[dict], None]: receives each `needs_you` card the harness builds.
        owner            the person a question goes to when no Team Lead is configured (FR-AGT-06 owner fallback).
        covered_actions  action types an autonomy policy already covers (PRD 8.3 "not covered by an autonomy policy").

    await MustAsk.assess(unit, *, failures=0) -> Ask | None
        unit             a plan.schema.json unit (its `title` is the task text, its `actions` the side effects).
        failures         how many times this unit has already failed.
        Returns None when no must-ask rule fires, else an `Ask` with `.reason` (one of agent.escalated's
        reasons: ambiguous_brief, trade_off, sensitive_step, repeated_failure) and `.question` (str).

    MustAsk.raise_question(ask, *, writer, unit, specialist, lead, director, district=None, cause=None) -> dict
        Writes, through `writer`, agent.help_requested (specialist -> lead), agent.escalated (lead ->
        director, data.reason == ask.reason) and question.routed (lead -> a person, data.card_id), in that
        order; submits one needs_you card (contracts/card.schema.json) to card_sink; returns that card.

    run_plan(..., must_ask=MustAsk(...))   (new optional keyword, default None = today's behaviour)
        Before a unit's work runs the executor calls must_ask.assess(unit); on an Ask it calls
        raise_question and does not run the unit now (BQ-201).

THE MODEL REPLY the scripted specialist-role provider gives (what the builder's prompt must ask for;
parsed by the harness): a JSON object
    {"ask": false}
    {"ask": true, "reason": <ambiguous_brief|trade_off|sensitive_step>, "question": str,
     "options": [2 or 3 labels, each at most 20 characters], "suggested": <index into options>, "why": str}
A reply that is not such an object makes the harness ask (ambiguous_brief): it fails toward asking (BQ-199).

Like agt_support, `tilo_harness.must_ask` does not exist yet: it is imported lazily here, so this
file always imports and each test fails on the missing module (or the missing behaviour) only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agt_scripted import ScriptedProvider, role_providers
from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    contract_errors,
    load_config_sync,
    write_agents_config,
)

TASKS_PATH = Path(__file__).resolve().parent / "fixtures" / "must_ask" / "tasks.json"

REASONS = ("ambiguous_brief", "trade_off", "sensitive_step", "repeated_failure")

SPECIALIST = "A_s0"
LEAD = "A_lead"
DIRECTOR = "A_dir"
OWNER = "u_owner"
WORLD = "w_must_ask"


def load_tasks() -> list[dict[str, Any]]:
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]


def tasks_of(kind: str) -> list[dict[str, Any]]:
    return [task for task in load_tasks() if task["kind"] == kind]


def unit_for(task: dict[str, Any], unit_id: str = "U1") -> dict[str, Any]:
    unit = build_unit(unit_id, title=task["title"])
    unit["actions"] = list(task["actions"])
    return unit


def specialist_script(tasks: list[dict[str, Any]]) -> ScriptedProvider:
    """The recorded replies of the specialist-role model: one JSON reply per task title."""
    return ScriptedProvider({task["title"]: json.dumps(task["model_reply"]) for task in tasks})


def layout_for_asks(*, specialists: int = 1, unit_ids: list[str] | None = None) -> dict[str, Any]:
    spec_ids = [SPECIALIST] + [f"A_s{i}" for i in range(1, specialists)]
    return build_layout(
        world_id=WORLD,
        director_id=DIRECTOR,
        district_specs=[{"id": "D1", "lead": LEAD, "specialists": spec_ids, "unit_ids": unit_ids or ["U1"]}],
    )


def make_config(tmp_path: Path, **overrides: Any) -> Any:
    return load_config_sync(write_agents_config(tmp_path / "agents.yaml", **overrides))


def make_must_ask(
    tmp_path: Path,
    specialist: ScriptedProvider,
    *,
    covered_actions: Any = (),
    cards: list[dict[str, Any]] | None = None,
    brief: dict[str, Any] | None = None,
    model_questions: str = "ask",
    **config_overrides: Any,
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """Returns (must_ask, cards_submitted, providers_by_role). `model_questions` defaults to "ask" here, the
    FR-AGT-05 behaviour these suites pin; config/must_ask.yaml's own default is "assume" (BQ-ASSUME-1)."""
    from tilo_harness.must_ask import MustAsk

    sunk: list[dict[str, Any]] = cards if cards is not None else []
    providers = role_providers(specialist=specialist)
    must_ask = MustAsk(
        providers,
        config=make_config(tmp_path, **config_overrides),
        card_sink=sunk.append,
        owner=OWNER,
        covered_actions=frozenset(covered_actions),
        brief=brief,
        model_questions=model_questions,
    )
    return must_ask, sunk, providers


def raise_for(
    must_ask: Any, ask: Any, writer: Any, unit: dict[str, Any], *, cause: str | None = None
) -> dict[str, Any]:
    return must_ask.raise_question(
        ask,
        writer=writer,
        unit=unit,
        specialist=SPECIALIST,
        lead=LEAD,
        director=DIRECTOR,
        district="D1",
        cause=cause,
    )


def card_problems(card: dict[str, Any]) -> list[str]:
    """contracts/card.schema.json errors plus card.rules.md CR-01/CR-02 (the validator-only rules)."""
    problems = contract_errors("card", card)
    ids = [option["id"] for option in card.get("options", [])]
    if len(set(ids)) != len(ids):
        problems.append("CR-02: option ids must be unique")
    if card.get("safe_default") not in ids:
        problems.append("CR-01: safe_default must name one of the options")
    return problems


def plan_for(units: list[dict[str, Any]]) -> dict[str, Any]:
    return build_plan(units)
