"""Loader error-count cap (EFF-07; PR #35 note): many schema errors are capped, not all of them scanned/joined."""

import time

import pytest
from conftest import write_case
from tilo_evals import CaseError, load_cases

_MANY = 20_000  # comfortably beyond the 20-error cap; large enough to expose an O(n) join/sort regression


def test_EFF_07_load_cases_caps_schema_errors_reported_to_20(tmp_path):
    write_case(
        tmp_path / "cases",
        case_id="E-PLAN-01",
        group="E-PLAN",
        ground_truth={"ok": True},
        scripted_answers=[0] * _MANY,  # each item is a schema error: "N is not of type 'object'"
    )
    start = time.monotonic()
    with pytest.raises(CaseError) as info:
        load_cases(root=str(tmp_path / "cases"))
    elapsed = time.monotonic() - start
    assert str(info.value).count("is not of type") <= 20
    # A loader that reports "at most 20" must not sort/format all `_MANY` errors first: that costs seconds.
    assert elapsed < 2.0, f"loader scanned far more than 20 of {_MANY} schema errors ({elapsed:.2f}s)"
