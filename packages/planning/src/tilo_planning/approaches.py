"""Approaches (FR-INT-06, PRD 7.1). The Director role proposes two or three approaches for a brief through the
provider layer's router (PL-01), which checks the reply's shape against `plan.schema.json#/$defs/approach`.
Whether the set is usable is deterministic code: every pair differs on at least 2 of the 5 dimensions (PG-08),
ranges are ordered (PG-09) and ids are unique (PG-07). A set that breaks a rule is sent back once through the
router with the problems named; if it still breaks one it is rejected, never returned."""

from __future__ import annotations

import itertools
import json
import math
import re
from dataclasses import dataclass
from typing import Annotated, Any

import pydantic
from tilo_contracts import PlanApproach
from tilo_providers.interfaces import Capability, GenerateRequest
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.router import Router, RouterError, RouterResult

from tilo_planning.brief import DIRECTOR_ROLE
from tilo_planning.events import build_event

DIMENSIONS = ("depth", "sources", "parallelism", "verification", "output_format")
MIN_DIFFERING = 2


class ApproachProposalError(Exception):
    """No usable approach set could be proposed; nothing is returned."""


class _Reply(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    approaches: Annotated[list[PlanApproach], pydantic.Field(min_length=2, max_length=3)]  # PG-12


@dataclass(frozen=True)
class ApproachesResult:
    approaches: list[dict[str, Any]]
    event: dict[str, Any]  # plan.approaches_proposed, returned for the harness to write
    runs: list[RouterResult]  # every router call, the repair included, for the Trace (PRD 9.3)


def differing_dimensions(a: dict[str, Any], b: dict[str, Any]) -> int:
    return sum(1 for key in DIMENSIONS if a["dimensions"][key] != b["dimensions"][key])


def check_distinct(approaches: list[dict[str, Any]]) -> bool:
    """PG-08: every pair differs on at least 2 of the 5 dimensions."""
    return all(differing_dimensions(a, b) >= MIN_DIFFERING for a, b in itertools.combinations(approaches, 2))


def _label(value: Any) -> str:
    """A model-written id as it appears in a problem line: only the id pattern's own characters, never prose."""
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", value) else "?"


def _credit_ok(value: Any, *, positive: bool) -> bool:
    """A finite number of credits (a bool is not one): above 0 for a maximum, 0 or more for a minimum."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return False
    return value > 0 if positive else value >= 0


def problems(approaches: list[dict[str, Any]]) -> list[str]:
    """Every PG-07/08/09 rule the set breaks, in words the Director can act on. Empty when the set is usable."""
    found = []
    ids = [a["id"] for a in approaches]
    if len(set(ids)) != len(ids):
        found.append("PG-07: approach ids must be unique")
    for a, b in itertools.combinations(approaches, 2):
        if (n := differing_dimensions(a, b)) < MIN_DIFFERING:
            found.append(
                f"PG-08: {_label(a['id'])} and {_label(b['id'])} differ on {n} of 5 dimensions; they must differ on 2"
            )
    for a in approaches:
        credits = a["credits"]
        if not (_credit_ok(credits["min"], positive=False) and _credit_ok(credits["max"], positive=True)):
            found.append(f"PG-09: {_label(a['id'])} has credits that are not finite or a maximum that is not above 0")
        elif a["time"]["min_s"] > a["time"]["max_s"] or credits["min"] > credits["max"]:
            found.append(f"PG-09: {_label(a['id'])} has a range whose minimum is above its maximum")
    return found


def _data(text: str, marker: str) -> str:
    """Delimited data never closes its own block (PRD 16.3 item 1)."""
    return neutralise_marker(text, marker)


def _ask(router: Router, prompt: str, budget: float | None) -> tuple[RouterResult, list[dict[str, Any]]]:
    request = GenerateRequest(
        system=load_prompt(DIRECTOR_ROLE, "approaches_system.md"),
        prompt=prompt,
        json_mode=True,
        response_schema=_Reply.model_json_schema(),
    )
    try:
        run = router.generate(DIRECTOR_ROLE, request, budget=budget, required_capability=Capability.JSON)
    except RouterError as error:
        raise ApproachProposalError(f"FR-INT-06: no approaches from the Director: {error}") from error
    if run.outcome != "ok" or run.response is None:
        raise ApproachProposalError(f"FR-INT-06: the Director's reply was {run.outcome}")
    try:
        reply = _Reply.model_validate_json(run.response.text or "")
    except pydantic.ValidationError as error:
        raise ApproachProposalError(f"FR-INT-06: the Director's reply is not a valid approach set: {error}") from error
    return run, [a.model_dump(mode="json") for a in reply.approaches]


def propose_approaches(
    brief: dict[str, Any], *, router: Router, base: dict[str, Any], seq: int, budget: float | None = None
) -> ApproachesResult:
    """`base` holds the event's v/ts/world_id/run_id/actor; the event gets `seq`. The brief goes in as data."""
    brief_text = _data(json.dumps(brief, ensure_ascii=False, indent=2), "BRIEF")
    run, approaches = _ask(router, load_prompt(DIRECTOR_ROLE, "approaches_task.md", {"brief": brief_text}), budget)
    runs = [run]
    if found := problems(approaches):  # one repair through the router, then reject
        previous = _data(json.dumps({"approaches": approaches}, ensure_ascii=False, indent=2), "PREVIOUS")
        listed = _data("\n".join(f"- {p}" for p in found), "PROBLEMS")
        variables = {"problems": listed, "brief": brief_text, "previous": previous}
        remaining = None if budget is None else run.budget
        run, approaches = _ask(router, load_prompt(DIRECTOR_ROLE, "approaches_repair.md", variables), remaining)
        runs.append(run)
        if found := problems(approaches):
            raise ApproachProposalError(f"FR-INT-06: approaches still break the rules after one repair: {found}")
    count = len(approaches)
    event = build_event(
        base, seq=seq, type="plan.approaches_proposed", target=base["world_id"], item=None, severity="needs_you",
        tool=None, cause=None, data={"approach_count": count},
        summary=f"The Director proposed {count} approaches to choose from.",
    )  # fmt: skip
    return ApproachesResult(approaches, event, runs)
