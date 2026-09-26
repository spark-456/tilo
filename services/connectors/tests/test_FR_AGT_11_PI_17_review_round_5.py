"""ST-2 review round 5 (qa) and #30 item 8: a retried transfer is exactly the part first built,
and an emit that lands after its lease expired still clears the transfer (PI-16, PI-17)."""

from __future__ import annotations

import copy
import threading

import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail

T0 = "2026-09-29T09:32:09.500Z"


def _case(gate_case_factory, i: int):
    return gate_case_factory(
        outbox_id=f"01JB5VQ00000000000000098{i:02d}", idempotency_key=f"r_village_basic_1:U2:r5:{i}"
    )


def test_PI_16_a_retried_transfer_is_the_part_first_built_even_if_the_writer_mutated_it(gate_case_factory):
    attempts: list[dict] = []
    state = {"fail": True}

    def mutating_then_failing(part: dict) -> None:
        attempts.append(copy.deepcopy(part))
        if state["fail"]:
            part["id"] = "evt_stale"
            part["seq"] = 7
            part["data"]["artifact"] = None
            raise RuntimeError("writer stamped the part, then failed to append it")

    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), {"gmail": FakeGmail()}, mutating_then_failing, ManualClock(T0)
    )
    case = _case(gate_case_factory, 1)
    outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.dispatch_due()
    state["fail"] = False
    outbox.dispatch_due()
    assert len(attempts) == 2
    assert attempts[1] == attempts[0]
    assert "id" not in attempts[1] and "seq" not in attempts[1]
    assert attempts[1]["data"]["artifact"] == case["entry"]["item"]


class RejectingDuplicatesWriter:
    """A PI-17 validator in front of the stream: a second data.transfer for an outbox_id raises."""

    def __init__(self) -> None:
        self.stream: list[dict] = []
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, part: dict) -> None:
        with self.lock:
            self.calls += 1
            if any(p["data"]["outbox_id"] == part["data"]["outbox_id"] for p in self.stream):
                raise RuntimeError("duplicate data.transfer for this outbox_id")
            self.stream.append(part)


def test_PI_17_an_emit_that_lands_after_its_lease_expired_still_clears_the_transfer(gate_case_factory):
    """A's emit reaches the writer first and then stalls past its lease; B takes the lease over and
    its emit is the one the writer rejects. When A returns, A must remove the transfer, or it stays
    pending forever and every later flush is rejected again."""
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    gmail = FakeGmail()
    writer = RejectingDuplicatesWriter()
    landed = threading.Event()
    release = threading.Event()

    def lands_then_stalls(part: dict) -> None:
        writer(part)
        landed.set()
        release.wait(5)

    a = tilo_connectors.Outbox(store, {"gmail": gmail}, lands_then_stalls, clock)
    b = tilo_connectors.Outbox(store, {"gmail": gmail}, writer, clock)
    case = _case(gate_case_factory, 2)
    a.enqueue(case["entry"], evidence_from_case(case))
    thread = threading.Thread(target=a.dispatch_due)
    thread.start()
    assert landed.wait(5)
    clock.advance(31)
    b.dispatch_due()  # B claims the expired lease; the writer rejects its duplicate
    release.set()
    thread.join(5)
    calls = writer.calls
    b.dispatch_due()
    b.dispatch_due()
    assert [p["data"]["outbox_id"] for p in writer.stream] == [case["entry"]["id"]]
    assert writer.calls == calls, "the transfer must not stay pending after A's emit landed"
