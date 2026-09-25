"""FR-CHN-13 (PRD 11.4 "Threading", 12.1): a threaded send via Gmail goes through the outbox and
never becomes a new email — the reply always lands in the entry's `destination` (thread id),
whichever connector method sent it or how many times dispatch was retried.
"""

from __future__ import annotations

import tilo_connectors
from conftest import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail


def make_outbox(emitted: list[dict]):
    gmail = FakeGmail()
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock("2026-09-29T09:00:00.000Z")
    outbox = tilo_connectors.Outbox(store, {"gmail": gmail}, emitted.append, clock)
    return outbox, gmail


def test_FR_CHN_13_reply_lands_in_the_entrys_thread(gate_case_factory):
    case = gate_case_factory(undo_window_s=0, destination="thread-supplier-1")
    outbox, gmail = make_outbox([])
    outbox.enqueue(case["entry"], evidence_from_case(case))

    outbox.dispatch_due()

    assert len(gmail.sent) == 1
    assert gmail.sent[0]["thread_id"] == "thread-supplier-1"


def test_FR_CHN_13_two_different_threads_never_get_mixed_up(gate_case_factory):
    case_a = gate_case_factory(
        outbox_id="01JB5VQ0000000000000009301",
        idempotency_key="r_village_basic_1:U2:send_email:301",
        destination="thread-supplier-1",
    )
    case_b = gate_case_factory(
        outbox_id="01JB5VQ0000000000000009302",
        idempotency_key="r_village_basic_1:U3:send_email:302",
        destination="thread-buyer-9",
    )
    outbox, gmail = make_outbox([])
    outbox.enqueue(case_a["entry"], evidence_from_case(case_a))
    outbox.enqueue(case_b["entry"], evidence_from_case(case_b))

    outbox.dispatch_due()

    assert len(gmail.sent) == 2
    by_key = {s["idempotency_key"]: s for s in gmail.sent}
    assert by_key[case_a["entry"]["idempotency_key"]]["thread_id"] == "thread-supplier-1"
    assert by_key[case_b["entry"]["idempotency_key"]]["thread_id"] == "thread-buyer-9"


def test_FR_CHN_13_retrying_the_send_step_never_creates_a_second_email_in_the_thread(gate_case_factory):
    """A retry storm on the outbox's public surface (repeated dispatch_due() calls, the way a
    crashed harness or a duplicate webhook would trigger one): the thread only ever gets one
    reply, never a second one and never a new, un-threaded email."""
    case = gate_case_factory(undo_window_s=0, destination="thread-supplier-1")
    outbox, gmail = make_outbox([])
    outbox.enqueue(case["entry"], evidence_from_case(case))

    for _ in range(25):
        outbox.dispatch_due()

    replies_in_thread = [s for s in gmail.sent if s["thread_id"] == "thread-supplier-1"]
    assert len(replies_in_thread) == 1
    assert len(gmail.sent) == 1
