"""FR-CHN-05 authorisation: who may answer a WhatsApp card, and the PIN for T3 approvals.

PRD 10.3: WhatsApp answers come "only from the user's verified, bound number". PRD 10.4: T3 is "L1 only,
always a person". PRD 16.2: "PIN for T3 approvals over WhatsApp"; SEC-06: "Unbound or wrong-PIN approvals
are rejected". Contract approval.resolved: `pin_verified` is true when tilo-channels checked the person's
PIN before accepting the answer; "a T3 gate answered on WhatsApp opens only with it, and a wrong or
missing PIN emits no approval.resolved" (OB-01, ADR-0006). Only approve opens a gate (CR-07), so Hold and
Edit first need no PIN.

How the PIN is given is not in the PRD (BQ-89 default): tapping Approve on a T3 gate asks for the PIN;
the person types it as the next message from the same number within 300 s; one try per tap.

Public interface: `tilo_channels.cards.WhatsAppCards` (API_FR_CHN_03_05.md). The module does not exist
yet, so every test fails with ModuleNotFoundError when the rig is built.
"""

from __future__ import annotations

import logging

import pytest
from _chn_0305_lib import (
    GATE_T1,
    GATE_T3,
    NUM_RIYA,
    NUM_SAM,
    PIN_WINDOW_S,
    QUESTION,
    RIYA,
    SAM,
    CardRig,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@pytest.fixture()
def rig() -> CardRig:
    return CardRig()


def _approve_calls(rig: CardRig) -> list[dict]:
    return [c for c in rig.api.calls if c["option"] == "approve"]


def _wrong_pin(rig: CardRig) -> str:
    return rig.sam_pin  # a real PIN, but not Riya's


# --- T3 approve needs the PIN -------------------------------------------------------------------------


def test_FR_CHN_05_t3_approve_asks_for_pin_and_answers_nothing(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    result = rig.tap(sent, "approve", card_id=GATE_T3)
    assert result.outcome == "pin_required" and result.card_id == GATE_T3
    assert rig.api.calls == []  # no answer without the PIN: the gate stays shut
    prompts = rig.sender.texts_to(NUM_RIYA)
    assert len(prompts) == 1 and "PIN" in prompts[0]


def test_FR_CHN_05_t3_approve_with_correct_pin_opens_with_pin_verified(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    rig.clock.advance(30)
    result = rig.text(NUM_RIYA, rig.pin)
    assert result.outcome == "answered" and result.card_id == GATE_T3 and result.option == "approve"
    [call] = rig.api.accepted()
    assert (call["card_id"], call["option"], call["user_id"]) == (GATE_T3, "approve", RIYA)
    assert (call["channel"], call["pin_verified"]) == ("whatsapp", True)
    assert rig.pins.checks == [(RIYA, rig.pin, True)]


def test_FR_CHN_05_t3_wrong_pin_is_rejected_and_spends_the_prompt(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    result = rig.text(NUM_RIYA, _wrong_pin(rig))
    assert result.outcome == "wrong_pin"
    assert _approve_calls(rig) == []
    # The prompt is spent: the right PIN on its own now approves nothing.
    late = rig.text(NUM_RIYA, rig.pin)
    assert late.outcome != "answered"
    assert _approve_calls(rig) == []
    # Tap Approve again, then the right PIN.
    rig.tap(sent, "approve", card_id=GATE_T3)
    assert rig.text(NUM_RIYA, rig.pin).outcome == "answered"
    assert [c["pin_verified"] for c in rig.api.accepted()] == [True]


def test_FR_CHN_05_t3_pin_after_the_window_is_not_accepted(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    rig.clock.advance(PIN_WINDOW_S + 1)
    result = rig.text(NUM_RIYA, rig.pin)
    assert result.outcome != "answered"
    assert _approve_calls(rig) == []


def test_FR_CHN_05_t3_pin_from_another_number_does_not_approve(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    rig.text(NUM_SAM, rig.pin)  # Riya's PIN typed from Sam's bound number
    rig.text(NUM_SAM, rig.sam_pin)  # and Sam's own PIN
    assert _approve_calls(rig) == []


def test_FR_CHN_05_pin_without_a_pending_approve_does_nothing(rig: CardRig) -> None:
    rig.send(GATE_T3)
    result = rig.text(NUM_RIYA, rig.pin)
    assert result.outcome == "ignored"
    assert rig.api.calls == []


@pytest.mark.parametrize("option", ["hold", "edit"])
def test_FR_CHN_05_t3_hold_and_edit_need_no_pin(rig: CardRig, option: str) -> None:
    sent = rig.send(GATE_T3)
    result = rig.tap(sent, option, card_id=GATE_T3)
    assert result.outcome == "answered"
    [call] = rig.api.calls
    assert (call["option"], call["pin_verified"]) == (option, False)
    assert rig.pins.checks == []


def test_FR_CHN_05_t1_gate_approve_needs_no_pin(rig: CardRig) -> None:
    sent = rig.send(GATE_T1)
    result = rig.tap(sent, "approve", card_id=GATE_T1)
    assert result.outcome == "answered"
    [call] = rig.api.calls
    assert (call["option"], call["pin_verified"], call["user_id"]) == ("approve", False, RIYA)


def test_FR_CHN_05_pin_never_logged_archived_recorded_or_echoed(rig: CardRig, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    rig.text(NUM_RIYA, _wrong_pin(rig))
    rig.tap(sent, "approve", card_id=GATE_T3)
    rig.text(NUM_RIYA, rig.pin)
    for blob in (caplog.text, rig.events.dump(), rig.archive.dump(), rig.sender.everything()):
        assert rig.pin not in blob and rig.sam_pin not in blob
    assert NUM_RIYA not in caplog.text and NUM_RIYA[-7:] not in caplog.text


# --- only the bound user the card was sent to may answer ----------------------------------------------


def test_FR_CHN_05_another_bound_user_cannot_answer_a_card_sent_to_someone_else(rig: CardRig) -> None:
    sent = rig.send(QUESTION, user=RIYA)
    result = rig.tap(sent, "per_pack", sender=NUM_SAM, card_id=QUESTION)
    assert result.outcome in ("forbidden", "unknown_card")
    assert rig.api.calls == []
    assert rig.events.of_type("channel.message_in") == []


def test_FR_CHN_05_number_that_changed_hands_cannot_answer_the_old_card(rig: CardRig) -> None:
    sent = rig.send(QUESTION, user=RIYA)
    rig.bindings.by_number = {NUM_RIYA: SAM}  # Riya unbound; Sam later bound the same number
    result = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert result.outcome in ("forbidden", "unknown_card")
    assert rig.api.calls == []


def test_FR_CHN_05_answer_is_made_as_the_bound_user_never_from_the_payload(rig: CardRig) -> None:
    sam_sent = rig.send(QUESTION, user=SAM)
    rig.tap(sam_sent, "per_kwh", sender=NUM_SAM, card_id=QUESTION)
    assert [c["user_id"] for c in rig.api.calls] == [SAM]


# --- property: no T3 approval without a verified PIN ---------------------------------------------------

_action = st.one_of(
    st.tuples(st.just("tap"), st.sampled_from([NUM_RIYA, NUM_SAM]), st.sampled_from(["approve", "edit", "hold"])),
    st.tuples(st.just("text"), st.sampled_from([NUM_RIYA, NUM_SAM]), st.sampled_from(["riya", "sam", "junk"])),
    st.tuples(st.just("wait"), st.integers(min_value=1, max_value=200), st.none()),
)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(actions=st.lists(_action, max_size=25))
def test_FR_CHN_05_property_no_t3_approval_without_a_verified_pin(actions: list[tuple]) -> None:
    """PRD 10.4 "T3 ... always a person" and SEC-06, whatever arrives in whatever order: every approve sent
    to tilo-api for the T3 gate carries pin_verified, follows a successful PIN check of the card's own user,
    is made as that user, and the card is answered at most once."""
    rig = CardRig(card_ids=(GATE_T3,))
    sent = rig.send(GATE_T3)
    pins = {"riya": rig.pin, "sam": rig.sam_pin, "junk": "000000"}
    for op, a, b in actions:
        if op == "tap":
            rig.tap(sent, b, sender=a, card_id=GATE_T3)
        elif op == "text":
            rig.text(a, pins[b])
        else:
            rig.clock.advance(a)
        for call in rig.api.calls:
            assert call["user_id"] == RIYA
            if call["option"] == "approve":
                assert call["pin_verified"] is True
            if call["pin_verified"]:
                assert (RIYA, rig.pin, True) in rig.pins.checks
        assert len(rig.api.accepted()) <= 1
