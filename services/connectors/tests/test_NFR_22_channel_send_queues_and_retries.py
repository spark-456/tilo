"""NFR-22 (PRD 17.2): "... channels queue and retry." Outbound half: a channel send (here the Gmail reply the
Email Autopilot and the run enqueue) goes through the outbox, the only path to a side effect (SEC-03). When the
provider fails (429 quota, 5xx or a lost answer) the entry stays queued with a not-before time, is retried with
backoff, and is sent exactly once when the provider recovers. It is never lost and never sent twice.

Implemented by `tilo_connectors.outbox.Outbox` and `RetryPolicy` (FR-CON-04, FR-AGT-13); production passes
`RetryPolicy()`. Fakes only: no network, no real account.
"""

from __future__ import annotations

import pytest
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors import InMemoryOutboxStore, Outbox
from tilo_connectors.adapters import ProviderUnavailable, RateLimited
from tilo_connectors.fakes import FakeGmail
from tilo_connectors.outbox import RetryPolicy

T0 = "2026-09-29T09:32:09.500Z"


class FlakyGmail(FakeGmail):
    """Fails with the scripted errors, then recovers."""

    def __init__(self, errors: list[Exception]) -> None:
        super().__init__()
        self.errors, self.attempts = list(errors), 0

    def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
        self.attempts += 1
        if self.errors:
            raise self.errors.pop(0)
        return super().send_reply(thread_id, item, recipients, idempotency_key, grant)


def _rig(gate_case_factory, errors, store=None):
    clock, emitted = ManualClock(T0), []
    gmail = FlakyGmail(errors)
    store = store if store is not None else InMemoryOutboxStore()
    outbox = Outbox(store, {"gmail": gmail}, emitted.append, clock, retry=RetryPolicy())
    case = gate_case_factory(undo_window_s=0)
    outbox.enqueue(case["entry"], evidence_from_case(case))
    return outbox, gmail, clock, emitted, case["entry"]["id"], store


@pytest.mark.parametrize(
    "error",
    [RateLimited(120), ProviderUnavailable("the provider did not answer")],
    ids=["quota_429", "provider_5xx"],
)
def test_NFR_22_a_send_that_fails_stays_queued_and_is_retried_until_it_goes_once(gate_case_factory, error):
    outbox, gmail, clock, emitted, oid, _ = _rig(gate_case_factory, [error, error, error])

    for _round in range(6):
        outbox.dispatch_due()
        entry = outbox.get(oid)
        assert entry is not None, "a failed send is never lost"
        if entry["state"] == "sent":
            break
        assert entry["state"] != "failed", "three transient failures do not end the entry (max_attempts is 8)"
        assert gmail.sent == [], "nothing is sent while the provider keeps failing"
        clock.advance(3_600)  # past any backoff, Retry-After or ambiguity delay (max_delay_s)

    assert outbox.get(oid)["state"] == "sent"
    assert gmail.attempts == 4, "three failures, then the retry that succeeds"
    assert len(gmail.sent) == 1, "sent exactly once"
    assert [p["type"] for p in emitted] == ["data.transfer"]


def test_NFR_22_a_queued_send_survives_a_restart_and_goes_when_the_provider_recovers(gate_case_factory):
    outbox, gmail, clock, emitted, oid, store = _rig(gate_case_factory, [RateLimited(60)])
    outbox.dispatch_due()
    assert outbox.get(oid)["state"] != "failed" and gmail.sent == []

    clock.advance(60)
    restarted = Outbox(store, {"gmail": gmail}, emitted.append, clock, retry=RetryPolicy())  # a new process
    assert [e["state"] for e in restarted.dispatch_due()] == ["sent"]
    assert len(gmail.sent) == 1


def test_NFR_22_a_send_retried_after_a_lost_answer_is_not_sent_twice(gate_case_factory):
    outbox, gmail, clock, _, oid, _ = _rig(gate_case_factory, [])
    original_send = FakeGmail.send_reply

    calls: list[int] = []

    def send_then_lose_the_answer(thread_id, item, recipients, key, grant):
        record = original_send(gmail, thread_id, item, recipients, key, grant)
        calls.append(1)
        if len(calls) == 1:
            raise ProviderUnavailable("sent, but the answer was lost")
        return record

    gmail.send_reply = send_then_lose_the_answer  # type: ignore[method-assign]
    outbox.dispatch_due()
    clock.advance(3_600)
    outbox.dispatch_due()

    assert len(gmail.sent) == 1, "the idempotency key makes the retry a no-op at the provider"
    assert outbox.get(oid)["state"] == "sent"
