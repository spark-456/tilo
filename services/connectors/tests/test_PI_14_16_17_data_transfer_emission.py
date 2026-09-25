"""PI-14 / PI-16 / PI-17 (docs/security/p4-policy-invariants.md, PRD 10.4 HR-7): a sent entry
is exactly what was authorised and stays that way except for `state` (PI-14/OB-05); it emits
exactly one `data.transfer` part, direction "out", naming the entry and carrying its `authz`
unchanged (PI-16), which validates against
contracts/events/data/data.transfer.schema.json (PI-17); a cancelled or failed entry emits
nothing.
"""

from __future__ import annotations

import tilo_connectors
from conftest import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail


def make_outbox(emitted: list[dict], gmail, clock: ManualClock | None = None):
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(
        store, {"gmail": gmail}, emitted.append, clock or ManualClock("2026-09-29T09:00:00.000Z")
    )
    return outbox


def test_PI_14_no_field_but_state_changes_after_dispatch(gate_case_factory):
    case = gate_case_factory(undo_window_s=0)
    entry = case["entry"]
    outbox = make_outbox([], FakeGmail())
    before = outbox.enqueue(entry, evidence_from_case(case))

    sent = outbox.dispatch_due()

    assert len(sent) == 1
    after = sent[0]
    assert after["state"] == "sent"
    before_minus_state = {k: v for k, v in before.items() if k != "state"}
    after_minus_state = {k: v for k, v in after.items() if k != "state"}
    assert before_minus_state == after_minus_state


def test_PI_16_17_sent_entry_emits_exactly_one_data_transfer_out(gate_case_factory):
    case = gate_case_factory(
        undo_window_s=0,
        connector="gmail",
        action_type="send_email",
        item={"artifact_id": "art_reply_draft", "version": 3},
        risk_tier="T2",
    )
    entry = case["entry"]
    emitted: list[dict] = []
    outbox = make_outbox(emitted, FakeGmail())
    outbox.enqueue(entry, evidence_from_case(case))

    outbox.dispatch_due()

    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1
    part = transfers[0]
    assert set(part) == {"type", "authz", "data"}
    assert part["authz"] == entry["authz"], "PI-16: the entry's authz, unchanged"
    data = part["data"]
    assert data["outbox_id"] == entry["id"]
    assert data["connector"] == entry["connector"]
    assert data["action_type"] == entry["action_type"]
    assert data["direction"] == "out"
    assert data["artifact"] == entry["item"]
    assert data["risk_tier"] == entry["risk_tier"]


def test_PI_17_emitted_data_validates_against_data_transfer_schema(gate_case_factory, data_transfer_schema_errors):
    case = gate_case_factory(undo_window_s=0)
    emitted: list[dict] = []
    outbox = make_outbox(emitted, FakeGmail())
    outbox.enqueue(case["entry"], evidence_from_case(case))

    outbox.dispatch_due()

    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1
    errors = data_transfer_schema_errors(transfers[0]["data"])
    assert errors == []


def test_PI_16_policy_authorised_entry_keeps_policy_authz_on_its_transfer(l2_undo_window_case_factory):
    """A policy-run send is never drawn as a person's approval or the reverse (PI-16)."""
    case = l2_undo_window_case_factory()
    entry = case["entry"]
    assert entry["authz"]["by"] == "policy"
    clock = ManualClock(entry["created_at"])
    emitted: list[dict] = []
    outbox = make_outbox(emitted, FakeGmail(), clock)
    outbox.enqueue(entry, evidence_from_case(case))

    clock.advance(60)
    outbox.dispatch_due()

    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1
    assert transfers[0]["authz"]["by"] == "policy"
    assert transfers[0]["authz"] == entry["authz"]


def test_PI_17_a_cancelled_entry_emits_nothing(l2_undo_window_case_factory):
    case = l2_undo_window_case_factory()
    entry = case["entry"]
    clock = ManualClock(entry["created_at"])
    emitted: list[dict] = []
    outbox = make_outbox(emitted, FakeGmail(), clock)
    outbox.enqueue(entry, evidence_from_case(case))

    outbox.cancel(entry["id"])
    clock.advance(120)
    sent = outbox.dispatch_due()

    assert sent == []
    assert emitted == []


def test_PI_17_a_failed_entry_emits_nothing(gate_case_factory):
    class AlwaysFailsGmail:
        def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
            raise RuntimeError("simulated permanent adapter failure")

    case = gate_case_factory(undo_window_s=0)
    emitted: list[dict] = []
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(
        store, {"gmail": AlwaysFailsGmail()}, emitted.append, ManualClock("2026-09-29T09:00:00.000Z")
    )
    outbox.enqueue(case["entry"], evidence_from_case(case))

    sent = outbox.dispatch_due()

    assert len(sent) == 1
    assert sent[0]["state"] == "failed"
    assert emitted == []
