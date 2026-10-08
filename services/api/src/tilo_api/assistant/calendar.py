"""FR-CAL-07 (a): the panel's two calendar answers over the person's own, accepted entries (API_FR_CAL_07a.md).
`listed` is the calendar of `calendar_today`; `prepare_lines` resolves one entry by its start time today and lists
its own fields and the records linked to it that the oracle shows the person. Pure: reads through the gate only,
writes nothing, never prints quote text (ADR-0020) and never normalises a title."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC
from typing import Any

from tilo_people.text import clean_line

from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.facts import Line, clock_of, fill, moment_of, zone_of
from tilo_api.assistant.gate import Ref, RefGate
from tilo_api.assistant.navigation import route_for
from tilo_api.assistant.words import words

Row = Mapping[str, Any]
# H, H:MM, with am/pm attached or as the next word; a colon without am/pm is a 24-hour time. A bare number is no time.
_TIME = re.compile(r"(?<![\w:.])([0-9]{1,2})(?::([0-9]{2}))?(?:\s?(am|pm))?(?![\w:])")
_TITLE_MAX = 140
_OTHER_DAYS = frozenset({"tomorrow", "yesterday"})


def listed(rows: Sequence[Row], gate: RefGate, user: str) -> list[tuple[Row, Mapping[str, Any]]]:
    """(plate row, entry as the oracle shows it) for the rows of calendar entries the person owns and has accepted."""
    out = []
    for row in rows:
        if row["reason"] != "calendar" or row["ref"]["kind"] != "calendar_entry":
            continue
        record = gate.record(Ref("calendar_entry", row["ref"]["id"]))
        if record is not None and record.get("owner") == user and record.get("state") == "accepted":
            out.append((row, record))
    return out


def time_asked(key: str, config: AssistantConfig) -> tuple[int, int] | None:
    """The one distinct time of day the (normalised) question names, else None: no time, an invalid one, two different
    ones, or another day (BQ-CAL07-3). One linear pass; it stops at the second distinct time."""
    if _OTHER_DAYS & set(words(key, config)):
        return None
    found: set[tuple[int, int]] = set()
    for match in _TIME.finditer(key):
        hour_text, minute_text, meridiem = match.groups()
        if minute_text is None and meridiem is None:
            continue
        hour, minute = int(hour_text), int(minute_text or 0)
        if minute > 59 or (hour > 23 if meridiem is None else not 1 <= hour <= 12):
            return None
        if meridiem is not None:
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        found.add((hour, minute))
        if len(found) > 1:
            return None
    return next(iter(found)) if found else None


def _title(record: Mapping[str, Any], config: AssistantConfig) -> str:
    title = record.get("title")
    return (clean_line(title)[:_TITLE_MAX] if isinstance(title, str) else "") or config.answer["untitled"]


def _linked(entry: Mapping[str, Any], gate: RefGate, config: AssistantConfig) -> list[Line]:
    """The meeting the person may read and the released action item, cited by title and record only."""
    a, lines = config.answer, list[Line]()
    source, made = entry.get("source"), entry.get("created_by")
    if not (isinstance(source, Mapping) and isinstance(made, Mapping) and made.get("by") == "tilo"):
        return lines
    ref = source.get("ref")
    if not isinstance(ref, str):
        return lines
    if source.get("kind") == "tilo" and source.get("from") == "meeting":
        meeting = Ref("meeting", ref.split("#")[0])
        record = gate.record(meeting)
        if record is not None:
            lines.append(Line(fill(a["prepare"]["meeting"], label=_title(record, config)), meeting))
    item = gate.released(entry) if "#" in ref else None
    record = None if item is None else gate.record(item)
    if item is not None and record is not None:
        text = fill(a["prepare"]["item"], label=_title(record, config))
        if record.get("due") is not None:
            text += fill(a["due_suffix"], due=record["due"])
        lines.append(Line(text + (a["flagged_suffix"] if record.get("flagged") else ""), item))
    return lines


def prepare_lines(
    key: str,
    rows: Sequence[Row],
    *,
    user: str,
    now: str,
    tz: str | None,
    gate: RefGate,
    config: AssistantConfig,
) -> tuple[tuple[Line, ...], Mapping[str, Any] | None]:
    """((), None) when the question does not name exactly one of today's entries (the `which_entry` decline)."""
    want, moment, zone = time_asked(key, config), moment_of(now), zone_of(tz)
    if want is None or moment is None:
        return (), None
    day = moment.astimezone(zone or UTC).date()
    found = []
    for _, record in listed(rows, gate, user):
        start = moment_of(record.get("start"))
        local = None if start is None else start.astimezone(zone or UTC)
        if local is not None and local.date() == day and (local.hour, local.minute) == want:
            found.append(record)
    if len(found) != 1:
        return (), None
    entry, a = found[0], config.answer
    ref, p = Ref("calendar_entry", entry["id"]), a["prepare"]
    opens, end = clock_of(entry["start"], zone), entry.get("end")
    first = (
        fill(p["entry_open"], label=_title(entry, config), start=opens)
        if end is None
        else fill(p["entry"], label=_title(entry, config), start=opens, end=clock_of(end, zone))
    )
    lines = [Line(p["header"], None), Line(first + (a["flagged_suffix"] if entry.get("flagged") else ""), ref)]
    if isinstance(entry.get("attendee_count"), int) and entry["attendee_count"] > 0:
        lines.append(Line(fill(p["attendees"], n=str(entry["attendee_count"])), ref))
    links = _linked(entry, gate, config)
    return (*lines, *(links or [Line(p["nothing"], None)])), route_for(ref, gate)
