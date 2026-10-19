"""PPL-11c-FS: the emulator's ready timeout is 240 s by default (a cold start takes about 2.5 minutes) and can be
set with `TILO_EMULATOR_READY_TIMEOUT_S`; a value that is not a finite number above zero falls back to the default."""

from __future__ import annotations

import pytest
from tilo_harness import emulator


def test_PPL_11c_FS_ready_timeout_defaults_to_240_seconds() -> None:
    assert emulator.ready_timeout_s({}) == 240.0


def test_PPL_11c_FS_ready_timeout_reads_the_environment_variable() -> None:
    assert emulator.ready_timeout_s({"TILO_EMULATOR_READY_TIMEOUT_S": "300"}) == 300.0
    assert emulator.ready_timeout_s({"TILO_EMULATOR_READY_TIMEOUT_S": "12.5"}) == 12.5


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5", "nan", "inf", "-inf", "1e999", " "])
def test_PPL_11c_FS_ready_timeout_falls_back_on_a_bad_value(raw: str) -> None:
    assert emulator.ready_timeout_s({"TILO_EMULATOR_READY_TIMEOUT_S": raw}) == 240.0
