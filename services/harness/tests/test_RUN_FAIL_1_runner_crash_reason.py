"""RUN-FAIL-1: a runner that raises still fails only its unit, and now says why.

`UnitOutcome.reason` carries a plain, code-written line chosen by the error's class (never its text, which can quote a
prompt or a provider's message), and one ERROR line names the error classes and the Router's attempts.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_harness.failure import REASON_CAP, crash_reason, error_trail
from tilo_providers.errors import RequestError
from tilo_providers.router import (
    BudgetExceededError,
    RouterAttempt,
    RouterExhaustedError,
    RouterRequestError,
    TokenCapExceededError,
)

SECRET = "sk-live-" + "0" * 8  # assembled at runtime; it must never reach a reason or a log line


def _request_error() -> RouterRequestError:
    attempt = RouterAttempt(profile_id="lite-31", provider="google", outcome="error", error_type="RequestError")
    cause = RequestError(f"the SDK refused the request: {SECRET}")
    error = RouterRequestError(f"rejected the request: {SECRET}", [attempt])
    error.__cause__ = cause
    return error


class _Raising:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def run(self, unit: dict[str, Any], context: Any) -> UnitOutcome:
        await asyncio.sleep(0)
        if unit["id"] == "U1":
            raise self.error
        return UnitOutcome(success=True, summary="ok")


def test_RUN_FAIL_1_a_runner_crash_fails_its_unit_with_a_plain_reason_and_an_error_line(tmp_path: Path, caplog):
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0", "A_s1"], "unit_ids": ["U1", "U2"]}]
    )
    plan = build_plan([build_unit("U1"), build_unit("U2")])
    writer, _store = make_memory_writer(layout, world_id="w_crash")
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    caplog.set_level(logging.ERROR)

    result = asyncio.run(
        run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=_Raising(_request_error()))
    )

    assert result.failed == ["U1"] and result.outcomes["U2"].success is True
    assert result.outcomes["U1"].reason == "the model service refused a step's request"
    (line,) = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    # SILENT-FAILS (147820ff) appends the run and world ids to the error line.
    assert line == (
        "unit U1 failed: the model service refused a step's request "
        "[RouterRequestError <- RequestError; attempts: lite-31 RequestError] run=r_test_1 world=w_crash"
    )
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (BudgetExceededError("over"), "a step's model call did not fit the credits left in the run's budget"),
        (TokenCapExceededError("over"), "a step's input was over its model's input limit"),
        (RouterExhaustedError("none"), "no model could answer a step"),
        (ValueError(f"ambiguous {SECRET}"), "a step stopped on an internal error (ValueError)"),
    ],
)
def test_RUN_FAIL_1_each_error_class_has_its_own_plain_line(error: Exception, reason: str):
    assert crash_reason(error) == reason
    assert len(reason) <= REASON_CAP and SECRET not in reason
    assert SECRET not in error_trail(error)
