"""FR-INT-04 (PRD 7.1), review of PR #664: the terminal's number-list pattern had a redundant `|\\s` alternative next to
`\\s*` (quadratic on long runs of spaces). "1 2" and "1   2" must still read as two options, one number is not a list,
and the digits of one number are never split. Pure function, no network.
"""

from __future__ import annotations

import time

import pytest
from tilo_evals.live_topic import _numbers


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("1 2", [1, 2]),
        ("1   2", [1, 2]),
        ("1\t2", [1, 2]),
        ("1,2", [1, 2]),
        ("1 , 2", [1, 2]),
        ("1 and 2", [1, 2]),
        ("1 & 2 + 3", [1, 2, 3]),
        ("1 2 3", [1, 2, 3]),
        ("10 11", [10, 11]),
    ],
)
def test_FR_INT_04_numbers_joined_by_a_separator_or_spaces_are_a_list(said: str, expected: list[int]) -> None:
    assert _numbers(said) == expected


@pytest.mark.parametrize("said", ["1", "12", "123", "1 234", "1 and", "and 2", "1 a 2", ""])
def test_FR_INT_04_one_number_or_split_digits_are_not_a_list(said: str) -> None:
    assert _numbers(said) is None


@pytest.mark.parametrize("said", ["1" + " " * 3000 + "x", "1" + " " * 3000 + "2" + " " * 3000 + "x", " " * 3000])
def test_FR_INT_04_a_long_run_of_spaces_is_fast(said: str) -> None:
    started = time.perf_counter()
    _numbers(said)
    assert time.perf_counter() - started < 0.5
