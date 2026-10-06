"""FR-AGT-02 / FR-HIL-03 (ADR-0018 T4; AR-07, OB-05, BQ-264): the item a gate sends is a stored version, so the policy
engine's `safety_flag` comes from that version's record: on unless the screener's verdict was `clean`, never a default.
The plan's gate is lowered to T2 here, so only the facts can make the send T3. All fakes: no model, no network."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest
from _clint2_lib import KNOWN_RECIPIENT, base_plan, wait_for


class _Screener:
    """SafetyProvider-shaped. `verdict` None: the screener errs, so the version is `unscreened`."""

    def __init__(self, verdict: bool | None) -> None:
        self.verdict = verdict

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> dict[str, Any]:
        if self.verdict is None:
            raise RuntimeError("no verdict")
        return {"flagged": self.verdict, "reason": None}


def _send(run_flow: Any, verdict: bool | None) -> tuple[dict[str, Any], dict[str, Any]]:
    from tilo_memory.artifacts import ArtifactStore  # noqa: PLC0415

    rig = run_flow.rig
    rig.store = ArtifactStore(  # the seam reads rig.store on each call
        rig.meta, rig.blobs, clock=lambda: datetime.now(UTC), redactor=rig.redactor,
        archive_lookup=lambda scope, archive_ref: None, alert_sink=rig.alerts.append, screener=_Screener(verdict),
    )  # fmt: skip

    def t2_gate(*, brief: dict, approach: dict, budget_cap: float, context: Any = None) -> dict:
        plan = base_plan(approach["id"], budget_cap)
        plan["gates"][0]["risk_tier"] = "T2"  # the risk table's send_email tier: the facts alone raise it
        run_flow.last_plan = plan
        return copy.deepcopy(plan)

    run_flow.compile_plan = t2_gate
    run_flow.recipients, run_flow.known_recipients = [KNOWN_RECIPIENT], [KNOWN_RECIPIENT]
    requested, card = run_flow.run_to_gate()
    assert run_flow.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    (entry,) = run_flow.outbox_store.all_entries()
    return requested, entry


@pytest.mark.parametrize("verdict", [None, True], ids=["unscreened", "flagged"])
def test_FR_AGT_02_a_send_of_a_version_not_screened_clean_is_T3_with_safety_flag(run_flow, verdict) -> None:
    requested, entry = _send(run_flow, verdict)
    assert requested["data"]["risk_tier"] == "T3", "a known recipient, but the item is not screened clean"
    assert "safety_flag" in entry["modifiers"] and entry["risk_tier"] == "T3"


def test_FR_AGT_02_a_send_of_a_version_screened_clean_has_no_safety_flag(run_flow) -> None:
    requested, entry = _send(run_flow, False)
    assert requested["data"]["risk_tier"] == "T2" and entry["modifiers"] == []
