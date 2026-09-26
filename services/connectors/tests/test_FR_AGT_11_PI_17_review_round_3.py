"""ST-2 review round 3 (code, security, qa): one data.transfer per sent entry, however many
instances flush the store, and in send order (PI-17, FR-AGT-11, PRD 9.4)."""

from __future__ import annotations

import threading
import time

import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail

T0 = "2026-09-29T09:32:09.500Z"


def _case(gate_case_factory, i: int):
    return gate_case_factory(
        outbox_id=f"01JB5VQ00000000000000096{i:02d}", idempotency_key=f"r_village_basic_1:U2:r3:{i}"
    )


class SlowRecorder:
    """A healthy but slow event writer shared by every instance; optionally down at first."""

    def __init__(self, down: bool = False, delay: float = 0.05) -> None:
        self.down = down
        self.delay = delay
        self.parts: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, part: dict) -> None:
        if self.down:
            raise RuntimeError("event writer unavailable")
        time.sleep(self.delay)
        with self.lock:
            self.parts.append(part)

    def transfer_ids(self) -> list[str]:
        return [p["data"]["outbox_id"] for p in self.parts if p["type"] == "data.transfer"]


def _run_concurrently(outboxes) -> None:
    threads = [threading.Thread(target=o.dispatch_due) for o in outboxes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_PI_17_overlapping_ticks_with_a_slow_writer_emit_one_transfer(gate_case_factory):
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    gmail = FakeGmail()
    writer = SlowRecorder()
    outboxes = [tilo_connectors.Outbox(store, {"gmail": gmail}, writer, clock) for _ in range(4)]
    case = _case(gate_case_factory, 1)
    outboxes[0].enqueue(case["entry"], evidence_from_case(case))
    _run_concurrently(outboxes)
    _run_concurrently(outboxes)
    assert len(gmail.sent) == 1
    assert writer.transfer_ids() == [case["entry"]["id"]]


def test_PI_17_many_instances_flushing_after_an_outage_emit_each_transfer_once(gate_case_factory):
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    gmail = FakeGmail()
    writer = SlowRecorder(down=True)
    outboxes = [tilo_connectors.Outbox(store, {"gmail": gmail}, writer, clock) for _ in range(4)]
    cases = [_case(gate_case_factory, i) for i in (2, 3)]
    for case in cases:
        outboxes[0].enqueue(case["entry"], evidence_from_case(case))
    outboxes[0].dispatch_due()
    writer.down = False
    _run_concurrently(outboxes)
    _run_concurrently(outboxes)
    assert len(gmail.sent) == 2
    assert writer.transfer_ids() == [c["entry"]["id"] for c in cases]


def test_PI_17_an_early_emit_failure_in_one_batch_keeps_send_order(gate_case_factory):
    recorded: list[dict] = []
    failures = {"left": 1}

    def flaky(part: dict) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("event writer blip")
        recorded.append(part)

    sent_keys: list[str] = []

    class OrderGmail(FakeGmail):
        def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
            result = super().send_reply(thread_id, item, recipients, idempotency_key, grant)
            sent_keys.append(idempotency_key)
            return result

    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), {"gmail": OrderGmail()}, flaky, ManualClock(T0)
    )
    cases = [_case(gate_case_factory, 4), _case(gate_case_factory, 5)]
    for case in cases:
        outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.dispatch_due()
    outbox.dispatch_due()
    id_by_key = {c["entry"]["idempotency_key"]: c["entry"]["id"] for c in cases}
    send_order = [id_by_key[k] for k in sent_keys]
    emitted = [p["data"]["outbox_id"] for p in recorded if p["type"] == "data.transfer"]
    assert len(send_order) == 2
    assert emitted == send_order
