"""FR-PA-13: answers are templates over the signed-in person's own, already gated, plate rows (section 5).
Deterministic: no model writes a line, and every claim line cites the row it stands on (HR-1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from string import Template
from typing import Any
from zoneinfo import ZoneInfo

from tilo_api.assistant.config import AssistantConfig, FactIntent
from tilo_api.assistant.gate import Ref
from tilo_api.assistant.words import question_key, words

_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True)
class Line:
    text: str
    source: Ref | None  # None: a header or the "more" line (they claim nothing)


def match_fact(key: str, config: AssistantConfig) -> FactIntent | None:
    """The first intent in config order whose every `when` group shares a word with the question."""
    asked = set(words(key, config))
    return next((i for i in config.facts if all(group & asked for group in i.when)), None)


def remainder_of(key: str, intent: FactIntent, config: AssistantConfig) -> frozenset[str]:
    """The question's words that say neither what is asked (`when`) nor filler (`question_stop`)."""
    named = frozenset().union(*intent.when)
    return frozenset(words(key, config)) - config.words["question_stop"] - named


def moment_of(stamp: Any) -> datetime | None:
    try:
        return datetime.strptime(stamp, _STAMP).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _passes(intent: FactIntent, row: Mapping[str, Any], as_of: datetime | None) -> bool:
    f, kind = intent.rows, row["ref"]["kind"]
    if f.reasons is not None and row["reason"] not in f.reasons:
        return False
    if f.groups is not None and row["group"] not in f.groups:
        return False
    if f.kinds is not None and kind not in f.kinds:
        return False
    if f.has_due and row["due"] is None:
        return False
    if f.within_hours is not None:
        at = moment_of(row["at"])
        if at is None or as_of is None or not as_of - timedelta(hours=f.within_hours) <= at <= as_of:
            return False
    return True


def _title_words(row: Mapping[str, Any], config: AssistantConfig) -> set[str]:
    title = row["title"]
    return set(words(question_key(title), config)) if isinstance(title, str) else set()


def _narrow(
    selected: list[Mapping[str, Any]], context: Ref | None, remainder: frozenset[str], config: AssistantConfig
) -> list[Mapping[str, Any]]:
    """The selected record, else the one row whose title holds the rest of the question, else every row."""
    if context is not None:
        chosen = [r for r in selected if Ref(r["ref"]["kind"], r["ref"]["id"]) == context]
        if chosen:
            return chosen
    if remainder:
        holding = [r for r in selected if remainder <= _title_words(r, config)]
        if len(holding) == 1:
            return holding
    return selected


def fill(template: str, **values: str) -> str:
    """A config template filled with plain values; a value is data and is never read as a template."""
    filler = Template(template)
    return filler.substitute(**values)


def claim(row: Mapping[str, Any], template: str, config: AssistantConfig, *, time: str = "", due: bool = True) -> str:
    """One claim line: the row's title (or its kind's label) in `template`, plus the due and flagged suffixes."""
    a = config.answer
    label = row["title"] or a["kind_labels"].get(row["ref"]["kind"]) or a["untitled"]
    text = fill(template, label=label, time=time)
    if due and row["due"] is not None and row["reason"] != "calendar":
        text += fill(a["due_suffix"], due=row["due"])
    return text + a["flagged_suffix"] if row["flagged"] else text


def _clock(at: Any, zone: ZoneInfo | None) -> str:
    moment = moment_of(at)
    if moment is None:
        return ""
    return moment.strftime("%H:%M") + " UTC" if zone is None else moment.astimezone(zone).strftime("%H:%M")


def zone_of(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if isinstance(name, str) else None
    except Exception:
        return None


def fact_lines(
    intent: FactIntent,
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    context: Ref | None,
    remainder: frozenset[str],
    time_zone: str | None,
    config: AssistantConfig,
) -> tuple[tuple[Line, ...], Mapping[str, Any] | None]:
    """(lines, offered ui_action). Nothing selected: one `intent.empty` line that claims nothing."""
    moment = moment_of(as_of)
    selected = [r for r in rows if _passes(intent, r, moment)]
    if intent.narrow:
        selected = _narrow(selected, context, remainder, config)
    if not selected:
        return (Line(intent.empty, None),), None
    a, zone = config.answer, zone_of(time_zone)
    lines = [] if intent.header is None else [Line(intent.header, None)]
    shown, last = 0, None
    for row in selected:
        if shown == a["max_lines"]:
            break
        if intent.header is None and row["group"] != last and row["group"] in a["group_headers"]:
            lines.append(Line(a["group_headers"][row["group"]], None))
        last = row["group"]
        text = claim(row, a["lines"][row["reason"]], config, time=_clock(row["at"], zone))
        lines.append(Line(text, Ref(row["ref"]["kind"], row["ref"]["id"])))
        shown += 1
    if len(selected) > a["max_lines"]:
        lines.append(Line(a["more"], None))
        return tuple(lines), {"kind": "navigate", "route": "plate", "target": None}
    return tuple(lines), None
