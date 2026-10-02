"""CL-INT-2 safety follow-ups (#155, from the #151 reviews): a unit never makes or sends another world's item; the
gate card says what the send is from the action, connector, destination and recipients, not from a model-written
title; a send is not claimed once the world is paused, even when the pause lands after the run's last look; a failed
event write on a card answer is a 503 with a stable error, and the card stays open; the run's clock is a plain class.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from _clint2_lib import DESTINATION, NEW_RECIPIENT, ScriptedRunner, wait_for


def _created(artifact_id: str) -> dict[str, Any]:
    return {"type": "artifact.created", "data": {"artifact": {"artifact_id": artifact_id, "version": 1}}}


class _ForeignRunner(ScriptedRunner):
    """Every unit says its artifact is one that another world already holds."""

    async def run(self, unit: Any, context: Any) -> Any:
        from tilo_harness.executor import UnitOutcome  # noqa: PLC0415

        self.ran.append(unit["id"])
        return UnitOutcome(
            success=True, summary="done", artifact_refs=({"artifact_id": "art_OTHER_TENANT", "version": 1},)
        )


def test_FR_HIL_03_a_unit_naming_another_worlds_item_fails_the_world_and_sends_nothing(run_flow):
    run_flow.store.events["w_other"] = [_created("art_OTHER_TENANT")]
    run_flow.runner = _ForeignRunner(run_flow.timeline)
    run_flow.start()
    assert run_flow.approve().status_code == 200

    wait_for(lambda: run_flow.events("world.failed"), what="world.failed")
    run_flow.quiet_stream()

    assert run_flow.events("artifact.created") == []  # not even recorded in this world
    assert run_flow.events("approval.requested") == [] and run_flow.cards().json() == []
    assert run_flow.outbox_store.all_entries() == [] and run_flow.adapter.sent == []
    assert run_flow.events("data.transfer") == [] and run_flow.events("world.completed") == []


def test_FR_HIL_03_the_gate_card_says_what_the_send_is_not_what_the_unit_title_says(run_flow):
    _, card = run_flow.run_to_gate()

    exact = card["gate"]["action"]["exact"]
    assert NEW_RECIPIENT in exact and DESTINATION in exact and "send_email" in exact
    assert "Mock Mail" in exact  # the connector's own name
    titles = [u["title"] for u in run_flow.last_plan["units"]]
    assert not any(title in exact for title in titles)  # nothing a model wrote


def test_FR_HIL_03_a_send_with_too_many_recipients_for_the_card_text_fails_closed_not_cut(run_flow):
    run_flow.recipients = [f"a-rather-long-recipient-address-{n:02d}@example.com" for n in range(14)]  # fits the schema
    run_flow.start()
    assert run_flow.approve().status_code == 200

    wait_for(lambda: run_flow.events("world.failed"), what="world.failed")
    run_flow.quiet_stream()

    assert run_flow.events("approval.requested") == [] and run_flow.cards().json() == []
    assert run_flow.outbox_store.all_entries() == []


def test_FR_WLD_07_a_pause_landing_at_the_claim_stops_the_send_before_it_reaches_the_adapter(run_flow, monkeypatch):
    from tilo_api.runs import Run  # noqa: PLC0415

    real = Run.paused

    def paused(self: Run) -> bool:  # the world is paused at the instant the outbox claims, not before
        return True if sys._getframe(1).f_code.co_name == "_dispatch_one" else real(self)

    monkeypatch.setattr(Run, "paused", paused)
    _, card = run_flow.run_to_gate()
    assert run_flow.answer(card["id"], "approve").status_code == 200

    wait_for(lambda: run_flow.events("world.failed"), timeout=15.0, what="world.failed once the send is given up")

    assert run_flow.adapter.sent == [] and run_flow.events("data.transfer") == []
    (entry,) = run_flow.outbox_store.all_entries()
    assert entry["state"] == "failed"  # abandoned, never claimed


def test_FR_HIL_01_a_failed_event_write_on_an_answer_is_a_503_and_the_card_stays_open(run_flow, monkeypatch):
    _, card = run_flow.run_to_gate()
    real = run_flow.writer.append

    def failing(world_id: str, event: dict) -> dict:
        if event["type"] == "approval.resolved":
            raise OSError("the event store is down")
        return real(world_id, event)

    monkeypatch.setattr(run_flow.writer, "append", failing)
    down = run_flow.answer(card["id"], "approve")
    assert down.status_code == 503
    assert down.json() == {"outcome": "error", "reason": "event_write_failed"}
    assert run_flow.events("approval.resolved") == []

    monkeypatch.setattr(run_flow.writer, "append", real)
    assert run_flow.answer(card["id"], "approve").status_code == 200  # still open: the answer goes through
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    assert len(run_flow.events("approval.resolved")) == 1


def test_FR_HIL_03_the_runs_clock_is_a_plain_class_with_now():
    from tilo_api import runs  # noqa: PLC0415

    assert not isinstance(runs._CLOCK, SimpleNamespace)
    assert runs._CLOCK.now().endswith("Z")
