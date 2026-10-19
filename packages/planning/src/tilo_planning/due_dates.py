"""A person's words for a deadline as the brief's calendar date (SIMPLE-RUN-2, FR-INT-04).

The brief holds `deadline` as `YYYY-MM-DD` or null. A person answers in their own words ("by today", "tomorrow",
"Friday", "Today, 2026-10-14", "by the end of this week", "20 Oct"), so the answer is read against the clock here,
in code, never by a model. `parse_deadline` answers `(True, date)` for a date, `(True, None)` for "no deadline", and
`(False, None)` for words it does not understand (the caller then says so in plain words; a skip never gets here).
"""

from __future__ import annotations

import calendar
import functools
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

__all__ = ["DEADLINE_HELP", "parse_deadline"]

DEADLINE_HELP = "Give the deadline as a date such as 2026-10-18, or say today, tomorrow, Friday or 20 Oct; or skip it."

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "deadline_phrases.yaml"
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
_WEEKDAYS.update({name.lower(): i for i, name in enumerate(calendar.day_abbr)})
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_DAY_FIRST = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?(?: of)? ([a-z]{3,9})(?: (\d{4}))?")
_MONTH_FIRST = re.compile(r"([a-z]{3,9}) (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?")


class _Phrases:
    """config/deadline_phrases.yaml, read once: the word lists as sets and the two patterns built from them."""

    def __init__(self, raw: dict[str, Any]) -> None:
        def words(key: str) -> frozenset[str]:
            value = raw[key]
            if not isinstance(value, list) or not all(isinstance(w, str) for w in value):
                raise ValueError(f"{_CONFIG.name}: {key} must be a list of words")
            return frozenset(w.casefold() for w in value)

        self.none, self.today, self.tomorrow = words("no_deadline"), words("today"), words("tomorrow")
        self.after_tomorrow = words("day_after_tomorrow")
        self.end_of_week, self.end_of_next_week = words("end_of_week"), words("end_of_next_week")
        self.end_of_month = words("end_of_month")
        lead = sorted(words("lead_words"), key=len, reverse=True)
        self.lead = re.compile(r"^(?:(?:" + "|".join(re.escape(w) for w in lead) + r")\b[ ,]*)+")
        count = raw["in_count"]
        self.numbers: dict[str, int] = {str(k).casefold(): int(v) for k, v in count["numbers"].items()}
        units = {
            **{str(u).casefold(): 1 for u in count["day_units"]},
            **{str(u).casefold(): 7 for u in count["week_units"]},
        }
        self.unit_days = units
        names = "|".join(sorted((re.escape(n) for n in self.numbers), key=len, reverse=True))
        self.counted = re.compile(rf"in (\d{{1,3}}|{names}) ({'|'.join(re.escape(u) for u in units)})")
        self.prefixes: dict[str, bool] = {str(k).casefold(): bool(v) for k, v in raw["weekday_prefixes"].items()}


@functools.cache
def _phrases() -> _Phrases:
    return _Phrases(yaml.safe_load(_CONFIG.read_text(encoding="utf-8")))


def _month_day(month: int, day: int, year: int | None, today: date) -> date | None:
    try:
        if year is not None:
            return date(year, month, day)
        found = date(today.year, month, day)
        return found if found >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def parse_deadline(answer: str, today: date) -> tuple[bool, date | None]:
    p = _phrases()
    text = " ".join(re.sub(r"[^\w\s,:/.-]", " ", answer.casefold()).split())
    if not text:
        return False, None
    iso = _ISO.search(text)
    if iso is not None:  # "Today, 2026-10-14": the written date wins over the word
        try:
            return True, date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return False, None
    if text in p.none:
        return True, None
    text = p.lead.sub("", text).strip(" ,.") or text
    words = text.replace(",", " ").split()
    plain = " ".join(words)
    friday = today + timedelta(days=(4 - today.weekday()) % 7)  # the coming Friday, as the chip answer does
    if plain in p.today:
        return True, today
    if plain in p.tomorrow:
        return True, today + timedelta(days=1)
    if plain in p.after_tomorrow:
        return True, today + timedelta(days=2)
    if plain in p.end_of_week:
        return True, friday
    if plain in p.end_of_next_week:
        return True, friday + timedelta(days=7)
    if plain in p.end_of_month:
        return True, today.replace(day=calendar.monthrange(today.year, today.month)[1])
    counted = p.counted.fullmatch(plain)
    if counted is not None:
        n = int(counted.group(1)) if counted.group(1).isdigit() else p.numbers[counted.group(1)]
        return True, today + timedelta(days=n * p.unit_days[counted.group(2)])
    strictly_after = False
    if len(words) == 2 and words[0] in p.prefixes and words[1] in _WEEKDAYS:
        strictly_after = p.prefixes[words[0]]  # "next Friday" on a Friday is a week away; "Friday" on one is today
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
