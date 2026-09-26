"""ST-2 review round 2 (code, security, qa): exactly once across instances and restarts.

FR-AGT-11, FR-CHN-13, OB-03, PI-17 and PRD 9.4 (nothing happens without its event). Several
tilo-connectors instances share one store (Cloud Run scales out), and any of them may restart.
"""

from __future__ import annotations

import copy
import threading
import time

import pytest
import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail

T0 = "2026-09-29T09:32:09.500Z"


def _transfers(parts: list[dict]) -> list[dict]:
    return [p for p in parts if p["type"] == "data.transfer"]


def _case(gate_case_factory, i: int, **overrides):
    return gate_case_factory(
        outbox_id=f"01JB5VQ00000000000000095{i:02d}", idempotency_key=f"r_village_basic_1:U2:r2:{i}", **overrides
    )


class SlowGmail(FakeGmail):
    """Network latency inside the send, and a count of every adapter call."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.lock = threading.Lock()

    def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
        with self.lock:
            self.calls += 1
        time.sleep(0.05)
        return super().send_reply(thread_id, item, recipients, idempotency_key, grant)


def test_FR_AGT_11_OB_03_an_in_flight_send_is_not_claimed_again(gate_case_factory):
    """A claim holds while the send is in flight: four dispatchers on one store make one adapter
    call, not four (only a claim whose holder died may be taken over, after its lease)."""
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    gmail = SlowGmail()
    emitted: list[dict] = []
    outboxes = [tilo_connectors.Outbox(store, {"gmail": gmail}, emitted.append, clock) for _ in range(4)]
    case = _case(gate_case_factory, 1)
    outboxes[0].enqueue(case["entry"], evidence_from_case(case))
    threads = [threading.Thread(target=o.dispatch_due) for o in outboxes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert gmail.calls == 1
    assert len(gmail.sent) == 1
    assert len(_transfers(emitted)) == 1


def test_PI_17_a_pending_transfer_survives_a_restart(gate_case_factory):
    """emit fails after the send; a new Outbox on the same store (a restart, another instance)
    emits the transfer, exactly once. A sent entry never lacks its data.transfer (PRD 9.4)."""
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    gmail = FakeGmail()

    def down(part: dict) -> None:
        raise RuntimeError("event writer unavailable")

    first = tilo_connectors.Outbox(store, {"gmail": gmail}, down, clock)
    case = _case(gate_case_factory, 2)
    first.enqueue(case["entry"], evidence_from_case(case))
    try:
        first.dispatch_due()
    except RuntimeError:
        pass
    recorded: list[dict] = []
    restarted = tilo_connectors.Outbox(store, {"gmail": gmail}, recorded.append, clock)
    restarted.dispatch_due()
    restarted.dispatch_due()
    assert len(gmail.sent) == 1
    assert [t["data"]["outbox_id"] for t in _transfers(recorded)] == [case["entry"]["id"]]


def test_FR_AGT_11_an_emit_error_never_stops_the_batch(gate_case_factory):
    recorded: list[dict] = []
    failures = {"left": 1}

    def flaky(part: dict) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("event writer blip")
        recorded.append(part)

    gmail = FakeGmail()
    outbox = tilo_connectors.Outbox(tilo_connectors.InMemoryOutboxStore(), {"gmail": gmail}, flaky, ManualClock(T0))
    cases = [_case(gate_case_factory, i) for i in (3, 4, 5)]
    for case in cases:
        outbox.enqueue(case["entry"], evidence_from_case(case))
    settled = outbox.dispatch_due()  # must not raise
    assert sorted(e["state"] for e in settled) == ["sent", "sent", "sent"]
    outbox.dispatch_due()
    ids = [t["data"]["outbox_id"] for t in _transfers(recorded)]
    assert sorted(ids) == sorted(c["entry"]["id"] for c in cases)
    assert len(ids) == len(set(ids))


def test_FR_AGT_11_OB_03_racing_enqueues_of_one_key_store_one_entry(gate_case_factory):
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    gmail = FakeGmail()
    emitted: list[dict] = []
    a = _case(gate_case_factory, 6)
    b = copy.deepcopy(a)
    b["entry"]["id"] = "01JB5VQ0000000000000009699"
    outboxes = [tilo_connectors.Outbox(store, {"gmail": gmail}, emitted.append, clock) for _ in range(2)]

    def enqueue(outbox, case):
        try:
            outbox.enqueue(case["entry"], evidence_from_case(case))
        except tilo_connectors.OutboxRefused:
            pass

    threads = [threading.Thread(target=enqueue, args=(o, c)) for o, c in zip(outboxes, (a, b), strict=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    outboxes[0].dispatch_due()
    assert len(gmail.sent) == 1
    assert len(_transfers(emitted)) == 1


def test_PI_14_the_caller_changing_its_dict_after_enqueue_changes_nothing(gate_case_factory):
    gmail = FakeGmail()
    outbox = tilo_connectors.Outbox(tilo_connectors.InMemoryOutboxStore(), {"gmail": gmail}, [].append, ManualClock(T0))
    case = _case(gate_case_factory, 7)
    entry = copy.deepcopy(case["entry"])
    outbox.enqueue(entry, evidence_from_case(case))
    entry["recipients"] = ["stranger@evil.example"]
    entry["destination"] = "thread-elsewhere"
    outbox.dispatch_due()
    assert gmail.sent[0]["thread_id"] == case["entry"]["destination"]
    assert "stranger@evil.example" not in str(gmail.sent[0])


@pytest.mark.parametrize(
    "overrides", [{"undo_window_s": 10**12}, {"created_at": "9999-12-31T23:59:59.999Z", "undo_window_s": 1}]
)
def test_OB_02_an_out_of_range_schedule_is_refused_not_raised(overrides, gate_case_factory):
    case = _case(gate_case_factory, 8)
    entry = copy.deepcopy(case["entry"])
    entry.update(overrides)
    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), {"gmail": FakeGmail()}, [].append, ManualClock(T0)
    )
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(entry, evidence_from_case(case))


def test_PI_17_transfers_recovered_after_an_outage_keep_send_order(gate_case_factory):
    recorded: list[dict] = []
    state = {"down": True}

    def writer(part: dict) -> None:
        if state["down"]:
            raise RuntimeError("down")
        recorded.append(part)

    clock = ManualClock(T0)
    outbox = tilo_connectors.Outbox(tilo_connectors.InMemoryOutboxStore(), {"gmail": FakeGmail()}, writer, clock)
    order = []
    for i in (10, 11):
        case = _case(gate_case_factory, i)
        outbox.enqueue(case["entry"], evidence_from_case(case))
        outbox.dispatch_due()
        order.append(case["entry"]["id"])
        clock.advance(1)
    state["down"] = False
    outbox.dispatch_due()
    assert [t["data"]["outbox_id"] for t in _transfers(recorded)] == order
