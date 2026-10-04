"""CHN-GATE-A gate 1, outbox half (issue #256; gates FR-CHN-11, PRD 11.6 "no send after cancel"; OB-02, OB-03):
the real `tilo_connectors.Outbox` gets a read port, `get(outbox_id)` and `get_by_idempotency_key(world_id, key)`,
so a stop can find a card's entry without enqueueing it, and `revoke(world_id, key)`, so that after a revocation the
outbox refuses to create the key ("check_entry must refuse creation after a revocation"). Reads never write; a
revocation never creates an entry; keys are never pruned. API: API_CHN_GATE_A.md beside this file (BQ-186).

Built from contracts/fixtures/outbox/crossref/valid/policy_reply_waiting_out_undo_window.json (L2, 60 s window), with
its real OB-01 evidence. FakeGmail only; no network, no real mail.
"""

from __future__ import annotations

import threading
import unittest.mock

import pytest
import tilo_connectors
import tilo_policy
from _connectors_lib import ManualClock, evidence_from_case
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_connectors import InMemoryOutboxStore, Outbox, OutboxRefused
from tilo_connectors.fakes import FakeGmail


class Line:
    """One store, one FakeGmail, any number of Outbox instances (world-scoped or not) over them."""

    def __init__(self, case: dict) -> None:
        self.case = case
        self.entry = case["entry"]
        self.evidence = evidence_from_case(case)
        self.world, self.key = self.entry["world_id"], self.entry["idempotency_key"]
        self.clock = ManualClock(self.entry["created_at"])
        self.store = InMemoryOutboxStore()
        self.gmail = FakeGmail()
        self.emitted: list[dict] = []
        self.outbox = self.new_outbox()

    def new_outbox(self, world_id: str | None = None) -> Outbox:
        return Outbox(self.store, {"gmail": self.gmail}, self.emitted.append, self.clock, world_id=world_id)

    def enqueue(self) -> dict:
        return self.outbox.enqueue(dict(self.entry), self.evidence)

    def run_out(self, seconds: float = 61) -> list[dict]:
        self.clock.advance(seconds)
        self.outbox.dispatch_due()
        return self.gmail.sent


@pytest.fixture()
def line(l2_undo_window_case_factory) -> Line:
    return Line(l2_undo_window_case_factory())


def test_CHN_GATE_A_FR_CHN_11_read_port_finds_the_stored_entry_by_id_and_by_key(line: Line) -> None:
    stored = line.enqueue()
    assert line.outbox.get(stored["id"]) == stored
    assert line.outbox.get_by_idempotency_key(line.world, line.key) == stored
    assert line.outbox.get("01JB5VQ00000000000000ZZZZZ") is None
    assert line.outbox.get_by_idempotency_key(line.world, line.key + ":other") is None
    assert line.outbox.get_by_idempotency_key("w_another_world", line.key) is None


def test_CHN_GATE_A_FR_CHN_11_reads_never_write_and_never_ask_the_policy_engine(line: Line) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("a read called tilo_policy.check_entry")

    with unittest.mock.patch.object(tilo_policy, "check_entry", refuse):
        assert line.outbox.get(line.entry["id"]) is None, "nothing is stored yet"
        assert line.outbox.get_by_idempotency_key(line.world, line.key) is None
    assert line.store.all_entries() == [], "a read created an entry"
    stored = line.enqueue()
    with unittest.mock.patch.object(tilo_policy, "check_entry", refuse):
        found = line.outbox.get(stored["id"])
        found["state"], found["recipients"] = "cancelled", ["eve@attacker.example"]
        by_key = line.outbox.get_by_idempotency_key(line.world, line.key)
        by_key["state"] = "sent"
    assert line.store.all_entries() == [stored], "a read handed out the stored dict, not a copy"
    assert len(line.run_out()) == 1, "the entry still sends at 60 s"


def test_CHN_GATE_A_FR_CHN_11_keys_are_never_pruned(line: Line) -> None:
    stored = line.enqueue()
    assert len(line.run_out()) == 1
    for _ in range(3):
        line.clock.advance(40 * 86_400)
        line.outbox.dispatch_due()
    assert line.outbox.get_by_idempotency_key(line.world, line.key)["state"] == "sent"
    assert line.outbox.get(stored["id"])["state"] == "sent"
    assert line.outbox.revoke(line.world, line.key)["state"] == "sent", "a revocation never rewrites history"
    assert line.enqueue()["state"] == "sent", "the same key returns the stored entry, never a new one"
    assert len(line.store.all_entries()) == 1 and len(line.gmail.sent) == 1


def test_CHN_GATE_A_FR_CHN_11_revoking_an_absent_key_creates_nothing_and_refuses_it_forever(line: Line) -> None:
    assert line.outbox.revoke(line.world, line.key) is None
    assert line.store.all_entries() == [], "a revocation created an entry"
    assert line.outbox.get_by_idempotency_key(line.world, line.key) is None
    with pytest.raises(OutboxRefused):
        line.enqueue()
    assert line.outbox.revoke(line.world, line.key) is None, "idempotent"
    with pytest.raises(OutboxRefused):
        line.new_outbox().enqueue(dict(line.entry), line.evidence)  # another instance over the same store
    assert line.store.all_entries() == []
    assert line.run_out(3600) == []


def test_CHN_GATE_A_FR_CHN_11_revoking_a_scheduled_entry_cancels_it_and_it_never_sends(line: Line) -> None:
    stored = line.enqueue()
    line.clock.advance(30)
    revoked = line.outbox.revoke(line.world, line.key)
    assert revoked["id"] == stored["id"] and revoked["state"] == "cancelled"
    assert line.outbox.get(stored["id"])["state"] == "cancelled"
    assert line.outbox.revoke(line.world, line.key)["state"] == "cancelled", "idempotent"
    try:
        again = line.enqueue()
    except OutboxRefused:
        again = None
    assert again is None or again["state"] == "cancelled"
    assert len(line.store.all_entries()) == 1
    assert line.run_out(3600) == []


def test_CHN_GATE_A_FR_CHN_11_world_scoped_outbox_never_reads_or_revokes_another_world(line: Line) -> None:
    stored = line.enqueue()
    other = line.new_outbox(world_id="w_another_world")
    assert other.get(stored["id"]) is None
    assert other.get_by_idempotency_key(line.world, line.key) is None
    try:
        other.revoke(line.world, line.key)
    except OutboxRefused:
        pass
    assert line.outbox.get(stored["id"])["state"] == "scheduled", "another world's outbox changed this entry"
    assert len(line.run_out()) == 1


def test_CHN_GATE_A_FR_CHN_11_world_scoped_outbox_never_revokes_another_worlds_absent_key(line: Line) -> None:
    other = line.new_outbox(world_id="w_another_world")
    try:
        other.revoke(line.world, line.key)
    except OutboxRefused:
        pass
    assert line.enqueue()["state"] == "scheduled", "another world's outbox blocked this world's key"
    assert len(line.run_out()) == 1


def test_CHN_GATE_A_FR_CHN_11_revoke_racing_enqueue_never_leaves_a_sendable_entry(l2_undo_window_case_factory) -> None:
    assert hasattr(tilo_connectors.Outbox, "revoke"), "CHN-GATE-A: Outbox.revoke is missing (API_CHN_GATE_A.md)"
    case = l2_undo_window_case_factory()
    for _ in range(60):
        line = Line(case)
        barrier, answers = threading.Barrier(2), {}

        def enqueue(line: Line = line, barrier: threading.Barrier = barrier, answers: dict = answers) -> None:
            barrier.wait(timeout=10)
            try:
                answers["enqueue"] = line.enqueue()["state"]
            except OutboxRefused:
                answers["enqueue"] = "refused"

        def revoke(line: Line = line, barrier: threading.Barrier = barrier, answers: dict = answers) -> None:
            barrier.wait(timeout=10)
            found = line.outbox.revoke(line.world, line.key)
            answers["revoke"] = None if found is None else found["state"]

        threads = [threading.Thread(target=enqueue), threading.Thread(target=revoke)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert set(answers) == {"enqueue", "revoke"}, answers
        assert answers["revoke"] in (None, "cancelled"), answers
        if answers["revoke"] is None:
            assert answers["enqueue"] == "refused", f"stored after a revocation found nothing: {answers}"
        states = [e["state"] for e in line.store.all_entries()]
        assert all(s == "cancelled" for s in states) and len(states) <= 1, states
        assert line.run_out(3600) == []


OPS = st.lists(st.sampled_from(["enqueue", "revoke", "cancel", "get", "find", "advance", "dispatch"]), max_size=14)


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],  # a stateless factory
)
@given(ops=OPS)
def test_CHN_GATE_A_FR_CHN_11_one_key_any_sequence_reads_are_pure_and_revoked_never_sends(
    l2_undo_window_case_factory, ops
) -> None:
    for name in ("get", "get_by_idempotency_key", "revoke"):
        assert hasattr(tilo_connectors.Outbox, name), f"CHN-GATE-A: Outbox.{name} is missing (API_CHN_GATE_A.md)"
    line = Line(l2_undo_window_case_factory())
    revoked_at_sent = None  # the number of sends when the first revocation happened
    for op in ops:
        before = line.store.all_entries()
        if op == "enqueue":
            try:
                line.enqueue()
            except OutboxRefused:
                assert revoked_at_sent is not None, "refused although never revoked"
        elif op == "revoke":
            line.outbox.revoke(line.world, line.key)
            revoked_at_sent = len(line.gmail.sent) if revoked_at_sent is None else revoked_at_sent
        elif op == "cancel":
            try:
                line.outbox.cancel(line.entry["id"])
            except OutboxRefused:
                pass
        elif op in ("get", "find"):
            if op == "get":
                line.outbox.get(line.entry["id"])
            else:
                line.outbox.get_by_idempotency_key(line.world, line.key)
            assert line.store.all_entries() == before, "a read changed the store"
        elif op == "advance":
            line.clock.advance(25)
        else:
            line.outbox.dispatch_due()
        assert len(line.store.all_entries()) <= 1, "one key, one entry"
    line.run_out(3600)
    if revoked_at_sent is not None:
        assert len(line.gmail.sent) == revoked_at_sent, "sent after a revocation"
    assert len(line.gmail.sent) <= 1
