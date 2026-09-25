"""OB-02 (contracts/outbox.rules.md, PI-12 docs/security/p4-policy-invariants.md): an entry
with no undo window is written "queued"; one with an undo window is "scheduled", and
`scheduled_at` equals `created_at` plus `undo_window_s`. Neither outbox.schema.json nor
tilo_policy.check_entry ties `state`/`scheduled_at` to `undo_window_s` (see API.md "OB-02,
resolved"), so Outbox.enqueue is the thing under test here: it must enforce the correlation
itself and refuse an entry where it does not hold.
"""

from __future__ import annotations

import pytest
import tilo_connectors
from conftest import ManualClock, add_seconds, evidence_from_case
from tilo_connectors.fakes import FakeGmail


def make_outbox(emitted: list[dict], clock: ManualClock | None = None):
    gmail = FakeGmail()
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(
        store, {"gmail": gmail}, emitted.append, clock or ManualClock("2026-09-29T09:00:00.000Z")
    )
    return outbox, gmail


def test_OB_02_no_undo_window_is_written_queued(gate_case_factory):
    case = gate_case_factory(undo_window_s=0)
    assert case["entry"]["state"] == "queued"
    assert case["entry"]["scheduled_at"] == case["entry"]["created_at"]
    outbox, _gmail = make_outbox([])
    stored = outbox.enqueue(case["entry"], evidence_from_case(case))
    assert stored["state"] == "queued"


def test_OB_02_undo_window_is_written_scheduled_at_created_at_plus_window(gate_case_factory):
    case = gate_case_factory(undo_window_s=60, created_at="2026-09-29T09:42:16.000Z")
    assert case["entry"]["state"] == "scheduled"
    assert case["entry"]["scheduled_at"] == "2026-09-29T09:43:16.000Z"
    outbox, _gmail = make_outbox([])
    stored = outbox.enqueue(case["entry"], evidence_from_case(case))
    assert stored["state"] == "scheduled"
    assert stored["scheduled_at"] == add_seconds(stored["created_at"], stored["undo_window_s"])


def test_OB_02_refuses_scheduled_at_not_equal_to_created_at_plus_undo_window_s(gate_case_factory):
    case = gate_case_factory(undo_window_s=60, created_at="2026-09-29T09:42:16.000Z")
    case["entry"]["scheduled_at"] = "2026-09-29T09:43:17.000Z"  # one second off
    outbox, _gmail = make_outbox([])
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(case["entry"], evidence_from_case(case))


def test_OB_02_refuses_queued_state_with_a_positive_undo_window(gate_case_factory):
    case = gate_case_factory(undo_window_s=60, created_at="2026-09-29T09:42:16.000Z")
    case["entry"]["state"] = "queued"  # should be "scheduled" for undo_window_s=60
    outbox, _gmail = make_outbox([])
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(case["entry"], evidence_from_case(case))


def test_OB_02_refuses_scheduled_state_with_no_undo_window(gate_case_factory):
    case = gate_case_factory(undo_window_s=0)
    case["entry"]["state"] = "scheduled"  # should be "queued" for undo_window_s=0
    outbox, _gmail = make_outbox([])
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(case["entry"], evidence_from_case(case))


def test_OB_02_cancel_moves_scheduled_to_cancelled(l2_undo_window_case_factory):
    case = l2_undo_window_case_factory()
    clock = ManualClock(case["entry"]["created_at"])
    outbox, _gmail = make_outbox([], clock)
    stored = outbox.enqueue(case["entry"], evidence_from_case(case))
    assert stored["state"] == "scheduled"
    cancelled = outbox.cancel(stored["id"])
    assert cancelled["state"] == "cancelled"


def test_OB_02_cancel_refused_for_a_queued_entry_with_no_undo_window(gate_case_factory):
    """ "Only until sending starts" presupposes there is an undo window to cancel; a queued
    entry (undo_window_s == 0) has none, so cancel refuses it."""
    case = gate_case_factory(undo_window_s=0)
    outbox, _gmail = make_outbox([])
    outbox.enqueue(case["entry"], evidence_from_case(case))
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.cancel(case["entry"]["id"])


def test_OB_02_cancel_refused_once_the_entry_has_already_sent(gate_case_factory):
    case = gate_case_factory(undo_window_s=0)
    outbox, gmail = make_outbox([])
    outbox.enqueue(case["entry"], evidence_from_case(case))
    sent = outbox.dispatch_due()
    assert len(sent) == 1
    assert sent[0]["state"] == "sent"
    assert len(gmail.sent) == 1
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.cancel(case["entry"]["id"])
