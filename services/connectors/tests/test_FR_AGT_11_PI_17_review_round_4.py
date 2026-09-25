"""ST-2 review round 4 (security, qa): a transfer lease that expires mid-emit, and one stuck
transfer, never cost a second event or block other worlds (PI-17, FR-AGT-11, PRD 9.4).

The outbox delivers each data.transfer at least once; the event writer (the harness, PI-18)
keeps exactly one per outbox_id, so the stream holds exactly one (API.md "Delivery").
"""

from __future__ import annotations

import threading

import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail

T0 = "2026-09-29T09:32:09.500Z"


class DedupeWriter:
    """The harness writer as PI-17 has it: a second data.transfer for an outbox_id is dropped."""

    def __init__(self) -> None:
        self.stream: list[dict] = []
        self.lock = threading.Lock()
        self.calls = 0

    def __call__(self, part: dict) -> None:
        with self.lock:
            self.calls += 1
            if any(p["data"]["outbox_id"] == part["data"]["outbox_id"] for p in self.stream):
                return
            self.stream.append(part)


def _case(gate_case_factory, i: int, world_id: str = "w_village_basic"):
    return gate_case_factory(
        outbox_id=f"01JB5VQ00000000000000097{i:02d}",
        idempotency_key=f"r_village_basic_1:U2:r4:{i}",
        world_id=world_id,
    )


def test_PI_17_an_emit_that_outlives_its_lease_still_ends_with_one_transfer_and_nothing_pending(gate_case_factory):
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    gmail = FakeGmail()
    writer = DedupeWriter()
    release = threading.Event()
    entered = threading.Event()

    def stalling(part: dict) -> None:
        entered.set()
        release.wait(5)
        writer(part)

    a = tilo_connectors.Outbox(store, {"gmail": gmail}, stalling, clock)
    b = tilo_connectors.Outbox(store, {"gmail": gmail}, writer, clock)
    case = _case(gate_case_factory, 1)
    a.enqueue(case["entry"], evidence_from_case(case))
    thread = threading.Thread(target=a.dispatch_due)
    thread.start()
    assert entered.wait(5)
    clock.advance(31)  # A's transfer lease has expired while its emit is still running
    b.dispatch_due()
    release.set()
    thread.join()
    before = writer.calls
    b.dispatch_due()
    b.dispatch_due()
    assert len(gmail.sent) == 1
    assert [p["data"]["outbox_id"] for p in writer.stream] == [case["entry"]["id"]]
    assert writer.calls == before, "nothing may stay pending once the transfer is in the stream"


def test_PI_17_a_stuck_transfer_in_one_world_never_blocks_another_world(gate_case_factory):
    stuck = _case(gate_case_factory, 2, world_id="w_alpha")
    stuck_id = stuck["entry"]["id"]
    recorded: list[dict] = []

    def rejects_one(part: dict) -> None:
        if part["data"]["outbox_id"] == stuck_id:
            raise RuntimeError("writer rejects this part")
        recorded.append(part)

    gmail = FakeGmail()
    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), {"gmail": gmail}, rejects_one, ManualClock(T0)
    )
    others = [_case(gate_case_factory, i, world_id="w_beta") for i in (3, 4)]
    for case in (stuck, *others):
        outbox.enqueue(case["entry"], evidence_from_case(case))
    for _ in range(3):
        outbox.dispatch_due()
    assert len(gmail.sent) == 3
    assert [p["data"]["outbox_id"] for p in recorded] == [c["entry"]["id"] for c in others]
