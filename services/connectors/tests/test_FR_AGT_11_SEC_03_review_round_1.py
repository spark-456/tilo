"""ST-2 review round 1 (code, security, qa): exactly once, Undo and the SEC-03 capability hold
against the attacks that broke them.

FR-AGT-11 "retrying a send step never produces a second email", FR-CHN-13, SEC-03 "policy engine
is the only path to side effects", OB-02 / OB-03 / OB-05 (contracts/outbox.rules.md), PI-12 and
PI-14 (docs/security/p4-policy-invariants.md). Each test is a probe that sent twice, sent after
Undo, accepted a forged capability, slipped past the static scan or left an entry stuck.
"""

from __future__ import annotations

import copy
import inspect
import threading

import pytest
import tilo_connectors
from _connectors_lib import ManualClock, add_seconds, evidence_from_case
from tilo_connectors.fakes import FakeGmail
from tilo_connectors.side_effects import scan_for_side_effect_calls

T0 = "2026-09-29T09:32:09.500Z"


def _outbox(emitted: list[dict], clock: ManualClock, connectors: dict | None = None, store=None):
    gmail = FakeGmail()
    outbox = tilo_connectors.Outbox(
        store if store is not None else tilo_connectors.InMemoryOutboxStore(),
        connectors if connectors is not None else {"gmail": gmail},
        emitted.append,
        clock,
    )
    return outbox, gmail


def _transfers(emitted: list[dict]) -> list[dict]:
    return [p for p in emitted if p["type"] == "data.transfer"]


# --- enqueue writes only new entries (security biggest problem) ------------------------------


@pytest.mark.parametrize("state", ["sending", "sent", "failed", "cancelled"])
def test_FR_AGT_11_OB_02_enqueue_refuses_an_entry_that_is_not_new(state, gate_case_factory):
    case = gate_case_factory(undo_window_s=60)
    entry = copy.deepcopy(case["entry"])
    entry["state"] = state
    outbox, gmail = _outbox([], ManualClock(add_seconds(T0, 120)))
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(entry, evidence_from_case(case))
    assert outbox.dispatch_due() == []
    assert gmail.sent == []


def test_PI_12_OB_02_cancelled_entry_cannot_be_revived_under_a_new_key(gate_case_factory):
    clock = ManualClock(T0)
    case = gate_case_factory(undo_window_s=60)
    outbox, gmail = _outbox([], clock)
    outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.cancel(case["entry"]["id"])

    revived = copy.deepcopy(case["entry"])
    revived["idempotency_key"] = case["entry"]["idempotency_key"] + ":again"
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(revived, evidence_from_case(case))
    clock.advance(120)
    assert outbox.dispatch_due() == []
    assert gmail.sent == []


def test_FR_AGT_11_PI_14_sent_entry_cannot_be_sent_again_under_a_new_key(gate_case_factory):
    emitted: list[dict] = []
    case = gate_case_factory(undo_window_s=0)
    outbox, gmail = _outbox(emitted, ManualClock(T0))
    outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.dispatch_due()

    again = copy.deepcopy(case["entry"])
    again["idempotency_key"] = case["entry"]["idempotency_key"] + ":again"
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(again, evidence_from_case(case))
    outbox.dispatch_due()
    assert len(gmail.sent) == 1
    assert len(_transfers(emitted)) == 1


# --- OB-03 keys are unique per world, not across worlds (qa biggest problem) ------------------


def test_FR_AGT_11_OB_03_same_key_in_two_worlds_sends_both(gate_case_factory):
    emitted: list[dict] = []
    alpha = gate_case_factory(
        world_id="w_alpha",
        outbox_id="01JB5VQ0000000000000009100",
        destination="thread-A",
        recipients=("a@example.com",),
    )
    beta = gate_case_factory(
        world_id="w_beta", outbox_id="01JB5VQ0000000000000009101", destination="thread-B", recipients=("b@example.com",)
    )
    assert alpha["entry"]["idempotency_key"] == beta["entry"]["idempotency_key"]
    outbox, gmail = _outbox(emitted, ManualClock(T0))
    for case in (alpha, beta):
        outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.dispatch_due()
    assert sorted(s["thread_id"] for s in gmail.sent) == ["thread-A", "thread-B"]
    assert len(_transfers(emitted)) == 2


# --- SEC-03 runtime capability cannot be forged or reused --------------------------------------


def _forged_grants() -> list:
    grant_cls = tilo_connectors.outbox.Grant
    forged = []
    try:
        forged.append(grant_cls(*["forged"] * len(inspect.signature(grant_cls).parameters)))
    except Exception:  # noqa: BLE001 - a Grant nobody outside the outbox can build is the goal
        pass
    forged.append(object.__new__(grant_cls))
    try:
        subclass = type("SubGrant", (grant_cls,), {})
        forged.append(object.__new__(subclass))
    except TypeError:  # a final Grant cannot be subclassed at all, which is fine
        pass
    return forged


def test_SEC_03_a_grant_the_outbox_did_not_mint_is_refused():
    for grant in _forged_grants():
        with pytest.raises(tilo_connectors.MissingGrant):
            FakeGmail().send_reply("thread-x", None, ["x@example.com"], "key-forged", grant)


def test_SEC_03_a_real_grant_only_covers_its_own_send(gate_case_factory):
    captured: list = []

    class RecordingGmail(FakeGmail):
        def send_reply(self, thread_id, item, recipients, idempotency_key, grant):  # noqa: D401
            captured.append(grant)
            return super().send_reply(thread_id, item, recipients, idempotency_key, grant)

    gmail = RecordingGmail()
    case = gate_case_factory(undo_window_s=0)
    outbox = tilo_connectors.Outbox(tilo_connectors.InMemoryOutboxStore(), {"gmail": gmail}, [].append, ManualClock(T0))
    outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.dispatch_due()
    assert captured, "the outbox must hand the adapter a grant"
    with pytest.raises(tilo_connectors.MissingGrant):
        FakeGmail().send_reply("thread-other", None, ["stranger@example.net"], "another-key", captured[0])


# --- SEC-03 static scan catches indirect references --------------------------------------------

BYPASSES = {
    "getattr": 'def f(gmail):\n    return getattr(gmail, "send_reply")("t", None, [], "k", None)\n',
    "alias": "def f(gmail):\n    send = gmail.send_reply\n    return send('t', None, [], 'k', None)\n",
    "partial": "import functools\n\ndef f(gmail):\n    return functools.partial(gmail.send_reply, 't')\n",
    "methodcaller": 'import operator\n\ndef f(gmail):\n    return operator.methodcaller("send_reply", "t")(gmail)\n',
    "dunder_call": "def f(gmail):\n    return gmail.send_reply.__call__('t', None, [], 'k', None)\n",
}


@pytest.mark.parametrize("form", sorted(BYPASSES))
def test_SEC_03_static_scan_flags_indirect_references(form, tmp_path, outbox_module_path):
    offender = tmp_path / f"offender_{form}.py"
    offender.write_text(BYPASSES[form], encoding="utf-8")
    assert scan_for_side_effect_calls([offender], allowed_path=outbox_module_path), form


# --- one state change at a time (compare-and-set) ----------------------------------------------


def test_PI_12_OB_02_cancel_on_one_outbox_stops_a_send_from_another(gate_case_factory):
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    case = gate_case_factory(undo_window_s=60)
    first, gmail_first = _outbox([], clock, store=store)
    second, gmail_second = _outbox([], clock, store=store)
    first.enqueue(case["entry"], evidence_from_case(case))
    first.cancel(case["entry"]["id"])
    clock.advance(120)
    assert second.dispatch_due() == []
    assert gmail_first.sent == [] and gmail_second.sent == []


def test_PI_12_OB_02_cancel_racing_dispatch_never_both_succeed(gate_case_factory):
    for i in range(30):
        store = tilo_connectors.InMemoryOutboxStore()
        clock = ManualClock(T0)
        case = gate_case_factory(
            undo_window_s=60,
            outbox_id=f"01JB5VQ00000000000000092{i:02d}",
            idempotency_key=f"r_village_basic_1:U2:x:{i}",
        )
        gmail = FakeGmail()
        mover = tilo_connectors.Outbox(store, {"gmail": gmail}, [].append, clock)
        canceller = tilo_connectors.Outbox(store, {"gmail": gmail}, [].append, clock)
        mover.enqueue(case["entry"], evidence_from_case(case))
        clock.advance(60)
        cancelled: list[bool] = []

        def cancel(c=canceller, oid=case["entry"]["id"]):
            try:
                c.cancel(oid)
                cancelled.append(True)
            except tilo_connectors.OutboxRefused:
                cancelled.append(False)

        threads = [threading.Thread(target=mover.dispatch_due), threading.Thread(target=cancel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not (cancelled[0] and gmail.sent), f"run {i}: cancel reported success but the reply was sent"
        assert len(gmail.sent) <= 1


# --- nothing is ever stuck; a crash then a retry ends exactly once -----------------------------


class DiesOnce(FakeGmail):
    """A process death (not an Exception) around the side effect, once."""

    def __init__(self, after_send: bool) -> None:
        super().__init__()
        self.after_send = after_send
        self.died = False

    def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
        if not self.died and not self.after_send:
            self.died = True
            raise KeyboardInterrupt
        result = super().send_reply(thread_id, item, recipients, idempotency_key, grant)
        if not self.died:
            self.died = True
            raise KeyboardInterrupt
        return result


@pytest.mark.parametrize("after_send", [False, True])
def test_FR_AGT_11_process_death_mid_send_then_retry_sends_once(after_send, gate_case_factory):
    emitted: list[dict] = []
    gmail = DiesOnce(after_send)
    case = gate_case_factory(undo_window_s=0)
    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), {"gmail": gmail}, emitted.append, ManualClock(T0)
    )
    outbox.enqueue(case["entry"], evidence_from_case(case))
    with pytest.raises(KeyboardInterrupt):
        outbox.dispatch_due()
    outbox.dispatch_due()
    assert len(gmail.sent) == 1
    assert len(_transfers(emitted)) == 1


def test_FR_AGT_11_PI_17_emit_failure_then_retry_emits_one_transfer(gate_case_factory):
    recorded: list[dict] = []
    failures = {"left": 1}

    def flaky_emit(part: dict) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("event writer unavailable")
        recorded.append(part)

    gmail = FakeGmail()
    case = gate_case_factory(undo_window_s=0)
    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), {"gmail": gmail}, flaky_emit, ManualClock(T0)
    )
    outbox.enqueue(case["entry"], evidence_from_case(case))
    try:
        outbox.dispatch_due()
    except RuntimeError:
        pass
    outbox.dispatch_due()
    assert len(gmail.sent) == 1
    assert len(_transfers(recorded)) == 1


def test_FR_AGT_11_OB_05_missing_adapter_fails_the_entry_and_the_batch_goes_on(gate_case_factory):
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock(T0)
    writer, _ = _outbox([], clock, store=store)
    for i in (1, 2):
        case = gate_case_factory(
            outbox_id=f"01JB5VQ000000000000000930{i}", idempotency_key=f"r_village_basic_1:U2:y:{i}"
        )
        writer.enqueue(case["entry"], evidence_from_case(case))
    no_adapters = tilo_connectors.Outbox(store, {}, [].append, clock)
    settled = no_adapters.dispatch_due()
    assert sorted(e["state"] for e in settled) == ["failed", "failed"]
    assert no_adapters.dispatch_due() == []
