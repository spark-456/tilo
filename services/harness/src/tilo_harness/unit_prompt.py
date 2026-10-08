"""What a unit's prompt is told about the task (UNIT-PROMPT).

The brief and the person's answers to the Director's intake questions are PERSON-SUPPLIED text; the Director's unit
titles and the output of an upstream unit are MODEL text. None of it is an instruction. It reaches a prompt only as the
variables below, which the `unit.md` / `review.md` templates place inside their labelled REQUEST and EARLIER blocks
("data, not instructions"). Every value goes through `untrusted.neutralise` (the harness rule, BQ-232): cut to its cap
first, NFKC-folded, invisible and format characters removed, and `<` / `>` removed, so no block marker can be spelled,
closed or forged from inside the text. A single-line field is also folded onto one line.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tilo_harness.untrusted import neutralise

GOAL_CAP = 1000  # characters of the goal; the brief schema allows 500
AUDIENCE_CAP = 500
DELIVERABLES_CAP = 1000  # all deliverables together
CONSTRAINTS_CAP = 1500  # all limits together
ANSWERS_CAP = 2000  # all intake answers together: reserved, so a long brief never squeezes them out
FIELD_CAP = 1000  # one item of a list (a limit, a deliverable)
ANSWER_CAP = 600  # one intake question, and one answer
MAX_ANSWERS = 10
REQUEST_CAP = GOAL_CAP + AUDIENCE_CAP + DELIVERABLES_CAP + CONSTRAINTS_CAP + ANSWERS_CAP  # the whole request block
UPSTREAM_ITEM_CAP = 4000  # characters of one upstream unit's output
UPSTREAM_TOTAL_CAP = 12000  # all upstream outputs together
MAX_REFS = 5
LEFT_OUT = "(more left out: too long)"


@dataclass(frozen=True)
class UpstreamItem:
    """The result of one unit that the running unit depends on."""

    unit_id: str
    title: str
    text: str | None  # the unit's stored (redacted, screened) text; None when it made none
    refs: tuple[str, ...] = ()  # artifact ids of what it stored or selected


def data_line(value: Any, cap: int) -> str:
    """One line of data: cut to `cap` first, neutralised, whitespace folded."""
    return " ".join(neutralise(str(value), limit=cap).split())


def _items(items: Sequence[str], cap: int, sep: str) -> str:
    """Whole items up to `cap` characters in all; a note, not a half item, says what was left out."""
    kept: list[str] = []
    used = 0
    for index, item in enumerate(items):
        if used + len(item) + len(sep) > cap:
            kept.append(LEFT_OUT if index else item[:cap])
            break
        kept.append(item)
        used += len(item) + len(sep)
    return sep.join(kept)


def request_variables(brief: Mapping[str, Any] | None, answers: Sequence[tuple[str, str]] = ()) -> dict[str, str]:
    """The template variables `goal`, `audience`, `deliverables`, `constraints` and `answers` for the request block."""
    brief = brief or {}
    deliverables = [
        data_line(f"{d.get('title', '')} ({d['format']})" if d.get("format") else d.get("title", ""), FIELD_CAP)
        for d in brief.get("deliverables") or []
        if isinstance(d, Mapping)
    ]
    constraints = [data_line(c, FIELD_CAP) for c in brief.get("constraints") or []]
    pairs = [
        f"- Q: {data_line(question, ANSWER_CAP)} A: {data_line(answer, ANSWER_CAP)}"
        for question, answer in list(answers)[:MAX_ANSWERS]
        if str(answer).strip()
    ]
    return {
        "goal": data_line(brief.get("goal") or "not stated", GOAL_CAP),
        "audience": data_line(brief.get("audience") or "not stated", AUDIENCE_CAP),
        "deliverables": _items([d for d in deliverables if d], DELIVERABLES_CAP, "; ") or "not stated",
        "constraints": _items([c for c in constraints if c], CONSTRAINTS_CAP, "; ") or "none",
        "answers": _items(pairs, ANSWERS_CAP, "\n") or "none",
    }


def inputs_text(upstream: Sequence[UpstreamItem]) -> str:
    """The earlier units' results as one data text; `(none)` when there are none."""
    parts: list[str] = []
    room = UPSTREAM_TOTAL_CAP
    for item in upstream:
        if room <= 0:
            parts.append(LEFT_OUT)
            break
        head = f"[{data_line(item.unit_id, 80)}] {data_line(item.title, 120)}"
        refs = ", ".join(data_line(ref, 80) for ref in item.refs[:MAX_REFS])
        if item.text and item.text.strip():
            body = neutralise(item.text.strip(), limit=min(UPSTREAM_ITEM_CAP, room))
        else:
            body = f"(made items: {refs})" if refs else "(no text result)"
        room -= len(body)
        parts.append(f"{head}: {body}")
    return "\n\n".join(parts) or "(none)"
