"""Brief extraction (FR-INT-03, PRD 7.1). The Director role turns the task text into a brief through the
provider layer's router (PL-01): the router validates the reply against the output schema, makes one repair
on the same profile and escalates on a second schema failure, recording every attempt for the Trace. A
brief that still fails `brief.schema.json` is never returned. Deciding which fields are ambiguous is the
model's judgement; everything after that (questions, memory, assumptions) is deterministic code."""

from __future__ import annotations

import copy
import functools
from dataclasses import dataclass
from typing import Any

import pydantic
from tilo_contracts import Brief
from tilo_providers.interfaces import Capability, GenerateRequest
from tilo_providers.prompts import load_prompt
from tilo_providers.router import Router, RouterError, RouterResult

DIRECTOR_ROLE = "director"
CHIP_FIELDS = ("goal", "deliverables", "audience", "deadline", "constraints", "sources", "sensitivity")
_END_MARKER = "TASK>>>"


class BriefExtractionError(Exception):
    """No schema-valid brief could be extracted; nothing is returned."""


class BriefValidationError(ValueError):
    """A brief (or an edit to one) does not satisfy brief.schema.json."""


@dataclass(frozen=True)
class ExtractionResult:
    brief: dict[str, Any]
    ambiguous_fields: list[str]
    run: RouterResult  # router attempts, profile and usage for the Trace (PRD 9.3)


def validate_brief(data: Any) -> dict[str, Any]:
    """The brief as contract-shaped JSON, or BriefValidationError. Validated with the generated `Brief`."""
    try:
        brief = Brief.model_validate(data).model_dump(mode="json")
    except pydantic.ValidationError as error:
        raise BriefValidationError(str(error)) from error
    for source in brief["sources"]:
        if source.get("label") is None:  # optional in the contract, never null
            source.pop("label", None)
    return brief


def complete_brief(data: dict[str, Any]) -> dict[str, Any]:
    """A brief from a brief or from the Director's output: `ambiguous_fields` is dropped, and assumptions
    and applied preferences start empty when absent (only code fills them)."""
    fields = {k: v for k, v in data.items() if k != "ambiguous_fields"}
    return validate_brief({"assumptions": [], "applied_preferences": [], **fields})


@functools.cache
def output_schema() -> dict[str, Any]:
    """What the Director returns: the brief's chip fields plus `ambiguous_fields`. Assumptions and applied
    preferences are filled in by code, never by the model."""
    schema = Brief.model_json_schema()
    for key in ("assumptions", "applied_preferences"):
        del schema["properties"][key]
        schema["required"].remove(key)
    schema["properties"]["ambiguous_fields"] = {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "enum": list(CHIP_FIELDS)},
    }
    schema["required"].append("ambiguous_fields")
    return schema


def extract_brief(task_text: str, *, router: Router, budget: float | None = None) -> ExtractionResult:
    """PRD 16.3 item 1: the task text is passed only as delimited data, after the instructions."""
    request = GenerateRequest(
        system=load_prompt(DIRECTOR_ROLE, "brief_system.md"),
        prompt=load_prompt(DIRECTOR_ROLE, "brief_task.md", {"task": task_text.replace(_END_MARKER, "TASK> > >")}),
        json_mode=True,
        response_schema=output_schema(),
    )
    try:
        run = router.generate(DIRECTOR_ROLE, request, budget=budget, required_capability=Capability.JSON)
    except RouterError as error:
        raise BriefExtractionError(f"FR-INT-03: no schema-valid brief from the Director: {error}") from error
    if run.outcome != "ok" or run.response is None:
        raise BriefExtractionError(f"FR-INT-03: the Director's reply was {run.outcome}")
    try:
        output = pydantic.TypeAdapter(dict[str, Any]).validate_json(run.response.text or "")
        ambiguous = list(output["ambiguous_fields"])
        brief = complete_brief(output)
    except (pydantic.ValidationError, KeyError, TypeError, BriefValidationError) as error:
        raise BriefExtractionError(f"FR-INT-03: the Director's reply is not a valid brief: {error}") from error
    return ExtractionResult(brief, ambiguous, run)


def edit_brief_field(brief: dict[str, Any], field: str, value: Any) -> dict[str, Any]:
    """A person edits one chip. Returns a new, validated brief; the original is left unchanged."""
    if field not in CHIP_FIELDS:
        raise BriefValidationError(f"{field!r} is not an editable brief field")
    return validate_brief({**copy.deepcopy(brief), field: value})
