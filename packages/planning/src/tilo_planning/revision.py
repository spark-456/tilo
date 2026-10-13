"""Revision planning (MROOM-H2a, ADR-0028 decisions 5, 6 and 8; MR-09, MR-10, MR-11; PG-13). A person confirmed a
change in a meeting room: its units and artifacts are the proposal's own (MR-07). The Director role drafts
revision units only, through the provider layer's router (PL-01). Code does the rest: it keeps the district and
role of the unit each one revises, sets `revises` and `change` itself (the model names the revised unit, never the
change), gives the unit no connector and no action, and runs `validate_plan` with the world's confirmed changes
(PG-01 to PG-13). A reply that names a unit outside the change, an action, connector, tier or policy field, or an
id already used, is a violation sent back for repair and, if it stays, `PlanCompileError`; nothing is dropped
quietly. Nothing in a change sets a gate, a tier or a policy (MR-11): this step adds no gate and the revised plan's
gates are the current plan's.

The person's wording is untrusted data. The caller screens it with the SafetyProvider first (a flagged message
never becomes a proposal, ADR-0028 decision 5); here it only ever reaches a prompt inside a delimited block, cut to
`MAX_WORDING_CHARS`, with every block marker neutralised whatever its case, spacing or zero-width characters.
Starting the units (the owner's in-person grant, MR-10) and writing `plan.revised` are the API's (MROOM-H2b)."""

from __future__ import annotations

import copy
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

import pydantic
from tilo_providers.interfaces import Capability, GenerateRequest
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.router import Router, RouterError, RouterResult

from tilo_planning.brief import DIRECTOR_ROLE
from tilo_planning.compiler import MAX_ATTEMPTS, PLAN_THINKING, PlanCompileError, PlanInputs, _line, _pointer
from tilo_planning.estimate import UnknownUnitTypeError, estimate_units
from tilo_planning.plangraph import Violation, validate_plan

MAX_REVISION_UNITS = 10  # plan.revised.schema.json units.maxItems
MAX_WORDING_CHARS = 4_000
MAX_PREVIOUS_CHARS = 20_000
_MARKERS = ("CHANGE", "PLAN", "WORDING", "PROBLEMS", "PREVIOUS")
_UNIT_ID = "^U[0-9]{1,4}$"


class _RevisionUnit(pydantic.BaseModel):
    """What the Director may say about a revision unit, and nothing else (`extra` is forbidden: an action, connector,
    gate, tier, policy or `change` field is a violation)."""

    model_config = pydantic.ConfigDict(extra="forbid")
    id: Annotated[str, pydantic.Field(pattern=_UNIT_ID)]
    revises: Annotated[str, pydantic.Field(pattern=_UNIT_ID)]
    unit_type: Annotated[str, pydantic.Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    title: Annotated[str, pydantic.Field(min_length=1, max_length=80)]
    skills: Annotated[
        list[Annotated[str, pydantic.Field(max_length=64, pattern="^[a-z][a-z0-9]*([_-][a-z0-9]+)*$")]],
        pydantic.Field(max_length=10),
    ]
    depends_on: Annotated[list[Annotated[str, pydantic.Field(pattern=_UNIT_ID)]], pydantic.Field(max_length=50)]


class RevisionReply(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    units: Annotated[list[_RevisionUnit], pydantic.Field(min_length=1, max_length=MAX_REVISION_UNITS)]


@dataclass(frozen=True)
class RevisionResult:
    plan: dict[str, Any]  # the current plan's units and gates plus the revision units
    revision_units: list[dict[str, str]]  # plan.revised data `units`: [{id, revises}]
    credits: dict[str, float] | None  # the revision's credit range (FR-INT-07), None when a unit type has no history
    runs: list[RouterResult]  # every router call, the repair included, for the Trace (PRD 9.3)


def _fence(text: str) -> str:
    for marker in _MARKERS:
        text = neutralise_marker(text, marker)
    return text


def _summary(unit: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("id", "unit_type", "title", "role", "district", "skills", "depends_on")
    return {key: unit.get(key) for key in keys}


def _problems(reply: RevisionReply, plan: dict[str, Any], change: Mapping[str, Any]) -> list[str]:
    """What breaks the change's own rules (MR-09), as a rule id and a pointer, never the model's words."""
    taken = {unit["id"] for unit in plan["units"]}
    allowed = set(change["units"])
    found, seen = [], set()
    for number, unit in enumerate(reply.units):
        if unit.revises not in allowed:
            found.append(f"MR-09: /units/{number}/revises is not one of the change's units")
        if unit.id in taken or unit.id in seen:
            found.append(f"PG-01: /units/{number}/id is already used")
        seen.add(unit.id)
    return found


def _revised(plan: dict[str, Any], reply: RevisionReply, proposal_id: str) -> dict[str, Any]:
    """The plan with the revision units appended. District and role are the revised unit's; `change` is the
    proposal id the caller confirmed; connectors and actions are empty, so no gate is needed and none is added."""
    revised = copy.deepcopy(plan)
    units = {unit["id"]: unit for unit in revised["units"]}
    for unit in reply.units:
        target = units.get(unit.revises)
        if target is None:  # the change names a unit the plan lacks: caught as PG-13 by the validator
            target = {"district": "D1", "role": "specialist"}
        revised["units"].append({
            "id": unit.id, "unit_type": unit.unit_type, "title": unit.title, "role": target["role"],
            "district": target["district"], "skills": list(unit.skills), "connectors": [], "actions": [],
            "depends_on": list(unit.depends_on), "revises": unit.revises, "change": proposal_id,
        })  # fmt: skip
    return revised


def _known_changes(plan: dict[str, Any], change: Mapping[str, Any]) -> dict[str, set[str]]:
    """Every confirmed change the revised plan refers to: the revision units already in the plan (checked when they
    were added) and this one."""
    known: dict[str, set[str]] = {}
    for unit in plan["units"]:
        if unit.get("revises") is not None and unit.get("change") is not None:
            known.setdefault(unit["change"], set()).add(unit["revises"])
    known.setdefault(change["proposal_id"], set()).update(change["units"])
    return known


def _ask(router: Router, prompt: str) -> RouterResult:
    request = GenerateRequest(
        system=load_prompt(DIRECTOR_ROLE, "revision_system.md"),
        prompt=prompt,
        json_mode=True,
        response_schema=RevisionReply.model_json_schema(),
        thinking_level=PLAN_THINKING,
    )
    try:
        run = router.generate(DIRECTOR_ROLE, request, required_capability=Capability.JSON)
    except RouterError as error:
        raise PlanCompileError(f"MR-09: no revision from the Director: {error}") from error
    if run.outcome != "ok" or run.response is None:
        raise PlanCompileError(f"MR-09: the Director's reply was {run.outcome}")
    return run


def compile_revision(
    plan: dict[str, Any],
    change: Mapping[str, Any],
    wording: str,
    router: Router,
    inputs: PlanInputs,
    attempts: int = MAX_ATTEMPTS,
    *,
    changes: Mapping[str, Collection[str]] | None = None,
) -> RevisionResult:
    """The revised plan for the confirmed `change` (`proposal_id`, `units`, `artifacts`: the meeting.change_requested
    data) and the person's `wording`, valid by `validate_plan(changes=...)` for `inputs.owner`, or `PlanCompileError`.
    `changes` adds the world's earlier confirmed changes the plan's own revision units cannot show; by default they
    are read from those units."""
    current = {unit["id"] for unit in plan["units"]}
    proposal_id, change_units = change["proposal_id"], list(change["units"])
    if not change_units or not set(change_units) <= current:
        raise PlanCompileError("MR-09: the change names a unit the plan does not have")
    variables = {
        "change": _fence(json.dumps({"units": change_units, "artifacts": change.get("artifacts", [])}, indent=2)),
        "plan": _fence(json.dumps([_summary(u) for u in plan["units"]], ensure_ascii=False, indent=2)),
        "wording": _fence(wording[:MAX_WORDING_CHARS]),
    }
    known = {**_known_changes(plan, change), **{k: set(v) for k, v in (changes or {}).items()}}
    known.setdefault(proposal_id, set()).update(change_units)
    prompt, runs, found = load_prompt(DIRECTOR_ROLE, "revision_task.md", variables), [], ["none"]
    for attempt in range(attempts):
        run = _ask(router, prompt)
        runs.append(run)
        text = (run.response.text if run.response else None) or ""
        try:
            reply = RevisionReply.model_validate_json(text)
        except pydantic.ValidationError as error:
            found = [f"schema: {_pointer(e['loc'])} does not match the revision schema" for e in error.errors()[:20]]
        else:
            found = _problems(reply, plan, change)
            if not found:
                revised = _revised(plan, reply, proposal_id)
                violations: list[Violation] = validate_plan(
                    revised, risk_table=inputs.risk_table, connectors=inputs.connectors,
                    skills=frozenset(inputs.skills), policies=inputs.policies, owner=inputs.owner, changes=known,
                )  # fmt: skip
                if not violations:
                    return _result(revised, reply, runs)
                found = [_line(v) for v in violations[:20]]
        if attempt + 1 < attempts:
            repair = {**variables, "problems": _fence("\n".join(f"- {x}" for x in found)),
                      "previous": _fence(text[:MAX_PREVIOUS_CHARS])}  # fmt: skip
            prompt = load_prompt(DIRECTOR_ROLE, "revision_repair.md", repair)
    rules = sorted({line.split(":", 1)[0] for line in found})
    raise PlanCompileError(f"MR-09: no valid revision after {attempts} attempts; last broke {', '.join(rules)}")


def _result(revised: dict[str, Any], reply: RevisionReply, runs: list[RouterResult]) -> RevisionResult:
    added = revised["units"][-len(reply.units) :]
    try:
        credits: dict[str, float] | None = estimate_units(added)["credits"]
    except UnknownUnitTypeError:
        credits = None
    return RevisionResult(revised, [{"id": u["id"], "revises": u["revises"]} for u in added], credits, runs)
