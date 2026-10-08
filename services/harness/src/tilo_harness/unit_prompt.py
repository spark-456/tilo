"""What a unit's prompt is told about the task (UNIT-PROMPT).

The brief and the person's answers to the Director's intake questions are PERSON-SUPPLIED text; the output of an
upstream unit is MODEL text. Neither is an instruction. They reach a prompt only as the variables below, which the
`unit.md` / `review.md` templates place inside their labelled REQUEST and EARLIER blocks ("data, not instructions").
Every value is cut to a cap here, a single-line field is folded onto one line (so it cannot forge another label)
and no block marker can be closed from inside the text (`neutralise_marker`, PRD 16.3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tilo_providers.prompts import neutralise_marker

FIELD_CAP = 1000  # characters of any one brief field (goal, audience, one limit, one deliverable)
ANSWER_CAP = 600  # characters of one intake question, and of one answer
MAX_ANSWERS = 10
REQUEST_CAP = 6000  # all of the request block's variables together; later fields are cut first
UPSTREAM_ITEM_CAP = 4000  # characters of one upstream unit's output
UPSTREAM_TOTAL_CAP = 12000  # all upstream outputs together
MAX_REFS = 5

_MARKERS = ("REQUEST", "EARLIER", "WORK", "BEATS")
_ELLIPSIS = "..."


@dataclass(frozen=True)
class UpstreamItem:
    """The result of one unit that the running unit depends on."""

    unit_id: str
    title: str
    text: str | None  # the unit's text outputs; None when it made none
    refs: tuple[str, ...] = ()  # artifact ids of what it stored or selected


def neutralise(text: str) -> str:
    for marker in _MARKERS:
        text = neutralise_marker(text, marker)
    return text


def _cut(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[: max(cap - len(_ELLIPSIS), 0)] + _ELLIPSIS


def _line(value: Any, cap: int) -> str:
    """One line of data: whitespace folded, cut, and unable to close a block."""
    return neutralise(_cut(" ".join(str(value).split()), cap))


def request_variables(brief: Mapping[str, Any] | None, answers: Sequence[tuple[str, str]] = ()) -> dict[str, str]:
    """The template variables `goal`, `audience`, `deliverables`, `constraints` and `answers` for the request block."""
    brief = brief or {}
    deliverables = [
        d.get("title", "") + (f" ({d['format']})" if d.get("format") else "")
        for d in brief.get("deliverables") or []
        if isinstance(d, Mapping)
    ]
    constraints = brief.get("constraints") or []
    pairs = [
        f"- Q: {_line(question, ANSWER_CAP)} A: {_line(answer, ANSWER_CAP)}"
        for question, answer in list(answers)[:MAX_ANSWERS]
        if str(answer).strip()
    ]
    values = {
        "goal": _line(brief.get("goal") or "not stated", FIELD_CAP),
        "audience": _line(brief.get("audience") or "not stated", FIELD_CAP),
        "deliverables": "; ".join(_line(d, FIELD_CAP) for d in deliverables) or "not stated",
        "constraints": "; ".join(_line(c, FIELD_CAP) for c in constraints) or "none",
        "answers": "\n".join(pairs) or "none",
    }
    room = REQUEST_CAP  # one budget for the whole block, spent in this order
    for name, value in values.items():
        values[name] = value = value[: max(room, 0)]
        room -= len(value)
    return values


def inputs_text(upstream: Sequence[UpstreamItem]) -> str:
    """The earlier units' results as one data text; `(none)` when there are none."""
    parts: list[str] = []
    room = UPSTREAM_TOTAL_CAP
    for item in upstream:
        head = f"[{_line(item.unit_id, 80)}] {_line(item.title, 120)}"
        refs = ", ".join(_line(ref, 80) for ref in item.refs[:MAX_REFS])
        if item.text:
            body = neutralise(_cut(item.text.strip(), min(UPSTREAM_ITEM_CAP, max(room, 0))))
        else:
            body = f"(made items: {refs})" if refs else "(no text result)"
        if room <= 0:
            parts.append("(further results left out: the earlier work is long)")
            break
        room -= len(body)
        parts.append(f"{head}: {body}")
    return "\n\n".join(parts) or "(none)"
