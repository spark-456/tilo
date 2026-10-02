"""FR-CHN-05 acceptance: "Cards as interactive WhatsApp messages; answers sync to all channels" (PRD
11.6). Acceptance test: "Answer on WhatsApp; the web card closes in <= 2 s" (also FR-HIL-11: "The same
card answered on WhatsApp updates the web in <= 2 s").

PRD 10.3 "One card, every channel": WhatsApp renders an "interactive message with up to 3 reply buttons;
longer content links to the web", "only from the user's verified, bound number". Card rules: every card
has a timeout and a safe default. PRD 18.4: at most 3 buttons; every automated send confirmed with a
one-line receipt. Contracts: card.schema.json (labels <= 20 characters "so it fits a WhatsApp reply
button"; gate labels fixed, CR-07; answer_channels per kind), channel.message_in / channel.message_out
(never the body, message_ref into the archive; option from the button payload). The web card closes when
tilo-api records the answer (services/api CardStore.answer, first answer wins), so the server-side
<= 2 s is: from the tap reaching tilo-channels to the API call that closes the card.

Public interface: `tilo_channels.cards.WhatsAppCards` (API_FR_CHN_03_05.md), driven through fakes. The
module does not exist yet, so every test fails with ModuleNotFoundError when the rig is built.
"""

from __future__ import annotations

import re
import time

import pytest
from _chn_0305_lib import (
    CONSENT,
    GATE_T1,
    GATE_T3,
    KAI,
    MEETING,
    NUM_RIYA,
    QUESTION,
    RIYA,
    WEB_URL,
    CardRig,
    card_errors,
    data_errors,
    make_card,
    registered_types,
)

_REF = re.compile(r"^r_chn05_1/[0-9]{1,9}$")


@pytest.fixture()
def rig() -> CardRig:
    return CardRig()


def _texts(rig: CardRig, number: str = NUM_RIYA) -> list[str]:
    return rig.sender.texts_to(number)


# --- rendering ------------------------------------------------------------------------------------


def test_FR_CHN_05_fixture_cards_are_contract_valid(rig: CardRig) -> None:
    for card in rig.cards.values():
        assert card_errors(card) == []


def test_FR_CHN_05_gate_card_sent_as_interactive_message_with_fixed_labels(rig: CardRig) -> None:
    sent = rig.send(GATE_T3)
    card = rig.cards[GATE_T3]
    assert sent["to"] == NUM_RIYA
    assert [t for _, t in sent["buttons"]] == ["Approve", "Edit first", "Hold"]  # CR-07, WhatsApp shows labels
    ids = [i for i, _ in sent["buttons"]]
    assert len(set(ids)) == len(ids)
    for button_id in ids:
        assert isinstance(button_id, str) and 0 < len(button_id) <= 256  # Meta's reply-button id limit
        assert NUM_RIYA not in button_id and NUM_RIYA[-7:] not in button_id
    assert card["what_happened"] in sent["body"]
    assert WEB_URL in sent["body"]  # "longer content links to the web"
    assert rig.sender.texts == []  # one message, not a text plus a card


@pytest.mark.parametrize("card_id", [GATE_T1, QUESTION, MEETING])
def test_FR_CHN_05_one_reply_button_per_option_at_most_three(rig: CardRig, card_id: str) -> None:
    sent = rig.send(card_id)
    labels = [o["label"] for o in rig.cards[card_id]["options"]]
    assert [t for _, t in sent["buttons"]] == labels
    assert 1 <= len(sent["buttons"]) <= 3
    assert all(len(t) <= 20 for _, t in sent["buttons"])


def test_FR_CHN_05_consent_card_is_never_sent_on_whatsapp(rig: CardRig) -> None:
    result = rig.svc.send_card(rig.cards[CONSENT], user_id=RIYA)  # answer_channels: web, mobile_web
    assert result.outcome == "not_whatsapp" and result.message_id is None
    assert rig.sender.cards == [] and rig.sender.texts == []
    assert rig.events.parts == []


def test_FR_CHN_05_card_not_sent_to_unbound_user(rig: CardRig) -> None:
    result = rig.svc.send_card(rig.cards[QUESTION], user_id=KAI)
    assert result.outcome == "not_bound" and result.message_id is None
    assert rig.sender.cards == [] and rig.sender.texts == []


def test_FR_CHN_05_timed_out_card_is_not_sent(rig: CardRig) -> None:
    card = make_card(QUESTION, created_at=rig.clock() - 3601, timeout=3600)
    result = rig.svc.send_card(card, user_id=RIYA)
    assert result.outcome == "expired"
    assert rig.sender.cards == []


def test_FR_CHN_05_sending_a_card_records_channel_message_out(rig: CardRig) -> None:
    rig.send(GATE_T3)
    parts = rig.events.of_type("channel.message_out")
    assert len(parts) == 1
    part = parts[0]
    assert "channel.message_out" in registered_types()
    assert part["world_id"] == "w_chn05" and part["run_id"] == "r_chn05_1"
    assert part["authz"] is None
    assert data_errors("channel.message_out", part["data"]) == []
    assert part["data"]["channel"] == "whatsapp" and part["data"]["card_id"] == GATE_T3
    assert _REF.match(part["data"]["message_ref"])


# --- answering on WhatsApp closes the web card ------------------------------------------------------


def test_FR_CHN_05_answer_on_whatsapp_closes_web_card_within_2s(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    tapped_at = rig.clock()
    started = time.monotonic()
    result = rig.tap(sent, "per_pack", card_id=QUESTION)
    wall = time.monotonic() - started
    assert result.outcome == "answered" and result.card_id == QUESTION and result.option == "per_pack"
    accepted = rig.api.accepted()
    assert len(accepted) == 1
    call = accepted[0]
    assert (call["world_id"], call["card_id"], call["option"]) == ("w_chn05", QUESTION, "per_pack")
    assert (call["user_id"], call["channel"], call["pin_verified"]) == (RIYA, "whatsapp", False)
    assert call["at"] - tapped_at <= 2.0  # the API closes the web card on this call (PRD 11.6: <= 2 s)
    assert rig.api.closed[QUESTION] == ("per_pack", "whatsapp")
    assert wall < 2.0


def test_FR_CHN_05_answer_confirmed_once_after_the_api_accepted(rig: CardRig) -> None:
    sent = rig.send(MEETING)
    rig.tap(sent, "even", card_id=MEETING)
    receipts = [(b, at) for (to, b, at) in rig.sender.texts if to == NUM_RIYA]
    assert len(receipts) == 1  # one-line receipt (PRD 18.4)
    assert receipts[0][1] >= rig.api.accepted()[0]["at"]  # never confirmed before it happened (HR-1)
    assert "\n" not in receipts[0][0].strip()


def test_FR_CHN_05_answer_records_channel_message_in(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.tap(sent, "per_kwh", card_id=QUESTION)
    parts = rig.events.of_type("channel.message_in")
    assert len(parts) == 1
    part = parts[0]
    assert "channel.message_in" in registered_types()
    assert part["actor"] == RIYA  # the bound user, looked up after the signature check
    assert part["authz"] is None and part["world_id"] == "w_chn05" and part["run_id"] == "r_chn05_1"
    assert data_errors("channel.message_in", part["data"]) == []
    data = part["data"]
    assert (data["channel"], data["card_id"], data["card_kind"], data["option"]) == (
        "whatsapp",
        QUESTION,
        "needs_you",
        "per_kwh",
    )
    assert data["destination"] is None
    assert _REF.match(data["message_ref"])


def test_FR_CHN_05_gate_answer_records_the_gate_destination(rig: CardRig) -> None:
    sent = rig.send(GATE_T1)
    assert rig.tap(sent, "approve", card_id=GATE_T1).outcome == "answered"
    [part] = rig.events.of_type("channel.message_in")
    assert data_errors("channel.message_in", part["data"]) == []
    assert part["data"]["card_kind"] == "gate" and part["data"]["option"] == "approve"
    assert part["data"]["destination"] == rig.cards[GATE_T1]["gate"]["action"]["destination"]


def test_FR_CHN_05_channels_writes_only_registered_types_and_never_authorises(rig: CardRig) -> None:
    for card_id, option in ((QUESTION, "per_pack"), (GATE_T1, "approve"), (MEETING, "research")):
        rig.tap(rig.send(card_id), option, card_id=card_id)
    types = {p["type"] for p in rig.events.parts}
    assert types <= registered_types()
    # question.answered and approval.resolved are written by tilo-api when it accepts the answer
    # (services/api CardStore.answer); a second copy from tilo-channels would double the world effect.
    assert types <= {"channel.message_in", "channel.message_out"}
    assert all(p["authz"] is None for p in rig.events.parts)


def test_FR_CHN_05_no_number_in_events_or_archive(rig: CardRig) -> None:
    rig.tap(rig.send(GATE_T1), "approve", card_id=GATE_T1)
    for blob in (rig.events.dump(), rig.archive.dump()):
        assert NUM_RIYA not in blob and NUM_RIYA[-7:] not in blob


# --- answers from elsewhere close the WhatsApp card ---------------------------------------------------


def test_FR_CHN_05_answer_on_web_closes_the_whatsapp_card(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.api.close_elsewhere(QUESTION, "per_kwh", "web")
    assert rig.svc.card_closed(QUESTION, channel="web") is True
    notices = _texts(rig)
    assert len(notices) == 1 and len(notices[0]) <= 200
    result = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert result.outcome == "already_answered"
    assert rig.api.accepted() == []
    assert len(_texts(rig)) == 2  # one short reply to the late tap


def test_FR_CHN_05_card_closed_is_idempotent(rig: CardRig) -> None:
    rig.send(QUESTION)
    assert rig.svc.card_closed(QUESTION, channel="mobile_web") is True
    assert rig.svc.card_closed(QUESTION, channel="mobile_web") is False
    assert rig.svc.card_closed(QUESTION, channel="email") is False
    assert len(_texts(rig)) == 1


def test_FR_CHN_05_card_closed_after_whatsapp_answer_sends_nothing_more(rig: CardRig) -> None:
    rig.tap(rig.send(QUESTION), "per_pack", card_id=QUESTION)
    before = len(_texts(rig))
    assert rig.svc.card_closed(QUESTION, channel="whatsapp") is False
    assert len(_texts(rig)) == before


def test_FR_CHN_05_card_closed_for_unknown_or_unsent_card_sends_nothing(rig: CardRig) -> None:
    assert rig.svc.card_closed("01JC00000000000000000000ZZ", channel="web") is False
    assert rig.svc.card_closed(MEETING, channel="web") is False  # never sent on WhatsApp
    assert rig.sender.texts == []


def test_FR_CHN_05_timeout_closes_the_whatsapp_card(rig: CardRig) -> None:
    rig.send(GATE_T3)
    assert rig.svc.card_closed(GATE_T3, channel="timeout") is True
    assert len(_texts(rig)) == 1


def test_FR_CHN_05_closing_notice_never_goes_to_a_number_no_longer_bound(rig: CardRig) -> None:
    rig.send(QUESTION)
    del rig.bindings.by_number[NUM_RIYA]
    rig.svc.card_closed(QUESTION, channel="web")
    assert _texts(rig) == []


def test_FR_CHN_05_web_answer_wins_even_if_close_notice_is_late(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.api.close_elsewhere(QUESTION, "per_kwh", "web")  # no card_closed yet: the notice is in flight
    result = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert result.outcome == "already_answered"
    assert rig.api.closed[QUESTION] == ("per_kwh", "web")
    assert len(_texts(rig)) == 1


# --- first answer wins, replays, stale cards -------------------------------------------------------------


def test_FR_CHN_05_first_answer_wins_on_double_tap(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    first = rig.tap(sent, "per_kwh", card_id=QUESTION)
    second = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert first.outcome == "answered" and second.outcome == "already_answered"
    assert [c["option"] for c in rig.api.accepted()] == ["per_kwh"]


def test_FR_CHN_05_same_message_handled_twice_answers_once(rig: CardRig) -> None:
    sent = rig.send(MEETING)
    button_id, _ = sent["buttons"][0]
    message = rig.message(NUM_RIYA, kind="interactive", button_id=button_id, context_id=sent["message_id"])
    rig.svc.handle(message)
    again = rig.svc.handle(message)
    assert again.outcome in ("already_answered", "ignored")
    assert len(rig.api.accepted()) == 1


def test_FR_CHN_05_tap_after_timeout_is_refused(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.clock.advance(3600)  # created_at + timeout: the safe default applies, not the tap
    result = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert result.outcome == "expired"
    assert rig.api.calls == []
    assert len(_texts(rig)) == 1


def test_FR_CHN_05_api_failure_is_not_confirmed_and_card_stays_answerable(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.api.fail_next = ConnectionError("tilo-api unreachable")
    result = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert result.outcome == "failed"
    assert len(_texts(rig)) == 1
    retry = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert retry.outcome == "answered"
    assert len(rig.api.accepted()) == 1


def test_FR_CHN_05_api_rejection_is_reported_not_confirmed(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    rig.api.reject_with = "forbidden"  # e.g. a Viewer's number (PRD 10.1: Viewers answer nothing)
    result = rig.tap(sent, "per_pack", card_id=QUESTION)
    assert result.outcome == "rejected"
    assert len(_texts(rig)) == 1


def test_FR_CHN_05_unknown_button_is_refused(rig: CardRig) -> None:
    rig.send(QUESTION)
    forged = rig.message(NUM_RIYA, kind="interactive", button_id="not-a-tilo-button", context_id=None)
    result = rig.svc.handle(forged)
    assert result.outcome == "unknown_card"
    assert rig.api.calls == []
    assert len(_texts(rig)) == 1


def test_FR_CHN_05_typed_text_never_answers_a_card(rig: CardRig) -> None:
    """BQ-56, CR-07: the tap on a labelled button is the answer; typed words are never an option."""
    gate = rig.send(GATE_T1)
    question = rig.send(QUESTION)
    for body in ("yes", "Approve", "approve", "APPROVE", "ok", "1", "Hold", "per_pack", "Compare per pack", "👍"):
        for sent in (gate, question):
            rig.text(NUM_RIYA, body, context_id=sent["message_id"])
            rig.text(NUM_RIYA, body)
    assert rig.api.calls == []


def test_FR_CHN_05_cards_ignore_unbound_senders(rig: CardRig) -> None:
    sent = rig.send(QUESTION)
    button_id, _ = sent["buttons"][0]
    result = rig.svc.handle(rig.message("12025550188", kind="interactive", button_id=button_id))
    assert result.outcome == "ignored"
    assert rig.api.calls == [] and rig.sender.texts == []  # the router sends the opt-in text (FR-CHN-03)
