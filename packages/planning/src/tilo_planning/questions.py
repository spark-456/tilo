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
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from tilo_planning.brief import CHIP_FIELDS, BriefValidationError, complete_brief, validate_brief
from tilo_planning.events import build_event, clip
from tilo_planning.memory import MemoryHit, MemoryLookup

MAX_QUESTIONS = 3
DESCRIBE_GOAL = "Something else, which I will describe"  # a goal prompt, never a goal (BQ-99)
WEB_SOURCE = {"kind": "web", "ref": "web", "label": "The web"}  # no query yet: the goal is never one (BQ-99)

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
    "goal": ("Goal", "What should this work achieve?", (DESCRIBE_GOAL,)),
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


def record_assumption(
    brief: dict[str, Any], question: Question, assumed: str | None = None, *, today: date | None = None
) -> dict[str, Any]:
    """A skipped question keeps `assumed` (default: the Director's guess), recorded as "Label: value" like
    an assumption over the cap, and shown as "Assumed: ...". The assumption is the value the plan uses
    (BQ-97), so the field takes it too: the guess leaves the chip as it is, another value is applied as
    an answer would be."""
    value = assumed if assumed is not None else question.suggested_answers[0]
    updated = apply_answer(brief, question, value, today=today or date.today())
    updated["assumptions"].append(
        {"question": question.text, "assumed": clip(f"{_WORDING[question.field][0]}: {value}", 300)}
    )
    return validate_brief(updated)


def apply_answer(brief: dict[str, Any], question: Question, answer: str, *, today: date) -> dict[str, Any]:
    """The person's answer to `question` (FR-INT-04). The Director's guess (the first suggested answer) keeps
    the chip; another suggested answer sets the chip value it stands for; anything else is set as typed. An
    answer the chip cannot hold raises BriefValidationError, and the person edits the chip instead.
    The goal prompt is not a goal, so it is refused the same way (BQ-99)."""
    if answer == question.suggested_answers[0]:
        return validate_brief(copy.deepcopy(brief))
    field = question.field
    if field == "goal" and answer == DESCRIBE_GOAL:
        raise BriefValidationError("Describe the goal in the goal chip; that answer is not a goal.")
    value: Any = _ANSWER_VALUES.get(field, {}).get(answer, answer)
    if field == "deliverables":
        formats = _answer_formats(answer, question.suggested_answers[0], brief)
        if not formats:  # free text with no format: it stays as the content, in the default format (BQ-FREETEXT-1)
            wish = clip(" ".join(_C0.sub(" ", answer[:ANSWER_MAX_CHARS]).split()), 300)  # no control chars or breaks
            first = {**brief["deliverables"][0], "title": clip(wish, 120), "format": DEFAULT_FORMAT}
            brief = {
                **copy.deepcopy(brief),
                "constraints": list(dict.fromkeys([*brief["constraints"], f"Deliverable wishes: {wish}"])),
            }
            value = [first]
        elif len(formats) == 1:
            value = [{**d, "format": formats[0]} for d in brief["deliverables"]]
        else:  # "A PDF report and a slide deck": the deliverables already in a named format stay, the rest are added
            kept = [d for d in brief["deliverables"] if d["format"] in formats]
            title = brief["deliverables"][0]["title"]
            value = kept + [
                {"title": clip(f"{title} ({f})", 120), "format": f}
                for f in formats
                if f not in {d["format"] for d in kept}
            ]
    elif field == "constraints":
        value = [] if value is None else list(dict.fromkeys([*brief["constraints"], value]))
    elif field == "sources" and value in (None, "web"):
        kept = [s for s in brief["sources"] if s["kind"] != "web"]
        value = kept if value is None else [*kept, dict(WEB_SOURCE)]
    elif field == "deadline" and value == "end_of_week":
        value = (today + timedelta(days=(4 - today.weekday()) % 7)).isoformat()  # the coming Friday
    return validate_brief({**copy.deepcopy(brief), field: value})


ANSWER_MAX_CHARS = 300  # the answers route's own limit: a longer answer is cut, never scanned
_FORMATS = (
    "pdf",
    "pptx",
    "docx",
    "xlsx",
    "csv",
    "markdown",
    "google_slides",
    "google_docs",
    "google_sheets",
    "email",
    "in_app",
)
_FORMAT_WORDS = {  # what a person types for a format
    "powerpoint": "pptx", "ppt": "pptx", "slides": "pptx", "slide deck": "pptx", "deck": "pptx", "word": "docx",
    "doc": "docx", "document": "docx", "excel": "xlsx", "spreadsheet": "xlsx", "md": "markdown", "report": "pdf",
}  # fmt: skip
DEFAULT_FORMAT = "markdown"  # PRD default for a deliverable whose format the person did not name
MIN_FREE_TEXT_WORDS = 3  # a deliverables answer of this many words and no format is content, not a typo
_C0 = re.compile(r"[\x00-\x1f\x7f]")
_WORD = re.compile(r"[A-Za-z]{2,}")
_ANSWER_SPLIT = re.compile(r"[;,+&/]|\band\b", re.IGNORECASE)
_CHIP_FORMAT = re.compile(r".*\((" + "|".join(_FORMATS) + r")\)")


def _part_format(part: str) -> str | None:
    key = part.strip().rstrip(".").lower()
    labels = {label.lower(): fmt for label, fmt in _ANSWER_VALUES["deliverables"].items()}
    if key in labels:
        return labels[key]
    if (chip := _CHIP_FORMAT.fullmatch(key)) is not None:  # the current chip: "Price report (pdf)"
        return chip.group(1)
    return key if key in _FORMATS else _FORMAT_WORDS.get(key)


def _names_a_format(answer: str) -> bool:
    """Any format, format word or suggested label anywhere in `answer`: such an answer is a format answer."""
    text = " " + " ".join(_WORD.findall(answer.lower())) + " "
    names = {*_FORMATS, *_FORMAT_WORDS, *(label.lower() for label in _ANSWER_VALUES["deliverables"])}
    return any(f" {name} " in text for name in names) or any(_part_format(p) for p in _ANSWER_SPLIT.split(answer))


def _answer_formats(answer: str, current: str, brief: dict[str, Any]) -> list[str]:
    """The formats a deliverables answer names, in order, once each: one answer or several joined by "and", a
    comma, a semicolon, "+" or "&". The chip's own text (`current`, whose titles may hold any of those) stands for the
    formats the brief has now. A part that names no format refuses the answer, the person says it again."""
    answer = answer[:ANSWER_MAX_CHARS]
    if len(_WORD.findall(answer)) >= MIN_FREE_TEXT_WORDS and not _names_a_format(answer):
        return []  # what the person wants in it, in their words: not a format, not refused
    have = [d["format"] for d in brief["deliverables"]] if current in answer else []
    parts = [p for p in _ANSWER_SPLIT.split(answer.replace(current, ";")) if p.strip()]
    formats = [*have, *(_part_format(p) for p in parts)]
    if not formats or None in formats:
        raise BriefValidationError(
            "Name the format as pdf, pptx, docx, xlsx, csv, markdown, email and so on, or pick a number from the list."
        )
    return list(dict.fromkeys(f for f in formats if f is not None))


# Suggested answers (from _WORDING) that stand for a chip value; any other answer is set as typed.
_ANSWER_VALUES: dict[str, dict[str, Any]] = {
    "deliverables": {"A PDF report": "pdf", "A slide deck": "pptx", "A document I can edit": "docx"},
    "deadline": {"No firm deadline": None, "By the end of this week": "end_of_week"},
    "constraints": {"No extra rules": None},
    "sources": {"Only what I attached": None, "The web as well": "web"},
}


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
