"""FR-INT-03 / FR-INT-06 / FR-AGT-12 (INTAKE-QUALITY-1): today is a fact from an injectable clock, never a model guess.
`tilo_providers.clock.time_facts` is the one place the prompt variables `today`, `deadline` and `days_to_deadline`
come from; it is pure, so a test passes a fixed date."""

from __future__ import annotations

from datetime import date

import pytest
from tilo_providers.clock import parse_deadline, real_today, time_facts

TODAY = date(2026, 10, 9)


def test_FR_INT_03_time_facts_state_today_and_the_days_left() -> None:
    facts = time_facts(TODAY, "2027-02-07")

    assert facts["today"] == "2026-10-09"
    assert facts["deadline"] == "2027-02-07"
    assert facts["days_to_deadline"] == "121 days from today"


def test_FR_INT_03_time_facts_without_a_deadline_say_so() -> None:
    for none in (None, "", "soon", "2027-13-40", 5):
        facts = time_facts(TODAY, none)
        assert facts["deadline"] == "none stated"
        assert facts["days_to_deadline"] == "no deadline, so plan a sensible span from today"


def test_FR_INT_03_time_facts_for_today_tomorrow_and_a_deadline_that_has_passed() -> None:
    assert time_facts(TODAY, "2026-10-09")["days_to_deadline"] == "the deadline is today"
    assert time_facts(TODAY, "2026-10-10")["days_to_deadline"] == "1 day from today"
    assert time_facts(TODAY, "2026-10-01")["days_to_deadline"] == "already passed, 8 days ago"


def test_FR_INT_03_parse_deadline_reads_only_an_iso_date() -> None:
    assert parse_deadline("2027-02-07") == date(2027, 2, 7)
    assert parse_deadline(date(2027, 2, 7)) == date(2027, 2, 7)
    for bad in (None, "07/02/2027", "2027-2-7", "2027-02-30", " 2027-02-07", 20270207):
        assert parse_deadline(bad) is None


def test_FR_INT_03_the_real_clock_is_the_default_and_nothing_else_reads_it() -> None:
    assert real_today() == date.today()


@pytest.mark.parametrize("today", [date(2026, 1, 1), date(2028, 2, 29)])
def test_FR_INT_03_time_facts_follow_the_date_given(today: date) -> None:
    assert time_facts(today, None)["today"] == today.isoformat()
