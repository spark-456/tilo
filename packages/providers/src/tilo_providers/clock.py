"""The date the prompts state as a fact (FR-INT-03, FR-INT-06, FR-AGT-12; INTAKE-QUALITY-1). A model does not know
today's date and guesses one from its training data, so a plan starts in the wrong year. Every prompt that plans or
checks a schedule is given `today`, `deadline` and `days_to_deadline` as plain text from here instead.

`Clock` is the injectable seam: production passes nothing and gets the real date (`real_today`); a test passes a fixed
date, so a prompt, and therefore its recording key, does not move from day to day."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

Clock = Callable[[], date]

NO_DEADLINE = "none stated"
NO_DEADLINE_SPAN = "no deadline, so plan a sensible span from today"


def real_today() -> date:
    """The default clock: the date on the machine that runs Tilo."""
    return date.today()


def parse_deadline(value: Any) -> date | None:
    """A brief's `deadline` (`YYYY-MM-DD`) as a date; anything else, including a date in another shape, is None."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def time_facts(today: date, deadline: Any = None) -> dict[str, str]:
    """The prompt variables `today`, `deadline` and `days_to_deadline` for `today` and a brief's deadline."""
    due = parse_deadline(deadline)
    if due is None:
        return {"today": today.isoformat(), "deadline": NO_DEADLINE, "days_to_deadline": NO_DEADLINE_SPAN}
    left = (due - today).days
    if left > 0:
        text = f"{_days(left)} from today"
    elif left == 0:
        text = "the deadline is today"
    else:
        text = f"already passed, {_days(-left)} ago"
    return {"today": today.isoformat(), "deadline": due.isoformat(), "days_to_deadline": text}
