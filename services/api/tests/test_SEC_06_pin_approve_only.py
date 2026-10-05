"""SEC-06 as amended (PRD supplement 2.1, SD-01, ADR-0019): a gate is answered only in a signed-in
web or mobile-web session, with no PIN. The contract gate cards no longer list whatsapp, so an
answer over it is refused, PIN or not, and writes nothing; CH-RM PR 2 removes the PIN branch.
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
    assert "whatsapp" not in card["answer_channels"]
    writer = FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={card["world_id"]: OWNER})
    store.submit(card, outbox_id=new_ulid("outbox-3"))
    return store, writer, card


def _answer(store: CardStore, card: dict, option: str, channel: str, **kw):
    return store.answer(card["world_id"], card["id"], option=option, channel=channel, principal=OWNER_P, **kw)


@pytest.mark.parametrize("option", ["approve", "hold", "edit"])
@pytest.mark.parametrize("pin_verified", [False, True])
def test_SEC_06_t3_whatsapp_answer_is_refused_pin_or_not(option, pin_verified):
    store, writer, card = _t3_gate()

    result = _answer(store, card, option, "whatsapp", pin_verified=pin_verified)

    assert (result.outcome, result.reason, result.emitted) == ("rejected", "invalid_channel", ())
    assert writer.parts == []


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
