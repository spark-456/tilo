"""WEB-1 / WS-01, WS-14 (contracts/website.rules.md): a native website that the final writer unit made is stored as
text/html and delivered in Tilo as `artifact.delivered` {format website, outbox_id null, make_with native}, valid
against the registry. No gate, no card, no outbox entry."""

from __future__ import annotations

from typing import Any

from _api_contracts_lib import assert_valid_event
from _clint2_lib import wait_for
from test_FR_CON_10_in_app_delivery_run import report_plan
from tilo_harness.executor import UnitOutcome
from tilo_harness.outputs import WebsiteHtml

PAGE = b"<!doctype html><html><body><h1>Clocks</h1><script>setInterval(function(){}, 1000)</script></body></html>"


class _Runner:
    def __init__(self, inner: Any) -> None:
        self.inner, self.release = inner, inner.release

    async def run(self, unit: Any, context: Any) -> Any:
        if unit["unit_type"] == "deliver":
            made = (WebsiteHtml(media_type="text/html", content=PAGE),)
            return UnitOutcome(success=True, summary=f"Finished {unit['title']}.", outputs=made)
        return await self.inner.run(unit, context)


def website_plan(approach_id: str, budget_cap: float) -> dict[str, Any]:
    plan = report_plan(approach_id, budget_cap)
    plan["units"][3]["role"] = "writer"
    return plan


def test_WEB_1_WS_14_a_native_website_is_delivered_with_format_website_and_make_with_native(
    run_flow, repo_root, registry
) -> None:
    run_flow.compile_plan = lambda *, brief, approach, budget_cap, context=None: website_plan(
        approach["id"], budget_cap
    )
    run_flow.runner = _Runner(run_flow.runner)
    run_flow.start()
    assert run_flow.approve().status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    made = [e for e in run_flow.events("artifact.created") if e["data"].get("media_type") == "text/html"]
    assert len(made) == 1
    ref = made[0]["data"]["artifact"]
    delivered = [e for e in run_flow.events("artifact.delivered") if e["data"]["artifact"] == ref]
    assert len(delivered) == 1
    assert delivered[0]["data"] == {"artifact": ref, "format": "website", "outbox_id": None, "make_with": "native"}
    assert_valid_event(repo_root, registry, delivered[0])
    assert made[0]["seq"] < delivered[0]["seq"] and delivered[0]["cause"] == made[0]["id"]
    assert "approval.requested" not in run_flow.types() and "data.transfer" not in run_flow.types()
    others = [e["data"]["format"] for e in run_flow.events("artifact.delivered") if e["data"]["artifact"] != ref]
    assert set(others) <= {"in_app"}
