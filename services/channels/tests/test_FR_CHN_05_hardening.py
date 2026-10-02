"""FR-CHN-05 hardening from the #154 reviews (issue #156): honest unknown-outcome replies, late PINs never
routed, send_card failures and retries, closed cards stay closed, malformed cards, eviction. Defaults:
BQ-89 in docs/open-questions.md."""

from __future__ import annotations

from typing import Any

import pytest
from _chn_0305_lib import GATE_T3, NUM_RIYA, PIN_WINDOW_S, QUESTION, RIYA, SAM, WEB_URL, ApiAnswer, CardRig, make_card
from tilo_channels.inbound import InboundRouter

UNKNOWN = "Could not confirm your answer. Check the card in Tilo before tapping again."
LATE = "That PIN came too late. Tap Approve again."


@pytest.fixture()
def rig() -> CardRig:
    return CardRig()


def _texts(rig: CardRig) -> list[str]:
    return rig.sender.texts_to(NUM_RIYA)


def test_FR_CHN_05_api_error_reply_says_the_outcome_is_unknown(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.api.fail_next = TimeoutError("tilo-api timed out after recording")
    assert rig.tap(sent, "per_pack", card_id=QUESTION).outcome == "failed"
    assert _texts(rig) == [UNKNOWN]


# --- late PINs are consumed, never routed or archived ------------------------------------------------


def test_FR_CHN_05_second_text_pin_is_consumed_as_late(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    assert rig.text(NUM_RIYA, rig.sam_pin).outcome == "wrong_pin"
    archived = len(rig.archive.records)
    result = rig.text(NUM_RIYA, rig.pin)
    assert (result.outcome, result.card_id) == ("pin_late", GATE_T3)
    assert _texts(rig)[-1] == LATE
    assert rig.api.calls == [] and len(rig.pins.checks) == 1
    assert len(rig.archive.records) == archived and rig.pin not in rig.archive.dump() + rig.events.dump()


def test_FR_CHN_05_pin_in_the_grace_window_never_reaches_unhandled(rig: CardRig) -> None:
    router = InboundRouter(bindings=rig.bindings, sender=rig.sender, web_url=WEB_URL, cards=rig.svc)
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    rig.clock.advance(PIN_WINDOW_S + 1)
    assert router.handle(rig.message(NUM_RIYA, text=f" {rig.pin} ")).route == "card"
    assert _texts(rig)[-1] == LATE and rig.pins.checks == []
    assert router.handle(rig.message(NUM_RIYA, text="what is the status?")).route == "unhandled"  # not digits
    rig.clock.advance(PIN_WINDOW_S)  # grace over: digits are ordinary text again
    assert router.handle(rig.message(NUM_RIYA, text=rig.pin)).route == "unhandled"


def test_FR_CHN_05_answered_pin_leaves_no_late_capture(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    rig.tap(sent, "approve", card_id=GATE_T3)
    assert rig.text(NUM_RIYA, rig.pin).outcome == "answered"
    assert rig.text(NUM_RIYA, "123456").outcome == "ignored"


# --- send_card failures, retries, closed and malformed cards -----------------------------------------


def _boom(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("dependency down")


def test_FR_CHN_05_send_failure_is_reported_not_raised(rig: CardRig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rig.sender, "send_buttons", _boom)
    result = rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA)
    assert (result.outcome, result.message_id) == ("failed", None)
    assert rig.events.parts == []


@pytest.mark.parametrize(("broken", "method"), [("archive", "record"), ("events", "write")])
def test_FR_CHN_05_record_failure_after_send_never_double_sends(
    rig: CardRig, monkeypatch: pytest.MonkeyPatch, broken: str, method: str
) -> None:
    monkeypatch.setattr(getattr(rig, broken), method, _boom)
    first = rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA)
    assert first.outcome == "sent" and len(rig.sender.cards) == 1
    retry = rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA)
    assert (retry.outcome, retry.message_id) == ("sent", first.message_id)
    assert len(rig.sender.cards) == 1


def test_FR_CHN_05_resending_an_answered_card_does_not_reopen_it(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    assert rig.tap(sent, "per_kwh", card_id=QUESTION).outcome == "answered"
    again = rig.svc.send_card(rig.cards[QUESTION], user_id=RIYA)
    assert (again.outcome, again.message_id) == ("closed", None)
    assert len(rig.sender.cards) == 1
    assert rig.tap(sent, "per_pack", card_id=QUESTION).outcome == "already_answered"


@pytest.mark.parametrize(
    "change", [{"created_at": "yesterday"}, {"created_at": "2026-10-02T09:00:00"}, {"options": None}, {"timeout": "x"}]
)
def test_FR_CHN_05_malformed_card_is_refused_without_raising(rig: CardRig, change: dict[str, Any]) -> None:
    card = make_card(QUESTION, created_at=rig.clock()) | change
    assert rig.svc.send_card(card, user_id=RIYA).outcome == "failed"
    assert rig.sender.cards == [] and rig.events.parts == []


def test_FR_CHN_05_cards_are_evicted_after_their_deadline(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.clock.advance(3600)
    assert rig.tap(sent, "per_pack", card_id=QUESTION).outcome == "expired"
    rig.clock.advance(3600)
    assert rig.tap(sent, "per_pack", card_id=QUESTION).outcome == "unknown_card"
    assert rig.svc.card_closed(QUESTION, channel="timeout") is False


# --- Hold and Edit first leave a gate open (the real API answers them without resolving, #157) --------


def _api_keeps_gates_open(rig: CardRig, monkeypatch: pytest.MonkeyPatch) -> None:
    """Like tilo-api: Hold or Edit first on a gate is answered, but the gate stays open for an Approve."""
    real = rig.api.answer

    def answer(world_id: str, card_id: str, *, option: str, **kw: Any) -> ApiAnswer:
        if rig.cards[card_id].get("gate") and option in ("hold", "edit") and card_id not in rig.api.closed:
            rig.api.calls.append(dict(world_id=world_id, card_id=card_id, option=option, at=rig.clock(), **kw))
            return ApiAnswer("answered")
        return real(world_id, card_id, option=option, **kw)

    monkeypatch.setattr(rig.api, "answer", answer)


@pytest.mark.parametrize(
    ("option", "reply"),
    [
        ("hold", "Held. You can still approve here or in Tilo."),
        ("edit", f"To edit, open it in Tilo: {WEB_URL}/worlds/w_chn05/cards/{GATE_T3}. Nothing was approved."),
    ],
)
def test_FR_CHN_05_hold_or_edit_keeps_the_gate_open_for_a_pin_approve(
    rig: CardRig, monkeypatch: pytest.MonkeyPatch, option: str, reply: str
) -> None:
    _api_keeps_gates_open(rig, monkeypatch)
    sent = rig.send(GATE_T3)
    assert rig.tap(sent, option, card_id=GATE_T3).outcome == "answered"
    assert _texts(rig) == [reply]
    assert rig.tap(sent, "approve", card_id=GATE_T3).outcome == "pin_required"
    assert rig.text(NUM_RIYA, rig.pin).outcome == "answered"
    assert [(c["option"], c["pin_verified"]) for c in rig.api.calls] == [(option, False), ("approve", True)]
    assert rig.api.closed[GATE_T3] == ("approve", "whatsapp")


@pytest.mark.parametrize("option", ["hold", "edit"])
def test_FR_CHN_05_approve_then_hold_or_edit_then_correct_pin_makes_no_approve_call(
    rig: CardRig, monkeypatch: pytest.MonkeyPatch, option: str
) -> None:
    """The person's last choice wins: Hold or Edit first after Approve cancels the PIN prompt."""
    _api_keeps_gates_open(rig, monkeypatch)
    sent = rig.send(GATE_T3)
    assert rig.tap(sent, "approve", card_id=GATE_T3).outcome == "pin_required"
    assert rig.tap(sent, option, card_id=GATE_T3).outcome == "answered"
    assert rig.text(NUM_RIYA, rig.pin).outcome == "pin_late"
    assert [(c["option"], c["pin_verified"]) for c in rig.api.calls] == [(option, False)]
    assert rig.pins.checks == []
    assert rig.tap(sent, "approve", card_id=GATE_T3).outcome == "pin_required"  # a new Approve re-prompts
    assert rig.text(NUM_RIYA, rig.pin).outcome == "answered"


def test_FR_CHN_05_resend_to_another_user_retires_the_old_buttons(rig: CardRig) -> None:
    first = rig.send(QUESTION, user=RIYA)
    rig.send(QUESTION, user=SAM)
    assert rig.tap(first, "per_pack", card_id=QUESTION).outcome == "unknown_card"
    assert rig.api.calls == []
