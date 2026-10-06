"""CL-INT-2 review round 1 (#151): an owner's L0 policy keeps the draft in Tilo (PRD 10.4); a send step killed by a
BaseException, a send with nobody to send to, a send the run gives up on, and a gate card the schema refuses all end
closed; run events are scoped to their district (PRD 10.1). Defaults: BQ-90.
"""

from __future__ import annotations

import pytest
from _clint2_lib import (
    DESTINATION,
    FLOW_USER,
    KNOWN_RECIPIENT,
    MOCK_ID,
    assert_stream_valid,
    build_run_flow,
    schema_errors,
    wait_for,
)
from tilo_connectors.mock import MockConnector


def _l0_send_policy() -> dict:
    stamp = {"by": FLOW_USER, "at": "2026-09-29T09:30:00.000Z"}
    return {
        "id": "pol_observe_mock",
        "owner": FLOW_USER,
        "action_type": "send_email",
        "scope": {"connectors": [MOCK_ID], "recipients": [], "domains": [], "districts": []},
        "limits": {"per_day": None, "credits": None},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": "L0",
        "undo_window_s": 0,
        "expiry": None,
        "notify_channel": "web",
        "team_lead_domains": [],
        "created_by": stamp,
        "changed_by": None,
        "history": [{**stamp, "change": "Observe only", "level": "L0"}],
    }


def _nothing_left_tilo(rf) -> None:
    assert rf.outbox_store.all_entries() == []
    assert rf.adapter.sent == []
    assert rf.events("data.transfer") == []


def test_FR_HIL_04_an_owner_L0_policy_keeps_the_draft_in_tilo_and_nothing_is_sent(run_flow, registry):
    policy = _l0_send_policy()
    assert schema_errors("policy", policy) == []
    run_flow.store.policies[policy["id"]] = policy
    run_flow.recipients, run_flow.known_recipients = [KNOWN_RECIPIENT], [KNOWN_RECIPIENT]  # T2: L0 covers it
    run_flow.start()
    assert run_flow.approve().status_code == 200

    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    run_flow.quiet_stream()

    _nothing_left_tilo(run_flow)
    assert run_flow.events("approval.requested") == [] and run_flow.cards().json() == []  # no approve to press
    (delivered,) = run_flow.events("artifact.delivered")
    assert delivered["data"]["format"] == "in_app" and delivered["data"]["outbox_id"] is None
    assert [a["kind"] for a in run_flow.delivery().json()["artifacts"]] == ["in_app"]
    assert_stream_valid(run_flow, registry)


class _KilledMock(MockConnector):
    def send_reply(self, *args, **kwargs):
        raise SystemExit("killed mid-send")


def test_FR_AGT_11_a_send_step_killed_by_a_BaseException_ends_in_world_failed(repo_root):
    rf = build_run_flow(repo_root, adapter_factory=_KilledMock, covered=True)
    try:
        _, card = rf.run_to_gate()
        assert rf.answer(card["id"], "approve").status_code == 200

        wait_for(lambda: rf.events("world.failed"), what="world.failed after the killed send")
        rf.quiet_stream()
        assert rf.events("world.completed") == [] and rf.events("data.transfer") == []
        (entry,) = rf.outbox_store.all_entries()
        assert entry["state"] == "failed"  # never left 'sending' in a failed world
        assert rf.delivery().status_code == 409
    finally:
        rf.close()


@pytest.mark.parametrize(
    "resolved",
    [
        {"destination": DESTINATION, "recipients": []},
        {"destination": None, "recipients": [KNOWN_RECIPIENT]},
        {"destination": "", "recipients": [KNOWN_RECIPIENT]},
    ],
    ids=["no_recipients", "destination_none", "destination_empty"],
)
def test_FR_HIL_03_a_send_with_nobody_or_nowhere_to_send_to_fails_closed_before_the_gate(run_flow, resolved):
    run_flow.resolve_action = lambda **_: dict(resolved)
    run_flow.start()
    assert run_flow.approve().status_code == 200

    wait_for(lambda: run_flow.events("world.failed"), what="world.failed")
    run_flow.quiet_stream()

    assert run_flow.events("approval.requested") == [] and run_flow.cards().json() == []
    _nothing_left_tilo(run_flow)


def test_FR_HIL_03_a_gate_card_the_schema_refuses_writes_no_approval_requested(run_flow):
    run_flow.recipients = [f"person{n}@example.com" for n in range(51)]  # a card holds at most 50
    run_flow.start()
    assert run_flow.approve().status_code == 200

    wait_for(lambda: run_flow.events("world.failed"), what="world.failed")
    run_flow.quiet_stream()

    assert run_flow.events("approval.requested") == [] and run_flow.cards().json() == []
    _nothing_left_tilo(run_flow)


class _DownMock(MockConnector):
    def send_reply(self, *args, **kwargs):
        raise ConnectionError("the provider is down")


def test_FR_AGT_11_a_send_the_run_gives_up_on_is_failed_in_the_outbox(repo_root):
    rf = build_run_flow(repo_root, adapter_factory=_DownMock, covered=True)
    try:
        _, card = rf.run_to_gate()
        assert rf.answer(card["id"], "approve").status_code == 200

        wait_for(lambda: rf.events("world.failed"), timeout=15.0, what="world.failed after the retries")
        (entry,) = rf.outbox_store.all_entries()
        assert entry["state"] == "failed"  # no later dispatcher sends it
        assert rf.events("data.transfer") == []
    finally:
        rf.close()


def test_PRD_10_1_run_events_in_a_district_are_scoped_to_that_district(run_flow):
    run_flow.run_to_completion()
    stream = run_flow.quiet_stream()

    granted = next(i for i, e in enumerate(stream) if e["type"] == "budget.granted")
    run_events = stream[granted + 1 :]
    assert [e for e in run_events if e["district"]]  # the gate and the delivery happen in a district
    for event in run_events:
        assert event["vis"] == ([event["district"]] if event["district"] else "all"), (event["type"], event["vis"])
