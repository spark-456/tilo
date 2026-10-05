"""SEC-06 as amended (PRD supplement 2.1, SD-01, ADR-0019): a gate is answered only in a signed-in
web or mobile-web session, with no PIN. An answer over whatsapp is refused and writes nothing,
whatever the card lists: the store has no PIN path and fails closed on the channel (CH-RM).
"""

from __future__ import annotations

import pytest
from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, load_valid_card, new_ulid, principal
from tilo_api.cards import CardStore

OWNER = "u_owner"
START = "2026-09-29T09:30:00.000Z"


def _t3_gate() -> tuple[CardStore, FakeEventWriter, dict]:
    card = load_valid_card("gate_send_reply")
    assert card["gate"]["risk_tier"] == "T3"
    assert "whatsapp" not in card["answer_channels"]
    writer = FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={card["world_id"]: OWNER})
    store.submit(card, outbox_id=new_ulid("outbox-3"))
    return store, writer, card


def _answer(store: CardStore, card: dict, option: str, channel: str, **kw):
    return store.answer(card["world_id"], card["id"], option=option, channel=channel, principal=OWNER_P, **kw)


@pytest.mark.parametrize("option", ["approve", "hold", "edit"])
def test_SEC_06_t3_whatsapp_answer_is_refused(option):
    store, writer, card = _t3_gate()

    result = _answer(store, card, option, "whatsapp")

    assert (result.outcome, result.reason, result.emitted) == ("rejected", "invalid_channel", ())
    assert writer.parts == []


@pytest.mark.parametrize("kind", ["gate_send_reply", "gate_save_file_reversible", "needs_you_compare_basis"])
def test_CH_RM_SEC_06_a_card_that_still_lists_whatsapp_never_opens_on_a_whatsapp_answer(kind):
    """A stored card (an old run) may list whatsapp, a valid enum value: the store still refuses the answer, whatever
    the tier, and the card stays open so a signed-in answer resolves it (no stuck run)."""
    card = load_valid_card(kind)
    card["answer_channels"] = [*card["answer_channels"], "whatsapp"]
    writer = FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={card["world_id"]: OWNER})
    gate = card["kind"] == "gate"
    assert store.submit(card, outbox_id=new_ulid("outbox-4") if gate else None).outcome == "accepted"
    option = "approve" if gate else card["options"][0]["id"]
    owner = principal(world_id=card["world_id"])

    def answer(channel: str):
        return store.answer(card["world_id"], card["id"], option=option, channel=channel, principal=owner)

    refused = answer("whatsapp")

    assert (refused.outcome, refused.reason, refused.emitted) == ("rejected", "invalid_channel", ())
    assert writer.parts == []
    assert answer("web").outcome == "answered"
    assert len(writer.parts) == 1


@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_SEC_06_signed_in_channels_answer_without_a_pin(channel):
    store, writer, card = _t3_gate()
    assert channel in card["answer_channels"]

    hold = _answer(store, card, "hold", channel)
    approve = _answer(store, card, "approve", channel)

    assert hold.outcome == "answered"
    assert approve.outcome == "answered"
    assert len(writer.of_type("approval.resolved")) == 1
    assert writer.of_type("approval.resolved")[0]["data"]["pin_verified"] is False
