"""P0-RUN-DIES: a unit may continue a reply that still truncates after router recovery."""

from __future__ import annotations

import asyncio

import pytest
from tilo_harness.executor import UnitContext
from tilo_harness.failure import crash_reason
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_providers.errors import OutputTruncatedError
from tilo_providers.interfaces import GenerateResponse
from tilo_providers.router import RouterExhaustedError


class _FailFirstProvider:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        if len(self.calls) <= self.failures:
            try:
                raise OutputTruncatedError("reply hit its cap", output_tokens=100, thinking_tokens=900)
            except OutputTruncatedError as cause:
                raise RouterExhaustedError("reply stayed truncated") from cause
        return GenerateResponse(text="The complete result.", profile_id="fake")


def _run(provider: _FailFirstProvider):
    runner = ToolUnitRunner({"specialist": provider})
    unit = {"id": "U1", "role": "specialist", "title": "Research", "unit_type": "research"}
    context = UnitContext(agent_id="A1", skills=(), brief={"goal": "Find the answer."})
    return asyncio.run(runner.run(unit, context))


def test_P0_RUN_DIES_harness_continues_a_twice_truncated_unit_until_it_completes() -> None:
    provider = _FailFirstProvider(2)

    outcome = _run(provider)

    assert outcome.success is True
    assert len(provider.calls) == 3
    assert all("Continue from where you stopped" in call.prompt for call in provider.calls[1:])


def test_P0_RUN_DIES_harness_allows_at_most_three_continuations() -> None:
    provider = _FailFirstProvider(4)

    with pytest.raises(RouterExhaustedError) as raised:
        _run(provider)

    assert len(provider.calls) == 4, "the first attempt plus three continuation attempts"
    assert crash_reason(raised.value) == "a step's model reply was cut off before it finished"
