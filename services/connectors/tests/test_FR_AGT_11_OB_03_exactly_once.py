"""FR-AGT-11 / OB-03 (contracts/outbox.rules.md, PRD 8.5, 11.4): retrying a send step never
produces a second email. `idempotency_key` is stable per step; the connector runs a key at most
once, so a crash between the adapter call and Outbox marking the entry "sent", followed by a
retry, and a retry storm of repeated or concurrent dispatch_due() calls, all still produce
exactly one send per key.
"""

from __future__ import annotations

import threading

import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_connectors.fakes import FakeGmail


def make_outbox(emitted: list[dict], gmail, clock: ManualClock | None = None):
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(
        store, {"gmail": gmail}, emitted.append, clock or ManualClock("2026-09-29T09:00:00.000Z")
    )
    return outbox


class CrashOnceGmail:
    """Wraps a real FakeGmail: the first call to send_reply performs the real send (so the
    underlying side effect happens, recorded in `.sent`) and then raises, simulating a crash
    between the adapter call and Outbox recording "sent". Every call after that succeeds
    normally -- and because FakeGmail itself dedupes by idempotency_key (OB-03), the retried
    call after the "crash" does not record a second send."""

    def __init__(self) -> None:
        self.real = FakeGmail()
        self.calls = 0

    @property
    def sent(self):
        return self.real.sent

    def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
        self.calls += 1
        result = self.real.send_reply(thread_id, item, recipients, idempotency_key, grant)
        if self.calls == 1:
            raise RuntimeError("simulated crash: adapter call completed, outbox has not marked sent yet")
        return result


def test_FR_AGT_11_retry_after_crash_sends_once(gate_case_factory):
    case = gate_case_factory(undo_window_s=0)
    emitted: list[dict] = []
    gmail = CrashOnceGmail()
    outbox = make_outbox(emitted, gmail)
    outbox.enqueue(case["entry"], evidence_from_case(case))

    # First attempt: the adapter call happens (gmail.real.sent gets one record) but the crash
    # means the entry is not yet settled as "sent".
    outbox.dispatch_due()
    assert len(gmail.sent) == 1, "the crash happens after the adapter call, not before it"

    # Retry: dispatch_due() is called again (the harness/operator retrying the send step).
    outbox.dispatch_due()

    assert len(gmail.sent) == 1, "retrying after a crash must never produce a second email"
    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1, "exactly one data.transfer, however many attempts it took"


@given(attempts=st.integers(min_value=1, max_value=25))
@settings(deadline=None)
def test_FR_AGT_11_OB_03_retry_storm_sends_one_per_key(attempts, gate_case_factory):
    """A retry storm: dispatch_due() called an arbitrary number of times in a row (Hypothesis
    varies the count) never sends more than once per idempotency key."""
    case = gate_case_factory(
        outbox_id="01JB5VQ0000000000000009401",
        idempotency_key="r_village_basic_1:U2:send_email:401",
        undo_window_s=0,
    )
    emitted: list[dict] = []
    gmail = FakeGmail()
    outbox = make_outbox(emitted, gmail)
    outbox.enqueue(case["entry"], evidence_from_case(case))

    for _ in range(attempts):
        outbox.dispatch_due()

    assert len(gmail.sent) == 1
    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1


def test_FR_AGT_11_OB_03_concurrent_dispatch_due_sends_once(gate_case_factory):
    """A genuine retry storm: many threads calling dispatch_due() on the same Outbox at once."""
    case = gate_case_factory(undo_window_s=0)
    emitted: list[dict] = []
    lock = threading.Lock()

    def emit(part: dict) -> None:
        with lock:
            emitted.append(part)

    gmail = FakeGmail()
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(store, {"gmail": gmail}, emit, ManualClock("2026-09-29T09:00:00.000Z"))
    outbox.enqueue(case["entry"], evidence_from_case(case))

    threads = [threading.Thread(target=outbox.dispatch_due) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(gmail.sent) == 1
    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1
