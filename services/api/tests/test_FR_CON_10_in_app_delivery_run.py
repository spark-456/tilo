"""FR-CON-10 / FR-INT-03 / BQ-218 (issue #283): the plan's final `deliver` unit delivers, in Tilo (`in_app`), the items
its upstream units really produced: no gate, no card, no outbox entry, nothing outbound (PRD 10.3, 10.4). Nothing is
made up (HR-1): a run whose units produced no item completes honestly with 0 deliverables. Sending and saving stay
gated."""

from __future__ import annotations

import copy
from typing import Any

from _api_contracts_lib import assert_valid_event
from _clint2_lib import UNIT_ARTIFACT, base_plan, wait_for
from tilo_harness.executor import UnitOutcome, UnitOutput

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
    """The scripted runner for the work units; the deliver unit names no item itself (what the compiler's unit does).
    `produce=False`: no unit names an item. `outputs=True`: work units return Markdown, as `DefaultUnitRunner` does."""

    def __init__(self, inner: Any, *, produce: bool = True, deliver_names: dict | None = None, outputs=False) -> None:
        self.inner, self.produce, self.deliver_names, self.outputs = inner, produce, deliver_names, outputs
        self.release = inner.release  # RunFlow.close() sets it

    async def run(self, unit: Any, context: Any) -> Any:
        if unit["unit_type"] == "deliver" or not self.produce:
            refs = (self.deliver_names,) if self.deliver_names and unit["unit_type"] == "deliver" else ()
            made = (UnitOutput("text/markdown", b"# Notes"),) if self.outputs and unit["unit_type"] != "deliver" else ()
            return UnitOutcome(success=True, summary=f"Finished {unit['title']}.", artifact_refs=refs, outputs=made)
        return await self.inner.run(unit, context)


def start(run_flow, *, plan=report_plan, **runner_options) -> None:
    run_flow.compile_plan = lambda *, brief, approach, budget_cap, context=None: plan(approach["id"], budget_cap)
    run_flow.runner = _Runner(run_flow.runner, **runner_options)
    run_flow.start()
    assert run_flow.approve().status_code == 200


def test_FR_CON_10_a_report_run_delivers_what_its_last_unit_made_in_app_and_asks_nobody(run_flow, repo_root, registry):
    start(run_flow)

    completed = wait_for(lambda: run_flow.events("world.completed"), what="world.completed")[0]

    delivered = run_flow.events("artifact.delivered")
    assert completed["data"]["deliverable_count"] == len(delivered) == 1
    (event,) = delivered
    assert event["data"] == {
        "artifact": {"artifact_id": UNIT_ARTIFACT["U3"], "version": 1}, "format": "in_app", "outbox_id": None,
    }  # fmt: skip
    assert_valid_event(repo_root, registry, event)
    types = run_flow.types()
    assert "approval.requested" not in types and "data.transfer" not in types, "delivering in Tilo is ungated"
    assert run_flow.cards().json() == []


def test_FR_CON_10_the_delivery_follows_the_item_made_by_a_real_unit(run_flow):
    start(run_flow)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    (delivered,) = run_flow.events("artifact.delivered")
    (made,) = [e for e in run_flow.events("artifact.created") if e["target"] == UNIT_ARTIFACT["U3"]]
    assert made["seq"] < delivered["seq"] and delivered["cause"] == made["id"], "delivered after it was made (HR-1)"
    assert not [e for e in run_flow.events("artifact.created") if e["target"] not in UNIT_ARTIFACT.values()]


def test_FR_CON_10_the_delivery_endpoint_lists_the_item_under_the_unit_that_made_it(run_flow):
    start(run_flow)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    body = run_flow.delivery().json()

    title = next(u["title"] for u in report_plan("quick", 1)["units"] if u["id"] == "U3")
    assert [(a["id"], a["kind"], a["title"]) for a in body["artifacts"]] == [(UNIT_ARTIFACT["U3"], "in_app", title)]


def test_FR_CON_10_every_leaf_unit_has_its_item_delivered_once(run_flow):
    def branching(approach_id: str, budget_cap: float) -> dict[str, Any]:
        plan = report_plan(approach_id, budget_cap)
        plan["units"][2]["depends_on"] = ["U1"]  # U2 and U3 are both leaves of U1
        plan["units"][3]["depends_on"] = ["U2", "U3"]
        return plan

    start(run_flow, plan=branching)
    completed = wait_for(lambda: run_flow.events("world.completed"), what="world.completed")[0]

    delivered = [e["data"]["artifact"]["artifact_id"] for e in run_flow.events("artifact.delivered")]
    assert sorted(delivered) == sorted([UNIT_ARTIFACT["U2"], UNIT_ARTIFACT["U3"]])
    assert completed["data"]["deliverable_count"] == 2


def test_FR_CON_10_a_run_whose_units_produced_nothing_delivers_nothing_and_makes_nothing_up(run_flow):
    start(run_flow, produce=False)

    completed = wait_for(lambda: run_flow.events("world.completed"), what="world.completed")[0]

    assert completed["data"]["deliverable_count"] == 0
    assert run_flow.events("artifact.delivered") == [] and run_flow.events("artifact.created") == []
    assert run_flow.delivery().json()["artifacts"] == [], "S-12 says plainly that nothing was produced"


def test_FR_AGT_02_until_T4_an_api_run_drops_unit_outputs_as_before_and_completes(run_flow):
    """Stopgap until ADR-0018 T4: tilo-api passes run_plan no artifact store, so a unit's text (what DefaultUnitRunner
    returns since T3) is dropped as before T3 instead of failing the unit; nothing is made up."""
    start(run_flow, produce=False, outputs=True)
    completed = wait_for(lambda: run_flow.events("world.completed"), what="world.completed")[0]
    assert completed["data"]["deliverable_count"] == 0 and run_flow.events("artifact.created") == []


def test_FR_CON_10_a_deliver_unit_that_names_its_own_item_has_it_delivered_too(run_flow):
    named = {"artifact_id": "art_named_report", "version": 1}
    start(run_flow, deliver_names=named)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    delivered = [e["data"]["artifact"]["artifact_id"] for e in run_flow.events("artifact.delivered")]

    assert sorted(delivered) == sorted([named["artifact_id"], UNIT_ARTIFACT["U3"]])


def test_FR_CON_10_a_send_stays_gated_and_is_the_only_delivery_of_its_plan(run_flow):
    requested, card = run_flow.run_to_gate()  # the shipped plan: U4 sends by email behind G1

    assert run_flow.events("artifact.delivered") == [], "nothing is delivered while the send waits (HR-1)"
    assert run_flow.answer(card["id"], "approve").status_code == 200
    completed = wait_for(lambda: run_flow.events("world.completed"), what="world.completed")[0]

    formats = [e["data"]["format"] for e in run_flow.events("artifact.delivered")]
    assert formats == ["email"] and completed["data"]["deliverable_count"] == 1
    assert requested["type"] == "approval.requested" and len(run_flow.events("approval.requested")) == 1
