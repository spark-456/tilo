"""Clarifying questions (FR-INT-04, FR-INT-05; PRD 7.1). The Director only flags which brief fields are
ambiguous; this module decides what is asked, in deterministic code:

1. memory is looked up first, and a known preference or past answer is applied with its citation
   (one `memory.hit` each) instead of being asked again;
2. what is left is ranked by expected change to the plan and capped at MAX_QUESTIONS;
3. a candidate over the cap is not asked: the Director's guess is kept and recorded as an assumption
   with `question: null`, so nothing is assumed silently.

Events are built here and returned, never written (the harness is the single writer per world)."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tilo_planning.brief import CHIP_FIELDS, BriefValidationError, complete_brief, validate_brief
from tilo_planning.events import build_event, clip
from tilo_planning.memory import MemoryHit, MemoryLookup

MAX_QUESTIONS = 3

# Expected change to the plan when a field's answer differs from the Director's guess: the deliverable
# shapes every unit; goal and sources change the work itself; sensitivity changes tiers and gates; audience,
# deadline and constraints mostly change tone, schedule and checks. Ties keep CHIP_FIELDS order.
EXPECTED_CHANGE = {
    "deliverables": 1.0,
    "goal": 0.9,
    "sources": 0.7,
    "sensitivity": 0.6,
    "audience": 0.5,
    "deadline": 0.4,
    "constraints": 0.3,
}

_WORDING: dict[str, tuple[str, str, tuple[str, ...]]] = {  # field: (label, question, other suggested answers)
    "goal": ("Goal", "What should this work achieve?", ("Something else, which I will describe",)),
    "deliverables": (
        "Deliverables",
        "What should Tilo deliver, and in which format?",
        ("A PDF report", "A slide deck", "A document I can edit"),
    ),
    "audience": ("Audience", "Who is this for?", ("My own team", "An external client")),
    "deadline": ("Deadline", "When is this due?", ("No firm deadline", "By the end of this week")),
    "constraints": ("Constraints", "Are there rules the work must follow?", ("No extra rules",)),
    "sources": ("Sources", "Which material should Tilo work from?", ("Only what I attached", "The web as well")),
    "sensitivity": ("Sensitivity", "How sensitive is the data this task touches?", ("personal", "business", "public")),
}


@dataclass(frozen=True)
class Question:
    field: str
    text: str
    suggested_answers: tuple[str, ...]  # the first is the Director's guess, used if the question is skipped
    expected_change: float


@dataclass(frozen=True)
class QuestionsResult:
    brief: dict[str, Any]
    questions: list[Question]
    event: dict[str, Any] | None  # plan.questions_asked, or None when nothing is asked
    memory_hit_events: list[dict[str, Any]]


def generate_questions(
    brief: dict[str, Any],
    ambiguous_fields: Iterable[str],
    *,
    memory: MemoryLookup,
    base: dict[str, Any],
    seq: int,
) -> QuestionsResult:
    """`brief` is a brief or the Director's output. `base` is the event envelope (v, ts, world_id, run_id,
    actor); events take `seq`, `seq + 1`, ... (memory hits first, then plan.questions_asked)."""
    candidates = [f for f in dict.fromkeys(ambiguous_fields) if f in CHIP_FIELDS]
    brief = complete_brief(brief)
    hit_events: list[dict[str, Any]] = []
    for hit in memory.lookup(brief, candidates):  # FR-INT-05: before anything is ranked or asked
        applied = _apply(brief, hit) if hit.field in candidates else None
        if applied is None:
            continue
        brief = applied
        candidates.remove(hit.field)
        hit_events.append(_memory_hit_event(base, seq + len(hit_events), hit))

    ranked = sorted(candidates, key=lambda f: (-EXPECTED_CHANGE[f], CHIP_FIELDS.index(f)))
    questions = [_question(brief, f) for f in ranked[:MAX_QUESTIONS]]
    for field in ranked[MAX_QUESTIONS:]:
        brief["assumptions"].append({"question": None, "assumed": _assumed(brief, field)})
    brief = validate_brief(brief)

    event = None
    if questions:
        count = len(questions)
        event = build_event(
            base, seq=seq + len(hit_events), type="plan.questions_asked", target=base["world_id"], item=None,
            severity="needs_you", tool=None, cause=None, data={"question_count": count},
            summary=f"The Director has {count} question{'s' if count > 1 else ''} that change the plan.",
        )  # fmt: skip
    return QuestionsResult(brief, questions, event, hit_events)


def record_assumption(brief: dict[str, Any], question: Question, assumed: str | None = None) -> dict[str, Any]:
    """A skipped question keeps `assumed` (default: the Director's guess), shown as "Assumed: ..."."""
    updated = copy.deepcopy(brief)
    value = clip(assumed if assumed is not None else question.suggested_answers[0], 300)
    updated["assumptions"].append({"question": question.text, "assumed": value})
    return validate_brief(updated)


def _current(brief: dict[str, Any], field: str) -> str:
    value = brief[field]
    if field == "deliverables":
        return "; ".join(f"{d['title']} ({d['format']})" for d in value)
    if field == "sources":
        return "; ".join(s.get("label") or s["ref"] for s in value) or "Only what I attached"
    if field == "constraints":
        return "; ".join(value) or "No extra rules"
    if field == "deadline":
        return value or "No firm deadline"
    return str(value)


def _question(brief: dict[str, Any], field: str) -> Question:
    _label, text, others = _WORDING[field]
    answers = tuple(dict.fromkeys((clip(_current(brief, field), 300), *others)))[:3]
    return Question(field, text, answers, EXPECTED_CHANGE[field])


def _assumed(brief: dict[str, Any], field: str) -> str:
    return clip(f"{_WORDING[field][0]}: {_current(brief, field)}", 300)


def _apply(brief: dict[str, Any], hit: MemoryHit) -> dict[str, Any] | None:
    """The brief with `hit` applied and cited, or None if the stored value does not fit the field."""
    updated = copy.deepcopy(brief)
    if hit.field == "deliverables":
        updated["deliverables"] = [{**d, "format": hit.value} for d in updated["deliverables"]]
    elif hit.field == "constraints":
        updated["constraints"] = list(dict.fromkeys([*updated["constraints"], hit.value]))
    elif hit.field == "sources":
        updated["sources"].append({"kind": "memory", "ref": hit.ref, "label": clip(hit.value, 120)})
    else:
        updated[hit.field] = hit.value
    updated["applied_preferences"].append({"field": hit.field, "value": clip(hit.value, 300), "citation": hit.citation})
    try:
        return validate_brief(updated)
    except BriefValidationError:
        return None


def _memory_hit_event(base: dict[str, Any], seq: int, hit: MemoryHit) -> dict[str, Any]:
    return build_event(
        base, seq=seq, type="memory.hit", target=base["world_id"], item=None, severity="info", tool=None,
        cause=None, summary=f"Applied a saved {hit.kind} for {hit.field} instead of asking again.",
        data={"origin_cost": hit.origin_cost, "lookup_cost": hit.lookup_cost, "saved": hit.saved},
    )  # fmt: skip
