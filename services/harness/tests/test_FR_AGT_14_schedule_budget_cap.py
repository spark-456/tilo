"""FR-AGT-14 (security review): a schedule's budget cap is the owner's own cap for every firing (PRD 14, 10.4), so a
record with no usable cap never reaches a run start."""

from __future__ import annotations

import pytest
from schedule_support import make_schedule


@pytest.mark.parametrize("cap", [float("nan"), float("inf"), -5.0, 0.0, 0, True, "40", None])
def test_FR_AGT_14_a_schedule_without_a_finite_positive_budget_cap_is_refused(cap):
    with pytest.raises(ValueError, match="budget_cap"):
        make_schedule(budget_cap=cap)


def test_FR_AGT_14_a_finite_positive_budget_cap_is_accepted():
    assert make_schedule(budget_cap=0.5).budget_cap == 0.5
