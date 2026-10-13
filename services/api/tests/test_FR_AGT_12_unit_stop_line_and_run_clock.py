"""FR-AGT-12 / FR-INT-09, INTAKE-QUALITY-1 review fixes, through the API run.

1. A unit that fails with its own plain `reason` (the Verifier's date-window FAIL) stops the run as `world.failed`
   carrying that reason and that unit: the existing failure semantics, no new state, no `world.completed`.
2. `run_seams` hands the API's one clock (`deps.get_today`) to the plan compiler and the unit runner."""

from __future__ import annotations

from datetime import date
from typing import Any

from _clint2_lib import ScriptedRunner, base_plan, seam, wait_for
from tilo_api import deps

REASON = 'The work has dates outside today to the deadline: "March 2025"'
FIXED = date(2026, 10, 9)


class _DateFail(ScriptedRunner):
    """Fails the plan's first unit the way the default runner's date-window check does: `success=False` and a reason."""

    async def run(self, unit: Any, context: Any) -> Any:
        from tilo_harness.executor import UnitOutcome  # noqa: PLC0415

        if unit["id"] == base_plan()["units"][0]["id"]:
            self.ran.append(unit["id"])
            return UnitOutcome(success=False, summary="FAIL Schedule dates outside the window", reason=REASON)
        return await super().run(unit, context)


def test_FR_AGT_12_a_units_own_stop_line_reaches_world_failed(run_flow):
    run_flow.runner = _DateFail(run_flow.timeline)
    run_flow.start()
    assert run_flow.approve().status_code == 200

    (failed,) = wait_for(lambda: run_flow.events("world.failed"), what="world.failed")

    assert failed["data"] == {"reason": REASON, "unit": base_plan()["units"][0]["id"]}
    assert failed["summary"] == f"Stopped: {REASON}"
    assert run_flow.events("world.completed") == [] and run_flow.events("approval.requested") == []


def test_FR_AGT_12_run_seams_hand_one_clock_to_the_compiler_and_the_unit_runner(run_flow, monkeypatch):
    clock = lambda: FIXED  # noqa: E731
    overrides = run_flow.app.dependency_overrides
    scripted = {name: overrides.pop(seam(deps, name)) for name in ("get_plan_compiler", "get_unit_runner")}
    seen: dict[str, Any] = {}

    def compiler(mode: str = "replay", today: Any = None) -> Any:
        seen["compiler"] = today
        return scripted["get_plan_compiler"]()

    def runner(mode: str = "replay", today: Any = None) -> Any:
        seen["runner"] = today
        return scripted["get_unit_runner"]()

    monkeypatch.setattr(deps, "get_plan_compiler", compiler)
    monkeypatch.setattr(deps, "get_unit_runner", runner)
    overrides[deps.get_today] = lambda: clock

    run_flow.start()
    assert run_flow.approve().status_code == 200

    wait_for(lambda: run_flow.events("world.started"), what="world.started")
    assert seen == {"compiler": clock, "runner": clock}
