"""Brief extraction (FR-INT-03, PRD 7.1). The Director role turns the task text into a brief through the
provider layer's router (PL-01): the router validates the reply against the output schema, makes one repair
on the same profile and escalates on a second schema failure, recording every attempt for the Trace. A
brief that still fails `brief.schema.json` is never returned. Deciding which fields are ambiguous is the
model's judgement; everything after that (questions, memory, assumptions) is deterministic code."""

from __future__ import annotations

import copy
import functools
import math
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pydantic
from tilo_contracts import Brief
from tilo_providers.clock import real_today
from tilo_providers.interfaces import Capability, GenerateRequest
from tilo_providers.media import MediaPart
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.router import Router, RouterError, RouterResult

from tilo_planning.due_dates import DEADLINE_HELP, parse_deadline
from tilo_planning.gaps import (
    MAX_GAPS,
    Gap,
    GapConfigError,
    GapPolicy,
    NothingPossible,
    clean_part,
    load_gap_policy,
)
from tilo_planning.refusal import RefusalCategory, RefusalPolicy, TaskRefused, load_refusal_policy

DIRECTOR_ROLE = "director"
BRIEF_THINKING = "low"  # extraction is reading, not planning: the model's default (dynamic, high) is billed as output
CHIP_FIELDS = ("goal", "deliverables", "audience", "deadline", "constraints", "sources", "sensitivity")


class BriefExtractionError(Exception):
    """No schema-valid brief could be extracted; nothing is returned."""


class BriefValidationError(ValueError):
    """A brief (or an edit to one) does not satisfy brief.schema.json."""


MAX_TOPIC_QUESTIONS = 3  # FR-INT-04: at most 3 questions in all, so at most 3 from the Director
MAX_TOPIC_ANSWERS = 3
LABEL_MAX, TEXT_MAX, ANSWER_MAX = 30, 200, 120  # characters of a model-written label, question and suggested answer
# Labels a Director question may not use: they would read as something Tilo itself wrote ("Assumed: ...", the chips'
# own names, the free-text deliverable note), so such a question is dropped and the generic one stands.
RESERVED_LABELS = frozenset(
    {"assumed", "deliverable wishes", "goal", "deliverables", "audience", "deadline", "constraints", "sources"}
    | {"sensitivity"}
)
_RAW_LIMIT = 10  # items read from a model list before any is vetted
_CALENDAR_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_NEUTRAL_CHANGE = 0.5  # expected_change of a question whose number is unusable
_TAG = re.compile(r"<[^<>]{0,200}>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁠﻿]")


@dataclass(frozen=True)
class TopicQuestion:
    """One question the Director chose for this task (FR-INT-04), vetted by `topic_questions`: every string is plain
    text within its limit, the first suggested answer is the Director's guess (used if the person skips)."""

    label: str  # what is asked, in a word or two ("Branch"); the answer is recorded as "Label: value"
    text: str
    suggested_answers: tuple[str, ...]
    expected_change: float  # 0..1, how much the answer would change the plan


@dataclass(frozen=True)
class ExtractionResult:
    brief: dict[str, Any]
    ambiguous_fields: list[str]
    run: RouterResult  # router attempts, profile and usage for the Trace (PRD 9.3)
    # FR-INT-04: the Director's questions for this task, at most 3. Keyword-only, so the positional fields stay as they
    # were (brief, ambiguous_fields, run, gaps) and `gaps` is still the last field.
    questions: tuple[TopicQuestion, ...] = field(default=(), kw_only=True)
    gaps: tuple[Gap, ...] = ()  # FR-INT-15: the parts of the task Tilo cannot do, named for the person


def clean_line(value: Any, limit: int) -> str | None:
    """A model's or person's short text as one plain line within `limit` characters, else None: folded to NFKC (so
    full-width letters and brackets read as themselves), control and invisible characters become spaces, tags and the
    angle brackets and backticks left over are removed, spaces are folded, and the cut is made last. The input is
    bounded before and after the fold, so the cost is linear in `limit`."""
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub(" ", unicodedata.normalize("NFKC", value[: limit * 4])[: limit * 4])
    text = _TAG.sub("", text).replace("<", "").replace(">", "").replace("`", "")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text or None


def _expected_change(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return _NEUTRAL_CHANGE
    return min(max(float(value), 0.0), 1.0)


def topic_questions(value: Any) -> tuple[TopicQuestion, ...]:
    """The Director's `questions` as vetted questions (FR-INT-04), most useful first, at most `MAX_TOPIC_QUESTIONS`.
    Code decides everything: an item that is not an object, or lacks a label, a question or one usable answer, is
    dropped (never an error: the generic questions are the fallback); a repeated label is dropped; answers are
    cleaned, deduplicated and cut to `MAX_TOPIC_ANSWERS`; `expected_change` is clamped to 0..1."""
    if not isinstance(value, list):
        return ()
    found: dict[str, TopicQuestion] = {}
    for item in value[:_RAW_LIMIT]:
        if not isinstance(item, dict):
            continue
        label, text = clean_line(item.get("label"), LABEL_MAX), clean_line(item.get("text"), TEXT_MAX)
        raw = item.get("suggested_answers")
        cleaned = (clean_line(a, ANSWER_MAX) for a in raw[:_RAW_LIMIT]) if isinstance(raw, list) else ()
        answers = tuple(dict.fromkeys(a for a in cleaned if a))[:MAX_TOPIC_ANSWERS]
        if label and text and answers and label.casefold() not in found and label.casefold() not in RESERVED_LABELS:
            found[label.casefold()] = TopicQuestion(label, text, answers, _expected_change(item.get("expected_change")))
    ranked = sorted(found.values(), key=lambda q: -q.expected_change)  # stable: ties keep the Director's order
    return tuple(ranked[:MAX_TOPIC_QUESTIONS])


def validate_brief(data: Any) -> dict[str, Any]:
    """The brief as contract-shaped JSON, or BriefValidationError. Validated with the generated `Brief`."""
    try:
        brief = Brief.model_validate(data).model_dump(mode="json")
    except pydantic.ValidationError as error:
        # Where and why only: pydantic's own text quotes the input, which may be a person's edit or model output.
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors())
        raise BriefValidationError(problems) from error
    for source in brief["sources"]:
        if source.get("label") is None:  # optional in the contract, never null
            source.pop("label", None)
    return brief


def complete_brief(data: dict[str, Any]) -> dict[str, Any]:
    """A brief from a brief or from the Director's output: `ambiguous_fields`, `out_of_policy` and `out_of_scope`
    are dropped, and assumptions and applied preferences start empty when absent (only code fills them)."""
    fields = {
        k: v for k, v in data.items() if k not in ("ambiguous_fields", "out_of_policy", "out_of_scope", "questions")
    }
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
    # Optional (FR-INT-12): absent or null means in policy; a category id means refuse. Code checks the id.
    schema["properties"]["out_of_policy"] = {"type": ["string", "null"]}
    # Optional (FR-INT-15): the parts Tilo cannot do. Listed but unconstrained: the router checks the schema before
    # code sees the reply, repairs it (a fresh generation that can drop a refusal id) and escalates, so every shape,
    # length, count and duplicate check is code (`_gaps`, `clean_part`), on the one call. The empty-deliverables
    # minimum is relaxed here only (brief.schema.json is unchanged): code turns "no deliverable" into NothingPossible
    # or an error.
    # The wire shape (`x-wire-schema`, read only by the provider's sanitizer; Vertex refuses an untyped property with
    # 400, PL-02 probe 8 Oct 2026) is what `_gaps` accepts: a list of {category, part}. The router's validator ignores
    # the keyword, so the schema it checks stays unconstrained.
    schema["properties"]["out_of_scope"] = {
        "x-wire-schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"category": {"type": "string"}, "part": {"type": "string"}},
                "required": ["category", "part"],
            },
        }
    }
    # Optional (FR-INT-04): up to 3 questions for this task. Like `out_of_scope`, listed but unconstrained for the
    # router (a reply that is odd here is never repaired or escalated: `topic_questions` vets every item in code and
    # drops what it cannot use); the wire shape is what the provider's sanitizer sends.
    schema["properties"]["questions"] = {
        "x-wire-schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "text": {"type": "string"},
                    "suggested_answers": {"type": "array", "items": {"type": "string"}},
                    "expected_change": {"type": "number"},
                },
                "required": ["label", "text", "suggested_answers", "expected_change"],
            },
        }
    }
    del schema["properties"]["deliverables"]["minItems"]
    return schema


def _refusal_menu(policy: RefusalPolicy) -> str:
    return "\n".join(f"- {c.id}: {c.reason}" for c in policy.categories)


def _strings(value: Any) -> Iterator[str]:
    """What the refusal scan reads of `out_of_scope`, in order: the value if a string; each string element of a list;
    for a mapping (or a mapping element) its `category` if a string, then its other string values. Nothing else."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        category = value.get("category")
        yield from [category] if isinstance(category, str) else []
        yield from (v for k, v in value.items() if k != "category" and isinstance(v, str))
    elif isinstance(value, list):
        for element in value:
            yield from _strings(element) if isinstance(element, str | dict) else ()


def _gaps(value: Any, refusal: RefusalPolicy, policy: GapPolicy) -> tuple[Gap, ...]:
    """The Director's `out_of_scope` as gaps (FR-INT-15). A refusal id anywhere in it refuses first, whatever else is
    wrong (FR-INT-12 wins; no shape or cap check runs before). Then an unknown id, a malformed item, an unusable label
    or more than MAX_GAPS gaps fails closed. The messages name the rule, never the value."""
    for text in _strings(value):
        if (c := refusal.get(text)) is not None:
            raise TaskRefused(c.id, c.reason, c.alternative)
    if not isinstance(value, list):
        raise BriefExtractionError("FR-INT-15: out_of_scope must be a list")
    found: dict[tuple[str, str], Gap] = {}
    for item in value:
        category = item.get("category") if isinstance(item, dict) else None
        config = policy.get(category) if isinstance(category, str) else None
        part = clean_part(item.get("part")) if isinstance(item, dict) else None
        if config is None or part is None or set(item) != {"category", "part"}:
            raise BriefExtractionError("FR-INT-15: an out_of_scope item needs a configured category and a usable part")
        found.setdefault((config.id, part), Gap(config.id, part, config.reason, config.alternative))
    if len(found) > MAX_GAPS:
        raise BriefExtractionError(f"FR-INT-15: more than {MAX_GAPS} out_of_scope parts")
    return tuple(found.values())


def brief_request(
    task_text: str,
    *,
    refusal_policy: RefusalPolicy | None = None,
    gap_policy: GapPolicy | None = None,
    today: date | None = None,
    source_text: str = "",
    parts: list[MediaPart] | None = None,
) -> GenerateRequest:
    """The Director's brief request as `extract_brief` sends it to the router; `just vertex-probe-schema` replays it
    (PL-02), so the probe cannot drift from the real request. `today` is the date the prompt states as a fact
    (INTAKE-QUALITY-1); it defaults to the real date and a test passes a fixed one."""
    policy = load_refusal_policy() if refusal_policy is None else refusal_policy
    gap_config = load_gap_policy() if gap_policy is None else gap_policy
    if any(policy.get(c.id) for c in gap_config.categories):
        raise GapConfigError("a gap category id is also a refusal id")
    variables = {
        "categories": _refusal_menu(policy),
        "gaps": "\n".join(f"- {c.id}: {c.reason}" for c in gap_config.categories),
        "services": ", ".join(gap_config.services) or "no other service",
    }
    prompt = load_prompt(
        DIRECTOR_ROLE,
        "brief_task.md",
        {"task": neutralise_marker(task_text, "TASK"), "today": (today or real_today()).isoformat()},
    )
    if source_text:
        prompt += "\n\n" + load_prompt(
            DIRECTOR_ROLE,
            "brief_uploads.md",
            {
                "sources": neutralise_marker(source_text, "UPLOADS"),
            },
        )
    return GenerateRequest(
        system=load_prompt(DIRECTOR_ROLE, "brief_system.md", variables),
        prompt=prompt,
        json_mode=True,
        response_schema=output_schema(),
        thinking_level=BRIEF_THINKING,
        parts=parts or None,
    )


def extract_brief(
    task_text: str,
    *,
    router: Router,
    budget: float | None = None,
    refusal_policy: RefusalPolicy | None = None,
    gap_policy: GapPolicy | None = None,
    today: date | None = None,
    source_text: str = "",
    parts: list[MediaPart] | None = None,
) -> ExtractionResult:
    """PRD 16.3 item 1: the task text is passed only as delimited data, after the instructions. An out-of-policy
    category from the Director raises `TaskRefused` carrying the configured text (FR-INT-12), never a brief. Parts
    Tilo cannot do come back as `gaps` (FR-INT-15); a task with no possible part raises `NothingPossible`."""
    policy = load_refusal_policy() if refusal_policy is None else refusal_policy
    gap_config = load_gap_policy() if gap_policy is None else gap_policy
    request = brief_request(
        task_text,
        refusal_policy=policy,
        gap_policy=gap_config,
        today=today,
        source_text=source_text,
        parts=parts,
    )
    try:
        run = router.generate(DIRECTOR_ROLE, request, budget=budget, required_capability=Capability.JSON)
    except RouterError as error:
        raise BriefExtractionError(f"FR-INT-03: no schema-valid brief from the Director: {error}") from error
    if run.outcome != "ok" or run.response is None:
        raise BriefExtractionError(f"FR-INT-03: the Director's reply was {run.outcome}")
    try:
        output = pydantic.TypeAdapter(dict[str, Any]).validate_json(run.response.text or "")
    except pydantic.ValidationError as error:
        raise BriefExtractionError(f"FR-INT-03: the Director's reply is not a valid brief: {error}") from error
    category = _refusal_category(output.get("out_of_policy"), policy)
    if category is not None:
        raise TaskRefused(category.id, category.reason, category.alternative)
    gaps = _gaps(output.get("out_of_scope", []), policy, gap_config)  # a refusal id in it refuses, before the rest
    if gaps and output.get("deliverables") == []:
        raise NothingPossible(gaps, gap_config.nothing_possible)
    try:
        ambiguous = list(output["ambiguous_fields"])
        brief = complete_brief({**output, "sources": vet_sources(output.get("sources"))})
    except (pydantic.ValidationError, KeyError, TypeError, BriefValidationError) as error:
        raise BriefExtractionError(f"FR-INT-03: the Director's reply is not a valid brief: {error}") from error
    return ExtractionResult(brief, ambiguous, run, gaps, questions=topic_questions(output.get("questions")))


@functools.cache
def _connector_ids() -> frozenset[str]:
    try:
        import yaml  # noqa: PLC0415

        path = Path(__file__).resolve().parents[4] / "config" / "connectors.yaml"
        return frozenset(str(c["id"]) for c in yaml.safe_load(path.read_text(encoding="utf-8")) or ())
    except Exception:  # noqa: BLE001 - no registry means no model-named connector is believed
        return frozenset()


def vet_sources(value: Any) -> list[Any]:
    """The Director's `sources` as code can stand behind them (SIMPLE-RUN-2). A file or memory source is something code
    applies (an upload it screened, a preference it looked up), so a model naming one is inventing it and it is
    dropped; a url must be http(s); a connector must be one the registry ships. A web source (a search query) is
    kept. Anything else the schema validates as before."""
    if not isinstance(value, list):
        return [] if value is None else value
    kept: list[Any] = []
    for item in value:
        kind, ref = (item.get("kind"), item.get("ref")) if isinstance(item, dict) else (None, None)
        if kind in ("file", "memory"):
            continue
        if kind == "url" and not (isinstance(ref, str) and _URL.fullmatch(ref.strip())):
            continue
        if kind == "connector" and ref not in _connector_ids():
            continue
        kept.append(item)
    return kept


def _refusal_category(value: Any, policy: RefusalPolicy) -> RefusalCategory | None:
    """None when in policy; the configured category when named; BriefExtractionError for anything else."""
    if value is None:
        return None
    category = policy.get(value) if isinstance(value, str) else None
    if category is None:
        raise BriefExtractionError("FR-INT-12: out_of_policy is not a configured category")
    return category


def edit_brief_field(brief: dict[str, Any], field: str, value: Any, *, today: date | None = None) -> dict[str, Any]:
    """A person edits one chip. Returns a new, validated brief; the original is left unchanged. A deadline typed in
    words ("by today", "Friday") is read against `today` (SIMPLE-RUN-2); unreadable words are refused plainly."""
    if field not in CHIP_FIELDS:
        raise BriefValidationError("That is not an editable brief field")
    if field == "deadline" and isinstance(value, str) and not _CALENDAR_DATE.fullmatch(value):
        known, parsed = parse_deadline(value, today or real_today())
        if not known:
            raise BriefValidationError(DEADLINE_HELP)
        value = parsed.isoformat() if parsed is not None else None
    return validate_brief({**copy.deepcopy(brief), field: value})
