"""Plan compilation (FR-INT-09, PRD 7.1 and 10.4). The Director role drafts the units of the chosen approach through
the provider layer's router (PL-01), which checks the reply's shape. Everything that authorises is code: the plan
is assembled here (approaches and cap from the person's approval, one gate per side-effect action at the tier
the risk table and the connectors give it, never a policy), and `validate_plan` decides whether it is usable, with
the world owner (BQ-72). A plan that breaks a rule is sent back through the router with only the validator's rule
ids and JSON pointers, up to `MAX_ATTEMPTS` calls in all; if none is valid, `PlanCompileError` is raised and
nothing is returned. Every value from the model or the brief reaches a prompt only inside a delimited block."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

import pydantic
from tilo_contracts import PlanUnit
from tilo_policy import RiskTable
from tilo_providers.clock import real_today, time_facts
from tilo_providers.interfaces import Capability, GenerateRequest
from tilo_providers.prompts import load_prompt
from tilo_providers.router import Router, RouterError, RouterResult

from tilo_planning.brief import DIRECTOR_ROLE
from tilo_planning.deliverable_teams import with_design_team
from tilo_planning.plangraph import SCHEMA_RULE, Violation, _floor_tier, validate_plan

PLAN_THINKING = "medium"  # drafting units needs some thought; the model's default (dynamic, high) is billed as output
MAX_ATTEMPTS = 2  # the first draft and one repair, as for approaches (PL-03, PRD 6.6)
MAX_UNITS = 30  # BQ-115: the schema allows 200; the Director drafts a plan a person reads
DELIVER = "deliver"  # BQ-218: the unit type code appends so every run delivers in Tilo (FR-CON-10)
DELIVER_TITLE = "Deliver the finished work"
MAX_PREVIOUS_CHARS = 20_000  # how much of a failed reply goes back, inside its block
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")
_MARKERS = "BRIEF|APPROACH|CATALOGUE|PROBLEMS|PREVIOUS"  # the blocks of plan.md and plan_repair.md
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9_]{1,40}")


class PlanCompileError(Exception):
    """No valid plan could be compiled; nothing is returned."""


_NO_REVISION = {"revises", "change"}  # plan.schema 1.1.0 (ADR-0028): both or neither, so a null is not "neither"


class _Unit(PlanUnit):
    role: Literal["specialist", "writer", "verifier"]  # the roles the harness runs units as


class _Reply(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    units: Annotated[
        list[_Unit], pydantic.Field(min_length=1, max_length=MAX_UNITS - 1)
    ]  # one place is left for the deliver unit


@dataclass(frozen=True)
class PlanInputs:
    """What the plan is built and checked against: the approaches the person saw, the world owner, and the
    registries `validate_plan` takes."""

    approaches: list[dict[str, Any]]
    owner: str
    skills: Mapping[str, str]  # skill id -> one-line description
    connectors: Mapping[str, Any]  # connector id -> connector.schema.json record
    risk_table: RiskTable
    policies: Mapping[str, Any]


@dataclass(frozen=True)
class PlanResult:
    plan: dict[str, Any]
    runs: list[RouterResult]  # every router call, the repair included, for the Trace (PRD 9.3)


def _data(text: str) -> str:
    """Delimited data never closes or opens any block of the prompt, whatever the case, spacing or zero-width
    characters of the attempt (PRD 16.3 item 1)."""
    text = _ZERO_WIDTH.sub("", text)
    text = re.sub(rf"({_MARKERS})\s*>\s*>\s*>", r"\1> > >", text, flags=re.IGNORECASE)
    return re.sub(rf"<\s*<\s*<(\s*)({_MARKERS})", r"< < <\1\2", text, flags=re.IGNORECASE)


def _catalogue(inputs: PlanInputs) -> str:
    connectors = []
    for connector_id, record in sorted(inputs.connectors.items()):
        declared = record.get("actions") if isinstance(record, Mapping) else None
        actions = [
            {"id": a.get("id"), "gate_type": a.get("gate_type"), "description": a.get("description")}
            for a in (declared if isinstance(declared, list) else [])
            if isinstance(a, Mapping)
        ]
        connectors.append({"id": connector_id, "actions": actions})
    skills = [{"id": skill_id, "description": text} for skill_id, text in sorted(inputs.skills.items())]
    return json.dumps({"skills": skills, "connectors": connectors}, ensure_ascii=False, indent=2)


def _pointer(location: Any) -> str:
    """A JSON pointer made of the schema's own names and indexes; anything else is shown as `?`."""
    parts = [str(p) for p in location] if isinstance(location, tuple | list) else str(location).split("/")
    return "/" + "/".join(p if _SAFE_SEGMENT.fullmatch(p) else "?" for p in parts if p != "")


def _line(violation: Violation) -> str:
    """A problem as the Director sees it: the rule id and a pointer, never the model's own words. A plan rule's
    message names only ids the schema's patterns already limit."""
    if violation.rule_id != SCHEMA_RULE:
        return f"{violation.rule_id}: {violation.message}"
    pointer, _, _ = violation.message.partition(": ")
    if "larger than" in violation.message:
        return "schema: the plan is too large"
    if "nested deeper" in violation.message:
        return "schema: the plan is nested too deeply"
    return f"schema: {_pointer(pointer)} does not match the plan schema"


def _gates(units: list[dict[str, Any]], inputs: PlanInputs) -> list[dict[str, Any]]:
    """One gate per side-effect action, guarding every unit that performs it, at the tier the risk table and the
    units' connectors give it. No gate names a policy: the policy engine decides at run time, never the model."""
    guards: dict[str, list[str]] = {}
    for unit in units:
        for action in unit["actions"]:
            guards.setdefault(action, []).append(unit["id"])
    by_id = {unit["id"]: unit for unit in units}
    gates = []
    for number, (action, guarded) in enumerate(guards.items(), start=1):
        gate: dict[str, Any] = {"id": f"G{number}", "action_type": action, "guards": guarded, "policy_ref": None}
        gate["risk_tier"] = _floor_tier(gate, by_id, inputs.risk_table, inputs.connectors)
        gates.append(gate)
    return gates


def _deliver_title(brief: dict[str, Any]) -> str:
    """The brief's first deliverable title (what the person asked for), else a plain default."""
    deliverables = brief.get("deliverables")
    first = deliverables[0].get("title") if isinstance(deliverables, list) and deliverables else None
    return first.strip()[:80] if isinstance(first, str) and first.strip() else DELIVER_TITLE


def _with_deliver(units: list[dict[str, Any]], brief: dict[str, Any]) -> list[dict[str, Any]]:
    """BQ-218: a final unit that waits for every unit nothing else waits for and delivers in Tilo, ungated (no
    action, so no gate). Code adds it, never the model, and only to a plan with no action of its own: a send or
    save already delivers through its gate. A plan that already has a deliver unit (by type) keeps its own."""
    if any(unit["unit_type"] == DELIVER or unit["actions"] for unit in units):
        return units
    needed = {dep for unit in units for dep in unit["depends_on"]}
    leaves = [unit for unit in units if unit["id"] not in needed]
    number = max(int(unit["id"][1:]) for unit in units) + 1
    deliver = {
        "id": f"U{number}", "unit_type": DELIVER, "title": _deliver_title(brief), "role": "writer",
        "district": leaves[-1]["district"] if leaves else units[-1]["district"], "skills": [], "connectors": [],
        "actions": [], "depends_on": [unit["id"] for unit in leaves],
    }  # fmt: skip
    items = brief.get("deliverables")
    items = items if isinstance(items, list) and items else [{"title": _deliver_title(brief)}]
    result = list(units)
    if any(item.get("format") == "app" for item in items) and not any(u["role"] == "verifier" for u in units):
        result.append(
            {
                **deliver,
                "id": f"U{number}",
                "unit_type": "verify",
                "role": "verifier",
                "title": "Verify the source material",
            }
        )
        deliver["depends_on"] = [f"U{number}"]
        number += 1
    for item in items:
        title = item.get("title")
        canva = item.get("format") in ("pptx", "pdf") and item.get("make_with") == "connector:canva"
        result.append(
            {
                **deliver,
                "id": f"U{number}",
                "title": title.strip()[:80] if isinstance(title, str) and title.strip() else DELIVER_TITLE,
                "connectors": ["canva"] if canva else [],
                "actions": ["create_design"] if canva else [],
            }
        )
        number += 1
    return result


def _director_schema() -> dict[str, Any]:
    """The reply schema the Director sees. A revision unit (`revises`, `change`: plan.schema 1.1.0) comes only from a
    confirmed meeting-room change, never from the Director's own plan, so its fields are not offered."""
    schema = _Reply.model_json_schema()
    for definition in schema.get("$defs", {}).values():
        properties = definition.get("properties", {})
        if _NO_REVISION <= properties.keys():
            for name in _NO_REVISION:
                del properties[name]
            definition.pop("description", None)
    return schema


def _ask(router: Router, prompt: str) -> RouterResult:
    request = GenerateRequest(
        system=load_prompt(DIRECTOR_ROLE, "plan_system.md"),
        prompt=prompt,
        json_mode=True,
        response_schema=_director_schema(),
        thinking_level=PLAN_THINKING,
    )
    try:
        run = router.generate(DIRECTOR_ROLE, request, required_capability=Capability.JSON)
    except RouterError as error:
        raise PlanCompileError(f"FR-INT-09: no plan from the Director: {error}") from error
    if run.outcome != "ok" or run.response is None:
        raise PlanCompileError(f"FR-INT-09: the Director's reply was {run.outcome}")
    return run


def compile_plan(
    brief: dict[str, Any],
    approach: dict[str, Any],
    budget_cap: float,
    inputs: PlanInputs,
    *,
    router: Router,
    attempts: int = MAX_ATTEMPTS,
    today: date | None = None,
) -> PlanResult:
    """The PlanGraph for `approach` (one of `inputs.approaches`) under `budget_cap`, valid by `validate_plan`
    for `inputs.owner`, or `PlanCompileError`."""
    approaches = copy.deepcopy(inputs.approaches)
    offered = next((a for a in approaches if a.get("id") == approach.get("id")), None)
    if offered is None:
        raise PlanCompileError("FR-INT-09: the chosen approach is not one of the approaches offered")
    approach = offered  # the text the person saw, never a caller's variant of it
    variables = {
        "brief": _data(json.dumps(brief, ensure_ascii=False, indent=2)),
        "approach": _data(json.dumps(approach, ensure_ascii=False, indent=2)),
        "catalogue": _data(_catalogue(inputs)),
        **time_facts(today or real_today(), brief.get("deadline")),  # calendar facts from the clock, not a guess
    }
    prompt, runs, found = load_prompt(DIRECTOR_ROLE, "plan.md", variables), [], ["none"]
    for attempt in range(attempts):
        run = _ask(router, prompt)
        runs.append(run)
        text = (run.response.text if run.response else None) or ""
        try:
            units = [
                u.model_dump(mode="json", exclude=_NO_REVISION if u.revises is None and u.change is None else None)
                for u in _Reply.model_validate_json(text).units
            ]
        except pydantic.ValidationError as error:
            found = [f"schema: {_pointer(e['loc'])} does not match the units schema" for e in error.errors()[:20]]
        else:
            units = with_design_team(_with_deliver(units, brief), brief)
            plan = {
                "approaches": approaches, "chosen_approach": approach["id"], "units": units,
                "gates": _gates(units, inputs), "budget_cap": budget_cap,
            }  # fmt: skip
            violations = validate_plan(
                plan, risk_table=inputs.risk_table, connectors=inputs.connectors,
                skills=frozenset(inputs.skills), policies=inputs.policies, owner=inputs.owner,
            )  # fmt: skip
            if not violations:
                return PlanResult(plan, runs)
            found = [_line(v) for v in violations[:20]]
        if attempt + 1 < attempts:
            previous = _data(text[:MAX_PREVIOUS_CHARS])
            problems = _data("\n".join(f"- {line}" for line in found))
            repair = {**variables, "problems": problems, "previous": previous}
            prompt = load_prompt(DIRECTOR_ROLE, "plan_repair.md", repair)
    rules = sorted({line.split(":", 1)[0] for line in found})
    raise PlanCompileError(f"FR-INT-09: no valid plan after {attempts} attempts; last broke {', '.join(rules)}")
