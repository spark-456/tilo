"""PI-12 / FR-HIL-05 (docs/security/p4-policy-invariants.md, PRD 10.4, 11.4 "Undo"), outbox
half: an L2 `run_after_undo` decision's entry keeps its undo window end to end. Built from the
ticket's own named fixture, contracts/fixtures/outbox/crossref/valid/
policy_reply_waiting_out_undo_window.json (undo_window_s 60): advancing the clock 59 s sends
nothing; cancelling then stops it sending even once its scheduled time passes; a second,
independent entry from the same shape, advanced the full 60 s, sends exactly once.
"""

from __future__ import annotations

import tilo_connectors
from conftest import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail


def make_outbox(emitted: list[dict], clock: ManualClock):
    gmail = FakeGmail()
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(store, {"gmail": gmail}, emitted.append, clock)
    return outbox, gmail


def test_PI_12_FR_HIL_05_59s_sends_nothing_then_cancel_never_sends(l2_undo_window_case_factory):
    case = l2_undo_window_case_factory()
    entry = case["entry"]
    assert entry["undo_window_s"] == 60
    clock = ManualClock(entry["created_at"])
    emitted: list[dict] = []
    outbox, gmail = make_outbox(emitted, clock)

    stored = outbox.enqueue(entry, evidence_from_case(case))
    assert stored["state"] == "scheduled"

    # 59 s in: still short of scheduled_at (created_at + 60 s) -- nothing due yet.
    clock.advance(59)
    sent = outbox.dispatch_due()
    assert sent == []
    assert gmail.sent == []
    assert emitted == []

    # Cancel before it is due.
    cancelled = outbox.cancel(entry["id"])
    assert cancelled["state"] == "cancelled"

    # Even once the original scheduled time (and well beyond) passes, a cancelled entry never
    # sends (PI-12: "a cancelled entry never sends").
    clock.advance(2)  # now 61 s past created_at, 1 s past the original scheduled_at
    sent = outbox.dispatch_due()
    assert sent == []
    assert gmail.sent == []
    assert emitted == []


def test_PI_12_FR_HIL_05_60s_sends_exactly_once(l2_undo_window_case_factory):
    case = l2_undo_window_case_factory(
        outbox_id="01JB5VQ0000000000000009206",
        idempotency_key="r_village_basic_1:U2:send_email:2",
        instruction_id="01JB5VQ0000000000000000232",
    )
    entry = case["entry"]
    clock = ManualClock(entry["created_at"])
    emitted: list[dict] = []
    outbox, gmail = make_outbox(emitted, clock)

    outbox.enqueue(entry, evidence_from_case(case))

    clock.advance(60)  # exactly scheduled_at: due (scheduled_at <= clock())
    sent = outbox.dispatch_due()

    assert len(sent) == 1
    assert sent[0]["id"] == entry["id"]
    assert sent[0]["state"] == "sent"
    assert len(gmail.sent) == 1
    assert gmail.sent[0]["idempotency_key"] == entry["idempotency_key"]
    assert gmail.sent[0]["thread_id"] == entry["destination"]

    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1

    # A second dispatch_due() call (nothing new became due) sends nothing further.
    sent_again = outbox.dispatch_due()
    assert sent_again == []
    assert len(gmail.sent) == 1
