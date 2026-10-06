"""FR-AGT-14 (PRD 8.6, 10.4, 9.5; contracts 1.4.0 `schedule` channel; OB-01): what a scheduled run writes, and what
it may not be.

- A scheduled run's first event is a `world.requested` with actor = the schedule's OWNER user id (never `system`:
  OB-01 makes
  the actor of a world's first world.requested its owner, and only a person can be one), channel `schedule`, destination
  null, title = the schedule's title. It validates through the real WorldWriter (EventValidator, EV-01..EV-15).
- The skipped-slot alert is a valid `alert.raised`.
- `schedule` is never an owner instruction for an L2 policy (`tilo_policy.decide` gates; `instruction_counts` is
  False) and
  never a person's approval (`open_gate` stays shut), so a scheduled run still waits for a person at every T3 step.
Interface: API_FR_AGT_14.md.
"""

from __future__ import annotations

import json
import re

import pytest
import tilo_policy
from conftest import CONTRACTS_DIR, make_memory_writer
from schedule_support import MON_0330Z, OWNER
from tilo_harness.schedule import RunStart, skipped_alert_kwargs, slot_key, world_requested_kwargs
from tilo_policy import coverage

LAYOUT = json.loads((CONTRACTS_DIR / "fixtures/layout/valid/village_basic.json").read_text(encoding="utf-8"))
SCHEDULED_FIXTURE = CONTRACTS_DIR / "fixtures/events/valid/world.requested--scheduled.json"
WORLD = "w_village_basic"


def _run(**overrides) -> RunStart:
    fields = {
        "idempotency_key": slot_key("sched_a", MON_0330Z),
        "schedule_id": "sched_a",
        "owner_user_id": OWNER,
        "title": "Weekly supplier report",
        "approved_brief_ref": "w_approved_1",
        "prior_world_id": None,
        "budget_cap": 40.0,
        "slot": MON_0330Z,
        "skipped": 0,
        "cache_namespace": "sched_a",
    }
    return RunStart(**(fields | overrides))


def _writer():
    return make_memory_writer(LAYOUT, world_id=WORLD, run_id="r_village_basic_9")


def test_FR_AGT_14_the_scheduled_world_requested_is_owned_by_the_schedules_owner_on_the_schedule_channel():
    kwargs = world_requested_kwargs(_run(), WORLD)
    assert kwargs["type"] == "world.requested"
    assert kwargs["actor"] == OWNER  # not "system"
    assert kwargs["target"] == WORLD
    assert kwargs["data"] == {"title": "Weekly supplier report", "channel": "schedule", "destination": None}


def test_FR_AGT_14_the_actor_is_whoever_owns_the_schedule_never_the_literal_system():
    for owner in ("u_owner", "u_riya_2"):
        assert world_requested_kwargs(_run(owner_user_id=owner), WORLD)["actor"] == owner
    assert world_requested_kwargs(_run(), WORLD)["actor"] != "system"


def test_FR_AGT_14_the_scheduled_world_requested_passes_the_real_writer_and_validator():
    writer, store = _writer()
    event = writer.emit(**world_requested_kwargs(_run(), WORLD))
    assert (event["type"], event["actor"], event["seq"]) == ("world.requested", OWNER, 1)
    assert event["data"] == {"title": "Weekly supplier report", "channel": "schedule", "destination": None}
    assert [e["type"] for e in store.read_events("org_demo", WORLD)] == ["world.requested"]


def test_FR_AGT_14_the_built_event_has_the_shape_of_the_contracts_scheduled_fixture():
    fixture = json.loads(SCHEDULED_FIXTURE.read_text(encoding="utf-8"))
    built = world_requested_kwargs(
        _run(title=fixture["data"]["title"], owner_user_id=fixture["actor"]), fixture["world_id"]
    )
    assert (built["type"], built["actor"], built["target"], built["data"]) == (
        fixture["type"],
        fixture["actor"],
        fixture["target"],
        fixture["data"],
    )
    writer, _store = make_memory_writer(LAYOUT, world_id=fixture["world_id"], run_id=fixture["run_id"])
    assert writer.append(fixture)["id"] == fixture["id"]  # the contract's own fixture is a valid first event


def test_FR_AGT_14_the_skipped_slot_alert_is_a_valid_info_alert_that_says_how_many():
    writer, _store = _writer()
    writer.emit(**world_requested_kwargs(_run(skipped=3), WORLD))
    alert_id = "01JB5VQ0000000000000009401"
    kwargs = skipped_alert_kwargs(WORLD, 3, alert_id)
    event = writer.emit(**kwargs)
    assert (event["type"], event["severity"], event["target"]) == ("alert.raised", "info", WORLD)
    assert event["data"] == {"alert_id": alert_id, "card_id": None}
    assert re.search(r"\b3\b", event["summary"])


def test_FR_AGT_14_the_skipped_slot_alert_never_asks_a_person_for_anything():
    kwargs = skipped_alert_kwargs(WORLD, 1, "01JB5VQ0000000000000009402")
    assert kwargs["data"]["card_id"] is None
    assert kwargs["severity"] == "info"  # the lowest rung: it informs, it does not interrupt


# ---------------------------------------------------------------------------
# `schedule` is never an instruction and never an approval

DECIDED_AT = "2026-09-29T09:42:16.000Z"
INSTRUCTED_AT = "2026-09-29T09:41:50.000Z"
POLICY_CREATED = "2026-09-29T09:30:00.000Z"
DESTINATION = "thread-supplier-1"


def _l2_policy() -> dict:
    return {
        "id": "pol_autopilot_l2",
        "owner": OWNER,
        "action_type": "send_email",
        "scope": {"connectors": ["gmail"], "recipients": [], "domains": ["example.com"], "districts": []},
        "limits": {"per_day": 20, "credits": 50},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": "L2",
        "undo_window_s": 60,
        "expiry": None,
        "notify_channel": "email",
        "team_lead_domains": [],
        "created_by": {"by": OWNER, "at": POLICY_CREATED},
        "changed_by": None,
        "history": [{"by": OWNER, "at": POLICY_CREATED, "change": "Created", "level": "L2"}],
    }


def _instruction(channel: str, actor: str = OWNER) -> dict:
    """The owner's world.requested about this destination, shaped as `instruction_counts` reads it. Only `channel` and
    (in one test) `actor` change; for the schedule case the data comes from the builder under test."""
    data = (
        {**world_requested_kwargs(_run(), "w_village_basic")["data"], "destination": DESTINATION}
        if channel == "schedule"
        else {"title": "Reply to the supplier", "channel": channel, "destination": DESTINATION}
    )
    return {
        "id": "01JB5VQ0000000000000000131",
        "type": "world.requested",
        "actor": actor,
        "ts": INSTRUCTED_AT,
        "world_id": WORLD,
        "data": data,
    }


def test_FR_AGT_14_instruction_counts_accepts_the_web_instruction_and_refuses_the_schedule_one():
    policy = _l2_policy()
    web = coverage.instruction_counts(_instruction("web"), WORLD, policy, DESTINATION, DECIDED_AT, [])
    assert web is True  # the control: everything else about the setup is a valid L2 instruction
    for actor in (OWNER, "system"):
        scheduled = coverage.instruction_counts(
            _instruction("schedule", actor), WORLD, policy, DESTINATION, DECIDED_AT, []
        )
        assert scheduled is False


@pytest.fixture
def l2_action_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coverage, "L2_ACTION_RECORDED", True)  # stands in for ADR-0013, as in packages/policy tests


def _proposal(instruction: dict) -> tilo_policy.Proposal:
    facts = tilo_policy.SideEffectFacts(
        recipients=("riya@example.com",),
        known_recipients=("riya@example.com",),
        attachments=(),
        external_share=False,
        deletion=False,
        money_or_legal=False,
        safety_flags=False,
    )
    return tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination=DESTINATION,
        facts=facts,
        item={"artifact_id": "art_followup_reply", "version": 1},
        credits=1,
        instruction=instruction,
    )


@pytest.mark.usefixtures("l2_action_recorded")
def test_FR_AGT_14_decide_gates_a_send_whose_only_instruction_is_a_schedule_request():
    table = tilo_policy.load_risk_table(CONTRACTS_DIR / "fixtures/policy.risk_tier_table/valid/prd_10_4_tiers.json")

    def decide(channel: str):
        return tilo_policy.decide(
            _proposal(_instruction(channel)),
            table=table,
            policies=[_l2_policy()],
            world_owner=OWNER,
            applied=[],
            now=DECIDED_AT,
        )

    assert decide("web").outcome == "run_after_undo"  # control: a signed-in instruction opens the L2 send
    scheduled = decide("schedule")
    assert scheduled.outcome == "gate"  # a schedule is not the owner telling Tilo to send this
    assert scheduled.authz is None


GATE = {"gate_id": "G1", "card_id": "01JB5VQ0000000000000009001", "outbox_id": "01JB5VQ0000000000000009002"}


@pytest.mark.parametrize("risk_tier", ["T1", "T2", "T3"])
@pytest.mark.parametrize("by_ref", [OWNER, "u_approver"])
def test_FR_AGT_14_an_answer_on_the_schedule_channel_opens_no_gate_at_any_tier(risk_tier, by_ref):
    reserved = {
        "type": "approval.requested",
        "authz": None,
        "data": {
            **GATE,
            "action_type": "send_email",
            "risk_tier": risk_tier,
            "irreversible": True,
            "item": {"artifact_id": "art_reply_draft", "version": 1},
            "approver": {"user": "u_approver", "assigned_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"}},
            "team_lead": None,
        },
    }
    resolved = {
        "type": "approval.resolved",
        "authz": {"by": "person", "ref": by_ref, "at": "2026-09-29T09:32:09.500Z"},
        "data": {**GATE, "option": "approve", "channel": "schedule", "pin_verified": True},
    }
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER)
    assert decision.outcome == "gate"
    assert decision.authz is None
