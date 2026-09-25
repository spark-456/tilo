"""PL-03 (PRD 6.4): "Router picks by role, capability and budget." Test
scope: "a request over the role's remaining budget is refused before any
call". Public interface: `tilo_providers.router.Router.generate(...,
budget=...)`.

Ambiguity (docs/open-questions.md BQ-61): the PRD does not give an exact
cost-estimate formula for "remaining budget" -- only PL-06 (`config.price`)
and PRD 14.1 (`config.credits`) exist to build one from. These tests do not
assume a specific formula: they only exercise the two directions PL-03 must
get right in every formula -- a budget that cannot possibly cover even one
call is refused before any call, and a budget that is obviously ample lets
the call proceed -- via a property test (Hypothesis) over a wide range of
budget values on each side, so "budget never exceeded" holds regardless of
the implementer's exact estimate arithmetic.
"""

from __future__ import annotations

import pytest
from conftest import ScriptedCall, ScriptedModelProvider, build_providers_config, models_config, prices_config
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_providers.interfaces import GenerateRequest

_CONFIG = build_providers_config(models_config(), prices_config(set_=True))


def _router(config, providers: dict[str, ScriptedModelProvider]):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


def test_PL_03_over_budget_request_is_refused_before_any_call(providers_config):
    from tilo_providers.router import BudgetExceededError  # noqa: PLC0415

    primary = ScriptedModelProvider("large", [ScriptedCall(text="must never be reached")])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="must never be reached")])
    router = _router(providers_config, {"large": primary, "medium": fallback})

    with pytest.raises(BudgetExceededError):
        router.generate("director", GenerateRequest(prompt="Summarise the quarter."), budget=0)

    assert primary.calls == [], "budget must be checked before the primary is ever called"
    assert fallback.calls == []


def test_PL_03_within_budget_request_proceeds_normally(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(text="ok")])
    router = _router(providers_config, {"large": primary, "medium": primary})

    result = router.generate("director", GenerateRequest(prompt="Summarise the quarter."), budget=1_000_000)

    assert result.outcome == "ok"
    assert len(primary.calls) == 1


@given(budget=st.floats(min_value=-1_000, max_value=0, allow_nan=False))
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_PL_03_budget_never_exceeded_property_nonpositive_budget_always_refused(budget):
    """Property (PL-03, "budget never exceeded"): whatever a non-positive
    budget is, the router must refuse before making any call -- no call
    ever costs zero or negative credits, so no non-positive budget can ever
    cover one."""
    from tilo_providers.router import BudgetExceededError  # noqa: PLC0415

    provider = ScriptedModelProvider("large", [ScriptedCall(text="must never be reached")])
    router = _router(_CONFIG, {"large": provider, "medium": provider})

    with pytest.raises(BudgetExceededError):
        router.generate("director", GenerateRequest(prompt="hello"), budget=budget)

    assert provider.calls == []


@given(budget=st.floats(min_value=1e9, max_value=1e12, allow_nan=False))
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_PL_03_budget_never_exceeded_property_ample_budget_always_proceeds(budget):
    """Property (PL-03): whatever an obviously ample budget is (many orders
    of magnitude above any plausible per-call cost), the router must let a
    single short call through -- the budget check must not be so strict
    that it refuses calls it can plainly afford."""
    provider = ScriptedModelProvider("large", [ScriptedCall(text="ok")])
    router = _router(_CONFIG, {"large": provider, "medium": provider})

    result = router.generate("director", GenerateRequest(prompt="hello"), budget=budget)

    assert result.outcome == "ok"
    assert len(provider.calls) == 1
