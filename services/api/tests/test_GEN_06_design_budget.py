"""GEN-06 / SEC-16: design work shares a capped allowance inside the owning run."""

from types import SimpleNamespace

import pytest
from tilo_api.run_tools import RunBudget


def test_GEN_06_design_calls_reserve_writer_budget_and_never_exceed_run_cap():
    run = RunBudget(10)
    design = run.portion(0.3)
    seen = []

    def spend(*, budget):
        seen.append(budget)
        return SimpleNamespace(budget=budget - min(2, budget))

    design.call(spend)
    design.call(spend)
    assert seen == [3, 1]
    assert design.left == 0 and run.left == 7
    with pytest.raises(ValueError, match="budget"):
        design.call(spend)
    run.call(spend)
    assert run.left == 5


def test_GEN_06_invalid_provider_budget_cannot_increase_or_overdraw_cap():
    budget = RunBudget(4)
    for remaining in [-1, 5, float("nan")]:
        with pytest.raises(ValueError, match="budget"):
            budget.call(lambda *, budget: SimpleNamespace(budget=remaining))
        assert budget.left == 4
