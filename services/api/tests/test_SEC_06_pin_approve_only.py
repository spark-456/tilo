"""SEC-06 (PRD 16.2): a T3 gate answered over WhatsApp needs a verified PIN for the approval only.
Hold and Edit-first write no event and open no gate (CR-07), so they carry no PIN.
"""

from __future__ import annotations

import pytest
from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, load_valid_card, new_ulid
from tilo_api.cards import CardStore

OWNER = "u_owner"
START = "2026-09-29T09:30:00.000Z"


def _t3_gate() -> tuple[CardStore, FakeEventWriter, dict]:
    card = load_valid_card("gate_send_reply")
    assert card["gate"]["risk_tier"] == "T3"
    assert "whatsapp" in card["answer_channels"]
    writer = FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={card["world_id"]: OWNER})
    store.submit(card, outbox_id=new_ulid("outbox-3"))
    return store, writer, card


def _answer(store: CardStore, card: dict, option: str, channel: str, **kw):
    return store.answer(card["world_id"], card["id"], option=option, channel=channel, principal=OWNER_P, **kw)


def test_SEC_06_t3_whatsapp_approve_without_a_pin_is_rejected():
    store, writer, card = _t3_gate()

    result = _answer(store, card, "approve", "whatsapp")

    assert (result.outcome, result.reason, result.emitted) == ("rejected", "pin_required", ())
    assert writer.parts == []


def test_SEC_06_t3_whatsapp_approve_with_a_pin_writes_approval_resolved():
    store, writer, card = _t3_gate()

    result = _answer(store, card, "approve", "whatsapp", pin_verified=True)

    assert result.outcome == "answered"
    resolved = writer.of_type("approval.resolved")
    assert len(resolved) == 1
    assert resolved[0]["data"]["pin_verified"] is True


def test_SEC_06_t3_whatsapp_wrong_pin_is_still_pin_required():
    """A wrong PIN arrives as pin_verified=False: the same rejection as no PIN, nothing written."""
    store, writer, card = _t3_gate()

    result = _answer(store, card, "approve", "whatsapp", pin_verified=False)

    assert (result.outcome, result.reason) == ("rejected", "pin_required")
    assert writer.parts == []


@pytest.mark.parametrize("option", ["hold", "edit"])
def test_SEC_06_t3_whatsapp_hold_and_edit_need_no_pin_and_write_no_approval(option):
    store, writer, card = _t3_gate()
    assert option in {o["id"] for o in card["options"]}

    result = _answer(store, card, option, "whatsapp")

    assert (result.outcome, result.reason, result.emitted) == ("answered", None, ())
    assert writer.of_type("approval.resolved") == []
    assert writer.parts == []


@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_SEC_06_non_whatsapp_channels_are_unchanged(channel):
    store, writer, card = _t3_gate()
    if channel not in card["answer_channels"]:
        pytest.skip(f"{channel} is not an answer channel of this card")

    hold = _answer(store, card, "hold", channel)
    approve = _answer(store, card, "approve", channel)

    assert hold.outcome == "answered"
    assert approve.outcome == "answered"
    assert len(writer.of_type("approval.resolved")) == 1
    assert writer.of_type("approval.resolved")[0]["data"]["pin_verified"] is False
