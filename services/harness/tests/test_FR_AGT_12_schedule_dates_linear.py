"""FR-AGT-12, INTAKE-QUALITY-1 re-review: the date-window check runs synchronously inside the unit runner, so every
rule of `schedule_dates` must be linear in the text. A pathological 200,000-character line built to defeat each cue
pattern (from, to, start, week, by, table pipes, citation cues, "May", month and digit runs) finishes in well under
two seconds, and a date on the same line is still found."""

from __future__ import annotations

import time
from datetime import date

import pytest
from tilo_harness.schedule_dates import CUE_SCAN_CHARS, date_window_fail, out_of_window

TODAY = date(2026, 10, 9)
DEADLINE = date(2027, 2, 7)
SIZE = 200_000
LIMIT_S = 2.0

CASES = {
    "from": "from " * (SIZE // 5),
    "from_no_to_x": "from " * (SIZE // 10) + "x" * (SIZE // 2),
    "to": "to " * (SIZE // 3),
    "start": "start" * (SIZE // 5),
    "week": "week " * (SIZE // 5),
    "by": "by " * (SIZE // 3),
    "by_spaces": "by" + " " * SIZE,
    "table_pipes": "|" * SIZE,
    "table_rows": "|\n" * (SIZE // 2),
    "table_wide_rows": ("| " + "x" * 50 + " |\n") * (SIZE // 55),
    "published": "published " * (SIZE // 10),
    "source": "source " * (SIZE // 7),
    "source_spaces": "source" + " " * SIZE,
    "author_year": "(A" * (SIZE // 2),
    "author_long": "(" + "A" * SIZE,
    "author_spaces": "(A" + " " * SIZE,
    "et_al": "(Smith et al " * (SIZE // 13),
    "may": "May " * (SIZE // 4),
    "month_runs": "Mar " * (SIZE // 4),
    "month_spaces": "Mar" + " " * SIZE + "x",
    "digit_pairs": "1 " * (SIZE // 2),
    "digits": "1" * SIZE,
    "iso_runs": "2025-" * (SIZE // 5),
    "ordinal_runs": "1st " * (SIZE // 4),
    "of_runs": "1 of " * (SIZE // 5),
    "newlines": "\n" * SIZE,
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_FR_AGT_12_a_pathological_line_is_read_in_linear_time(name: str) -> None:
    text = CASES[name]
    began = time.perf_counter()
    out_of_window(text, TODAY, DEADLINE)
    date_window_fail(text, TODAY, DEADLINE)

    assert time.perf_counter() - began < LIMIT_S, f"{name}: more than {LIMIT_S}s"


@pytest.mark.parametrize("name", ["from", "start", "by", "published", "table_pipes", "may", "month_runs"])
def test_FR_AGT_12_a_date_at_the_end_of_a_pathological_line_is_still_found(name: str) -> None:
    # inside the scanned prefix, after the deadline: found wherever it stands, cues or not
    text = CASES[name][: SIZE - 20] + " 3 Nov 2031"
    began = time.perf_counter()
    found = [f.quote for f in out_of_window(text, TODAY, DEADLINE)]

    assert time.perf_counter() - began < LIMIT_S
    assert found and found[-1].endswith("Nov 2031")


def test_FR_AGT_12_cues_are_read_only_in_the_first_chars_of_a_line() -> None:
    far = "x" * (CUE_SCAN_CHARS + 10)
    assert out_of_window(far + " start 3 March 2025", TODAY, DEADLINE) == []  # the cue is out of reach
    assert [f.quote for f in out_of_window("Start 3 March 2025 " + far, TODAY, DEADLINE)] == ["3 March 2025"]


def test_FR_AGT_12_from_to_is_a_schedule_cue_and_to_before_from_is_not() -> None:
    assert [f.quote for f in out_of_window("Revise from 3 March 2025 to 5 April 2026", TODAY, DEADLINE)] == [
        "3 March 2025",
        "5 April 2026",
    ]
    assert out_of_window("Back to the notes of 3 March 2025, from the author", TODAY, DEADLINE) == []


def test_FR_AGT_12_the_reason_is_cut_at_140_chars_on_a_quote_boundary() -> None:
    fail = date_window_fail("Start 2025-01-01, 2025-01-02, 2025-01-03", TODAY, DEADLINE)

    assert fail is not None and len(fail.reason) <= 140
    assert fail.reason.count('"') % 2 == 0
