"""FR-CON-10 / FR-INT-03 / BQ-218 (issue #283): a completed run delivers at least one artifact, in Tilo (`in_app`),
with no gate, no card and no outbox entry; sending and saving stay gated (PRD 10.3, 10.4). The plan's final `deliver`
unit does it. The production unit runner makes no artifact yet, so the run makes the delivered item itself and says so
in the stream (artifact.created, then artifact.delivered); a runner that does name one has it delivered as named.
"""

from __future__ import annotations

import copy
from typing import Any

from _api_contracts_lib import assert_valid_event
from _clint2_lib import UNIT_ARTIFACT, base_plan, wait_for
from tilo_harness.executor import UnitOutcome

DELIVER_TITLE = "Deliver the finished work"


def report_plan(approach_id: str, budget_cap: float) -> dict[str, Any]:
    """U1 -> U2 -> U3 (research and report, nothing sent or saved) -> U4, the deliver unit the compiler appends."""
    plan = base_plan(approach_id, budget_cap)
    plan["units"], plan["gates"] = plan["units"][:3], []
    last = copy.deepcopy(plan["units"][2])
    last.update(id="U4", unit_type="deliver", title=DELIVER_TITLE, skills=[], connectors=[], actions=[])
    last["depends_on"] = ["U3"]
    plan["units"].append(last)
    return plan


class _Runner:
    """Every unit names its artifact except `deliver`, which names none (what the production runner does)."""

    def __init__(self, inner: Any, *, deliver_names: dict | None = None) -> None:
        self.inner, self.deliver_names = inner, deliver_names
        self.release = inner.release  # RunFlow.close() sets it

    async def run(self, unit: Any, context: Any) -> Any:
        if unit["unit_type"] != "deliver":
            return await self.inner.run(unit, context)
        refs = (self.deliver_names,) if self.deliver_names else ()
        return UnitOutcome(success=True, summary=f"Finished {unit['title']}.", artifact_refs=refs)


def start(run_flow, *, deliver_names: dict | None = None) -> None:
    run_flow.compile_plan = lambda *, brief, approach, budget_cap, context=None: report_plan(approach["id"], budget_cap)
    run_flow.runner = _Runner(run_flow.runner, deliver_names=deliver_names)
    run_flow.start()
    assert run_flow.approve().status_code == 200


def test_FR_CON_10_a_report_run_delivers_in_app_and_asks_nobody(run_flow):
    start(run_flow)

    completed = wait_for(lambda: run_flow.events("world.completed"), what="world.completed")[0]

    assert completed["data"]["deliverable_count"] >= 1
    delivered = run_flow.events("artifact.delivered")
    assert len(delivered) == completed["data"]["deliverable_count"]
    for event in delivered:
        assert event["data"]["format"] == "in_app" and event["data"]["outbox_id"] is None
        assert_valid_event(event)
    types = run_flow.types()
    assert "approval.requested" not in types and "data.transfer" not in types, "delivering in Tilo is ungated"
    assert run_flow.cards().json() == []


def test_FR_CON_10_the_delivered_item_was_made_in_this_world_before_it_was_delivered(run_flow):
    start(run_flow)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    (delivered,) = run_flow.events("artifact.delivered")
    item = delivered["data"]["artifact"]
    made = [e for e in run_flow.events("artifact.created") if e["data"]["artifact"] == {**item}]
    assert len(made) == 1, "artifact.created names the item first (HR-1): nothing is delivered that was not made"
    assert made[0]["seq"] < delivered["seq"] and delivered["cause"] == made[0]["id"]
    assert item["artifact_id"] not in UNIT_ARTIFACT.values(), "the deliver unit's own item, not another unit's"
    assert item["version"] == 1


def test_FR_CON_10_the_delivery_endpoint_lists_the_item_with_the_deliver_unit_title(run_flow):
    start(run_flow)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    body = run_flow.delivery().json()

    assert len(body["artifacts"]) >= 1
    assert [(a["kind"], a["title"]) for a in body["artifacts"]] == [("in_app", DELIVER_TITLE)]


def test_FR_CON_10_a_deliver_unit_that_names_its_item_has_that_item_delivered(run_flow):
    named = {"artifact_id": "art_named_report", "version": 1}
    start(run_flow, deliver_names=named)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    delivered = [e["data"]["artifact"] for e in run_flow.events("artifact.delivered")]

    assert delivered == [named]


def test_FR_CON_10_a_send_stays_gated_and_the_in_app_delivery_waits_behind_it(run_flow):
    def gated_plan(*, brief, approach, budget_cap, context=None):
        plan = base_plan(approach["id"], budget_cap)  # U4 sends by email behind G1
        last = copy.deepcopy(plan["units"][3])
        last.update(id="U5", unit_type="deliver", title=DELIVER_TITLE, connectors=[], actions=[], depends_on=["U4"])
        plan["units"].append(last)
        return plan

    run_flow.compile_plan = gated_plan
    run_flow.runner = _Runner(run_flow.runner)
    requested, card = run_flow.run_to_gate()

    assert run_flow.events("artifact.delivered") == [], "nothing is delivered while the send waits (HR-1)"
    assert run_flow.answer(card["id"], "approve").status_code == 200
    completed = wait_for(lambda: run_flow.events("world.completed"), what="world.completed")[0]

    formats = [e["data"]["format"] for e in run_flow.events("artifact.delivered")]
    assert formats == ["email", "in_app"] and completed["data"]["deliverable_count"] == 2
    assert requested["type"] == "approval.requested" and len(run_flow.events("approval.requested")) == 1
