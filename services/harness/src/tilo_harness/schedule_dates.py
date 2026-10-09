"""A deterministic date-window check for a deliverable's schedule (FR-AGT-12; INTAKE-QUALITY-1, 9 Oct 2026).

A model that is not told today's date plans from its training data: a 24-month roadmap starting March 2025 for a Feb
2027 exam. Telling it the date (`tilo_providers.clock`) is one half; this is the other. Before any model verifier call,
code reads the dates in the work under review and fails the unit's verification when one is before today or after the
brief's deadline, quoting the date. No model, no network, linear in the text (bounded by `MAX_SCAN_CHARS`).

The forms it recognises are listed in `RECOGNISED_FORMS`. Anything else is NOT checked (a model verifier may still
judge it): a numeric 01/03/2025, a bare year, a quarter, a season, "Week 3", "in 18 months", a month with no year. A
date that is not a real calendar day (31 Feb) is skipped. It cannot tell a schedule date from a date in a citation, so
"published 12 March 2024" in the text also fails; the quoted date shows why."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MAX_SCAN_CHARS = 200_000  # the prefix of the work that is read
MAX_FINDINGS = 50
MAX_SHOWN = 5  # dates quoted in the verdict
MIN_YEAR, MAX_YEAR = 1990, 2100  # a four-digit number outside this is not a year ("May 5000 words")
RECOGNISED_FORMS = (
    "ISO date: 2026-11-03",
    "day month year: 3 Nov 2026, 3rd November 2026, 3 of November 2026",
    "month day year: Nov 3, 2026, November 3rd 2026",
    "month year: March 2025, Mar 2025 (judged by its month: the current month and the deadline's month are inside)",
    "Other forms are not checked: numeric dates such as 01/03/2025, a bare year, quarters, seasons, weeks, "
    "relative spans, a month without a year, and impossible days such as 31 Feb.",
)

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
            ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
            ("nov", "november"), ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}  # fmt: skip
_MONTH = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"  # longest first: "sept" before "sep"
_DATE = re.compile(
    rf"""
    (?<![\d-])(?P<iso_y>\d{{4}})-(?P<iso_m>\d{{2}})-(?P<iso_d>\d{{2}})(?!\d)
  | (?<!\d)(?P<dmy_d>\d{{1,2}})(?:st|nd|rd|th)?[ \t]+(?:of[ \t]+)?
    (?P<dmy_m>{_MONTH})\b\.?,?[ \t]+(?P<dmy_y>\d{{4}})(?!\d)
  | \b(?P<mdy_m>{_MONTH})\b\.?[ \t]+(?P<mdy_d>\d{{1,2}})(?:st|nd|rd|th)?,?[ \t]+(?P<mdy_y>\d{{4}})(?!\d)
  | \b(?P<my_m>{_MONTH})\b\.?,?[ \t]+(?P<my_y>\d{{4}})(?!\d)
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class DateFinding:
    quote: str  # the date as written in the work
    when: date  # the date it stands for (the first of the month for a month and year)
    kind: str  # "before_today" | "after_deadline"


def _read(match: re.Match[str]) -> tuple[date, bool] | None:
    """(the date, whether only its month counts), or None for an impossible day or a number that is not a year."""
    groups = match.groupdict()
    for prefix in ("iso", "dmy", "mdy", "my"):
        year_text, month_text = groups.get(f"{prefix}_y"), groups.get(f"{prefix}_m")
        if year_text is None or month_text is None:
            continue
        day_text = groups.get(f"{prefix}_d")
        year = int(year_text)
        month = int(month_text) if prefix == "iso" else _MONTHS[month_text.lower()]
        if not MIN_YEAR <= year <= MAX_YEAR:
            return None
        try:
            return date(year, month, int(day_text) if day_text else 1), day_text is None
        except ValueError:
            return None
    return None


def _key(day: date, month_only: bool) -> tuple[int, int, int]:
    return (day.year, day.month, 0 if month_only else day.day)


def out_of_window(text: str, today: date, deadline: date | None) -> list[DateFinding]:
    """The dates in `text` (its first `MAX_SCAN_CHARS` characters) before `today` or after `deadline`, in reading
    order. A month and year is compared by month; a full date by day. `deadline=None` checks only the past."""
    found: list[DateFinding] = []
    for match in _DATE.finditer(text[:MAX_SCAN_CHARS]):
        read = _read(match)
        if read is None:
            continue
        when, month_only = read
        key = _key(when, month_only)
        kind = None
        if key < _key(today, month_only):
            kind = "before_today"
        elif deadline is not None and key > _key(deadline, month_only):
            kind = "after_deadline"
        if kind is not None:
            found.append(DateFinding(" ".join(match.group(0).split()), when, kind))
            if len(found) >= MAX_FINDINGS:
                break
    return found


def date_window_verdict(text: str, today: date, deadline: date | None) -> str | None:
    """A Verifier verdict (`FAIL` on the first line, then one sentence quoting the dates) when `text` holds a date
    outside the window, else None and the model verifier decides."""
    found = out_of_window(text, today, deadline)
    if not found:
        return None
    unique = list(dict.fromkeys((f.quote, f.kind) for f in found))
    reasons = [
        f'"{quote}" is before today ({today.isoformat()})'
        if kind == "before_today"
        else f'"{quote}" is after the deadline ({deadline.isoformat() if deadline else ""})'
        for quote, kind in unique[:MAX_SHOWN]
    ]
    more = f" and {len(unique) - MAX_SHOWN} more" if len(unique) > MAX_SHOWN else ""
    window = f"today {today.isoformat()}, " + (f"deadline {deadline.isoformat()}" if deadline else "no deadline")
    return f"FAIL\nSchedule dates outside the window ({window}): {'; '.join(reasons)}{more}."
