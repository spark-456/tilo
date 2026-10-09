"""FR-CAL-07 (b): resolve_due returns `out_of_range` instead of raising for a meeting day near the year 9999."""

from __future__ import annotations

import pytest
from tilo_people.dates import resolve_due


@pytest.mark.parametrize("phrase", ["end of next month", "end of next week", "in 2 weeks", "tomorrow"])
def test_FR_CAL_07b_resolve_due_never_raises_near_year_9999(phrase: str) -> None:
    found = resolve_due(phrase, meeting_at="9999-12-31T12:00:00.000Z", time_zone="UTC")
    assert found.reason in {"out_of_range", "resolved"} and (found.reason != "resolved" or found.due)


def test_FR_CAL_07b_end_of_next_month_in_december_9999_is_out_of_range() -> None:
    found = resolve_due("end of next month", meeting_at="9999-12-31T12:00:00.000Z", time_zone="UTC")
    assert found.due is None and found.reason == "out_of_range"
