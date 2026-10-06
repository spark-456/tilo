"""Due-date resolution for minutes (FR-MTG-05, PE-15; BQ-PPL10-5): a closed English grammar, in code.

The anchor is the meeting's start (or creation) time read in the assignee's time zone, which gives D0, the
meeting day. Everything after that is `date` arithmetic, so daylight saving never shifts a day. A phrase that
could mean two dates is `ambiguous`, never guessed; `due` is None and the phrase is kept in `due_text`.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ._schema import is_timestamp
from .errors import PeopleInputError
from .text import clean_line

DUE_REASONS = (
    "resolved",
    "no_phrase",
    "too_long",
    "not_understood",
    "ambiguous",
    "before_meeting",
    "out_of_range",
    "bad_time_zone",
)
_PHRASE_MAX = 60
_HORIZON_DAYS = 366


@dataclass(frozen=True)
class DueResolution:
    due: str | None  # YYYY-MM-DD, set only when reason == "resolved"
    due_text: str | None = field(repr=False)  # the phrase as said, cleaned; never in a repr (CLAUDE.md)
    reason: str  # one of DUE_REASONS


class _Verdict(Exception):
    """Internal: a grammar branch that ends without a date."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_ZONE = re.compile(r"(?:UTC|[A-Z][A-Za-z_+-]*(?:/[A-Za-z0-9_+-]+){1,2})")  # the person schema's time_zone
_PREFIX = re.compile(r"(?:(?:due )?(?:by|on) |due )?(?:the )?")
_TODAY = frozenset(
    {"today", "tonight", "eod", "cob", "end of day", "end of the day", "end of today", "close of business"}
)
_EOW = frozenset({"end of week", "end of the week", "end of this week", "eow"})
_EOM = frozenset({"end of month", "end of the month", "end of this month", "eom"})
_WEEKDAYS = {
    **{n: i for i, n in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))},
    **{"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6},
}
_MONTHS = {
    **{
        n: i
        for i, n in enumerate(
            (
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ),
            1,
        )
    },
    **{"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9},
    **{"oct": 10, "nov": 11, "dec": 12},
}
_NUMBER_WORDS = {
    **{"a": 1, "an": 1},
    **{w: i for i, w in enumerate(("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), 1)},
}
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"
_ORD = r"([0-9]{1,2})(st|nd|rd|th)"
_YEAR = r"(?: ([0-9]{4}))?"
_IN = re.compile(r"in ([0-9]{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten) (day|days|week|weeks)")
_ORD_ALONE = re.compile(_ORD)
_ORD_MONTH = re.compile(rf"{_ORD}(?: of)? {_MONTH}{_YEAR}")
_NUM_MONTH = re.compile(rf"([0-9]{{1,2}}) {_MONTH}{_YEAR}")
_MONTH_ORD = re.compile(rf"{_MONTH} {_ORD}{_YEAR}")
_MONTH_NUM = re.compile(rf"{_MONTH} ([0-9]{{1,2}}){_YEAR}")
_ISO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_SLASH = re.compile(r"[0-9]{1,2}/[0-9]{1,2}(?:/[0-9]{2,4})?")
_THIS_NEXT = re.compile(r"(this|next) ([a-z]+)")


def _suffix_ok(day: int, suffix: str) -> bool:
    expected = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return suffix == expected


def _ordinal(day: str, suffix: str) -> int:
    value = int(day)
    if not 1 <= value <= 31 or not _suffix_ok(value, suffix):
        raise _Verdict("not_understood")
    return value


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _next_month(day: date) -> tuple[int, int]:
    return (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)


def _bare_ordinal(d0: date, day: int) -> date:
    year, month = (d0.year, d0.month) if day >= d0.day else _next_month(d0)
    found = _make(year, month, day)
    if found is None:
        raise _Verdict("ambiguous")
    return found


def _dated(d0: date, month: int, day: int, year: str | None) -> date:
    """`month day` with or without a year (BQ-PPL10-5)."""
    if year is not None:
        found = _make(int(year), month, day)
        if found is None:
            raise _Verdict("not_understood")
        if found < d0:
            raise _Verdict("before_meeting")
        if found.year > d0.year + 1:
            raise _Verdict("out_of_range")
        return found
    for candidate_year in (d0.year, d0.year + 1):
        found = _make(candidate_year, month, day)
        if found is not None and found >= d0:
            return found
    raise _Verdict("not_understood")


def _evaluate(key: str, d0: date) -> date:
    """The date of one normalised phrase, or `_Verdict` for the reason it has none."""
    rest = key[_PREFIX.match(key).end() :]  # type: ignore[union-attr]  # the prefix is optional: always matches
    friday = d0 - timedelta(days=d0.weekday()) + timedelta(days=4)
    if rest in _TODAY:
        return d0
    if rest == "tomorrow":
        return d0 + timedelta(days=1)
    if rest == "day after tomorrow":
        return d0 + timedelta(days=2)
    if rest in _WEEKDAYS:
        if _WEEKDAYS[rest] == d0.weekday():
            raise _Verdict("ambiguous")
        return d0 + timedelta(days=(_WEEKDAYS[rest] - d0.weekday()) % 7)
    if rest in _EOW:
        if friday < d0:
            raise _Verdict("ambiguous")
        return friday
    if rest == "end of next week":
        return friday + timedelta(days=7)
    if rest in _EOM:
        return _month_end(d0.year, d0.month)
    if rest == "end of next month":
        return _month_end(*_next_month(d0))
    if rest in ("next week", "this week") or _SLASH.fullmatch(rest):
        raise _Verdict("ambiguous")
    if m := _THIS_NEXT.fullmatch(rest):
        if m[2] not in _WEEKDAYS:
            raise _Verdict("not_understood")
        target = d0 - timedelta(days=d0.weekday()) + timedelta(days=_WEEKDAYS[m[2]])
        if m[1] == "next" or target < d0:
            raise _Verdict("ambiguous")
        return target
    if m := _IN.fullmatch(rest):
        count = int(m[1]) if m[1][0] in "0123456789" else _NUMBER_WORDS[m[1]]
        weeks = m[2].startswith("week")
        if count == 0:
            raise _Verdict("not_understood")
        if count > (52 if weeks else 365):
            raise _Verdict("out_of_range")
        return d0 + timedelta(days=7 * count if weeks else count)
    if m := _ORD_ALONE.fullmatch(rest):
        return _bare_ordinal(d0, _ordinal(m[1], m[2]))
    if m := _ORD_MONTH.fullmatch(rest):
        return _dated(d0, _MONTHS[m[3]], _ordinal(m[1], m[2]), m[4])
    if m := _MONTH_ORD.fullmatch(rest):
        return _dated(d0, _MONTHS[m[1]], _ordinal(m[2], m[3]), m[4])
    if m := _NUM_MONTH.fullmatch(rest):
        return _dated(d0, _MONTHS[m[2]], int(m[1]), m[3])
    if m := _MONTH_NUM.fullmatch(rest):
        return _dated(d0, _MONTHS[m[1]], int(m[2]), m[3])
    if m := _ISO.fullmatch(rest):
        found = _make(int(m[1]), int(m[2]), int(m[3]))
        if found is None:
            raise _Verdict("not_understood")
        if found < d0:
            raise _Verdict("before_meeting")
        return found
    raise _Verdict("not_understood")


def _key(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold().rstrip(".!")
    return " ".join(folded.replace(",", " ").split())


def _meeting_start(meeting_at: object) -> datetime:
    if not is_timestamp(meeting_at):
        raise PeopleInputError("meeting_at is not a timestamp")
    assert isinstance(meeting_at, str)
    try:
        return datetime(
            int(meeting_at[0:4]),
            int(meeting_at[5:7]),
            int(meeting_at[8:10]),
            int(meeting_at[11:13]),
            int(meeting_at[14:16]),
            int(meeting_at[17:19]),
            tzinfo=UTC,
        )
    except ValueError:
        raise PeopleInputError("meeting_at is not a timestamp") from None


def _zone(name: object) -> ZoneInfo | None:
    if not isinstance(name, str) or len(name) > 64 or not _ZONE.fullmatch(name):
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def resolve_due(due_text: object, *, meeting_at: str, time_zone: str) -> DueResolution:
    """Resolves a spoken due phrase against the meeting day in `time_zone`. Raises PeopleInputError only
    when `meeting_at` is not a timestamp; everything else is a `DueResolution` with a reason."""
    start = _meeting_start(meeting_at)
    if not isinstance(due_text, str):
        return DueResolution(None, None, "no_phrase")
    if len(due_text) > _PHRASE_MAX:
        return DueResolution(None, None, "too_long")
    text = " ".join(clean_line(due_text).split())
    if not text:
        return DueResolution(None, None, "no_phrase")
    zone = _zone(time_zone)
    if zone is None:
        return DueResolution(None, text, "bad_time_zone")
    try:
        d0 = start.astimezone(zone).date()
    except (OverflowError, ValueError):
        raise PeopleInputError("meeting_at is out of range") from None
    try:
        due = _evaluate(_key(text), d0)
        if (due - d0).days > _HORIZON_DAYS:
            return DueResolution(None, text, "out_of_range")
    except _Verdict as verdict:
        return DueResolution(None, text, verdict.reason)
    except OverflowError:
        return DueResolution(None, text, "out_of_range")
    if due < d0:
        return DueResolution(None, text, "before_meeting")
    return DueResolution(due.isoformat(), text, "resolved")
