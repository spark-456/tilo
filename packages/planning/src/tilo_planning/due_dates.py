"""A person's words for a deadline as the brief's calendar date (SIMPLE-RUN-2, FR-INT-04).

The brief holds `deadline` as `YYYY-MM-DD` or null. A person answers in their own words ("by today", "tomorrow",
"Friday", "Today, 2026-10-14", "by the end of this week", "20 Oct"), so the answer is read against the clock here,
in code, never by a model. `parse_deadline` answers `(True, date)` for a date, `(True, None)` for "no deadline", and
`(False, None)` for words it does not understand (the caller then says so in plain words; a skip never gets here).
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

__all__ = ["DEADLINE_HELP", "parse_deadline"]

DEADLINE_HELP = "Give the deadline as a date such as 2026-10-18, or say today, tomorrow, Friday or 20 Oct; or skip it."

_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_NONE = {"none", "no", "no deadline", "no firm deadline", "n/a", "na", "nothing", "whenever", "no rush", "open"}
_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
_WEEKDAYS.update({name.lower(): i for i, name in enumerate(calendar.day_abbr)})
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_IN = re.compile(r"in (\d{1,3}|a|an|one|two|three|four|five|six|seven) (day|days|week|weeks)")
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
_LEAD = re.compile(r"^(?:(?:by|on|due|before|until|till|at|the|latest|no later than)\b[ ,]*)+")
_DAY_FIRST = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?(?: of)? ([a-z]{3,9})(?: (\d{4}))?")
_MONTH_FIRST = re.compile(r"([a-z]{3,9}) (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?")


def _month_day(month: int, day: int, year: int | None, today: date) -> date | None:
    try:
        if year is not None:
            return date(year, month, day)
        found = date(today.year, month, day)
        return found if found >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def parse_deadline(answer: str, today: date) -> tuple[bool, date | None]:
    text = " ".join(re.sub(r"[^\w\s,:/.-]", " ", answer.casefold()).split())
    if not text:
        return False, None
    iso = _ISO.search(text)
    if iso is not None:  # "Today, 2026-10-14": the written date wins over the word
        try:
            return True, date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return False, None
    if text in _NONE:
        return True, None
    text = _LEAD.sub("", text).strip(" ,.") or text
    words = text.replace(",", " ").split()
    plain = " ".join(words)
    if plain in {
        "today",
        "tonight",
        "this evening",
        "now",
        "asap",
        "right away",
        "immediately",
        "end of today",
        "end of day",
        "eod",
        "cob",
    }:
        return True, today
    if plain in {"tomorrow", "tmrw", "tmr"}:
        return True, today + timedelta(days=1)
    if plain == "day after tomorrow":
        return True, today + timedelta(days=2)
    if plain in {"end of week", "end of the week", "end of this week", "this week", "the end of this week"}:
        return True, today + timedelta(days=(4 - today.weekday()) % 7)  # the coming Friday, as the chip answer does
    if plain in {"next week", "end of next week", "the end of next week"}:
        return True, today + timedelta(days=(4 - today.weekday()) % 7 + 7)
    if plain in {"end of month", "end of the month", "end of this month", "this month"}:
        return True, today.replace(day=calendar.monthrange(today.year, today.month)[1])
    counted = _IN.fullmatch(plain)
    if counted is not None:
        n = int(counted.group(1)) if counted.group(1).isdigit() else _NUMBERS[counted.group(1)]
        return True, today + timedelta(days=n * (7 if counted.group(2).startswith("week") else 1))
    strictly_after = False
    if words and words[0] in {"this", "next", "coming"} and len(words) == 2 and words[1] in _WEEKDAYS:
        strictly_after = words[0] == "next"  # "next Friday" on a Friday is a week away; "Friday" on one is today
        words = words[1:]
    if len(words) == 1 and words[0] in _WEEKDAYS:
        gap = (_WEEKDAYS[words[0]] - today.weekday()) % 7
        return True, today + timedelta(days=gap or (7 if strictly_after else 0))
    for pattern, order in ((_DAY_FIRST, "dm"), (_MONTH_FIRST, "md")):
        found = pattern.fullmatch(plain)
        if found is None:
            continue
        name, day = (found.group(2), found.group(1)) if order == "dm" else (found.group(1), found.group(2))
        if name in _MONTHS:
            year = int(found.group(3)) if found.group(3) else None
            result = _month_day(_MONTHS[name], int(day), year, today)
            return (True, result) if result is not None else (False, None)
    return False, None
