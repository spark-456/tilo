"""A deterministic date-window check for a deliverable's schedule (FR-AGT-12; INTAKE-QUALITY-1, 9 Oct 2026).

A model that is not told today's date plans from its training data: a 24-month roadmap starting March 2025 for a Feb
2027 exam. Telling it the date (`tilo_providers.clock`) is one half; this is the other. Before any model verifier call,
code reads the dates in the work under review and fails the unit when one is outside today..deadline, quoting the
date. No model, no network, linear in the text (bounded by `MAX_SCAN_CHARS`).

Forms read: `RECOGNISED_FORMS`. Anything else is NOT checked (a model verifier may still judge it): a numeric
01/03/2025, a bare year, a quarter, a season, "Week 3", "in 18 months", a month with no year; "May" only as a capital
M; a date that is not a real calendar day (31 Feb) is skipped.

Where it reads them (a past date in a source list is not a schedule error):
- A date AFTER the deadline fails wherever it stands.
- A date BEFORE today fails only in schedule-like context: its line (for a table, any line of its table, so a header
  "Week | Date" covers the rows) holds a schedule cue (`SCHEDULE_CUES`), or "by" stands right before it; and its line
  holds no citation cue (`CITATION_CUES`). "Smith 2019, 12 March 2019" and "Published 3 March 2025" pass; "Week 1
  (3 March 2025): start" fails. A line that is both a schedule and a citation is not read for past dates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MAX_SCAN_CHARS = 200_000  # the prefix of the work that is read
MAX_FINDINGS = 50
MAX_SHOWN = 5  # dates quoted in the verdict
MAX_REASON = 140  # world.failed `reason` (contracts/events/data/world.failed.schema.json)
MIN_YEAR, MAX_YEAR = 1990, 2100  # a four-digit number outside this is not a year ("May 5000 words")
RECOGNISED_FORMS = (
    "ISO date: 2026-11-03",
    "day month year: 3 Nov 2026, 3rd November 2026, 3 of November 2026",
    "month day year: Nov 3, 2026, November 3rd 2026",
    "month year: March 2025, Mar 2025 (judged by its month: the current month and the deadline's month are inside)",
    "Other forms are not checked: numeric dates such as 01/03/2025, a bare year, quarters, seasons, weeks, "
    "relative spans, a month without a year, and impossible days such as 31 Feb.",
)
SCHEDULE_CUES = (  # generic words of a plan's timing; no subject words
    "start, begin, due, deliver, milestone, phase, week, day, month, session, revise/revision, mock, exam, deadline, "
    "schedule, sprint, finish, until, 'from .. to', and 'by' right before the date"
)
CITATION_CUES = (  # a line holding one is a reference, not a schedule
    "published, publication, accessed, retrieved, 'source:', et al, doi, vol., pp., reference, cited, copyright, "
    "isbn, '(Author 2019)'"
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
_MONTH = "(?:" + "|".join("(?-i:May)" if n == "may" else n for n in sorted(_MONTHS, key=len, reverse=True)) + ")"
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
_SCHEDULE = re.compile(
    r"\b(?:start(?:s|ed|ing)?|begin(?:s|ning)?|due|deliver(?:y|ies|s|ed|able|ables)?|milestones?|phases?|weeks?|weekly"
    r"|days?|daily|months?|monthly|sessions?|revis(?:e|es|ed|ion|ions|ing)|mock|exams?|deadlines?|schedules?|sprints?"
    r"|finish(?:es|ed)?|until)\b|\bfrom\b[^\n]*\bto\b",
    re.IGNORECASE,
)
_BY_BEFORE = re.compile(r"\bby\s+(?:the\s+)?(?:end\s+of\s+)?$", re.IGNORECASE)
_CITATION = re.compile(
    r"\b(?:published|publication|accessed|retrieved|et\s+al|doi|isbn|reference|references|cited|copyright)\b"
    r"|\bsources?\s*:|\b(?:vol|pp)\.|(?-i:\([A-Z][\w'-]+(?:\s+et\s+al\.?)?,?\s+\d{4}[a-z]?\))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DateFinding:
    quote: str  # the date as written in the work
    when: date  # the date it stands for (the first of the month for a month and year)
    kind: str  # "before_today" | "after_deadline"


@dataclass(frozen=True)
class WindowFail:
    verdict: str  # `FAIL` on the first line, then one sentence quoting the dates
    reason: str  # one short plain line (at most MAX_REASON characters) for the run's own stop notice


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
    """The dates in `text` (its first `MAX_SCAN_CHARS` characters) after `deadline` anywhere, or before `today` in a
    schedule-like line (see the module notes), in reading order. A month and year is compared by month; a full date by
    day. `deadline=None` checks only the past."""
    found: list[DateFinding] = []
    lines = text[:MAX_SCAN_CHARS].splitlines()
    index = 0
    while index < len(lines):
        end = index + 1
        if lines[index].lstrip().startswith("|"):  # a table: its header's cue covers its rows
            while end < len(lines) and lines[end].lstrip().startswith("|"):
                end += 1
        block = lines[index:end]
        index = end
        scheduled = any(_SCHEDULE.search(line) for line in block)
        for line in block:
            cited = _CITATION.search(line) is not None
            for match in _DATE.finditer(line):
                read = _read(match)
                if read is None:
                    continue
                when, month_only = read
                key, kind = _key(when, month_only), None
                if key < _key(today, month_only):
                    if (scheduled or _BY_BEFORE.search(line[: match.start()])) and not cited:
                        kind = "before_today"
                elif deadline is not None and key > _key(deadline, month_only):
                    kind = "after_deadline"
                if kind is not None:
                    found.append(DateFinding(" ".join(match.group(0).split()), when, kind))
                    if len(found) >= MAX_FINDINGS:
                        return found
    return found


def date_window_fail(text: str, today: date, deadline: date | None) -> WindowFail | None:
    """The Verifier's deterministic FAIL when `text` holds a date outside the window, else None (the model verifier
    decides). The reason is plain, code-written text built only from the matched dates."""
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
    verdict = f"FAIL\nSchedule dates outside the window ({window}): {'; '.join(reasons)}{more}."
    shown = ", ".join(f'"{quote}"' for quote, _ in unique[:2]) + (", and more" if len(unique) > 2 else "")
    return WindowFail(verdict, f"The work has dates outside today to the deadline: {shown}"[:MAX_REASON])


def date_window_verdict(text: str, today: date, deadline: date | None) -> str | None:
    """`date_window_fail(...).verdict`, or None."""
    fail = date_window_fail(text, today, deadline)
    return None if fail is None else fail.verdict
