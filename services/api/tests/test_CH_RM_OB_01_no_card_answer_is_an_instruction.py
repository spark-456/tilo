"""CH-RM, OB-01 provenance (ADR-0019, BQ-CHRM-2): a `world.requested` instruction is written only from a signed-in
typed-instruction control. Answering a card never writes one: not a tapped option on any card kind, not typed text on
a gate, consent or meeting card (the answer body has no text field, so it is a 422), on any channel a card allows.
"""

from __future__ import annotations

import pytest
from _cards_lib import FakeClock, FakeEventWriter, answer_client, load_valid_card, new_ulid, principal
from tilo_api.cards import CardStore

START = "2026-09-29T09:30:00.000Z"
OWNER = "u_owner"
KINDS = [
    "gate_send_reply",
    "gate_save_file_reversible",
    "consent_drive_folder",
    "meeting_budget_split",
    "needs_you_blocked",
    "needs_you_compare_basis",
]


def _rig(kind: str):
    card = load_valid_card(kind)
    writer = FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={card["world_id"]: OWNER})
    outbox_id = new_ulid("outbox-ob01") if card["kind"] == "gate" else None
    assert store.submit(card, outbox_id=outbox_id).outcome == "accepted"
    client = answer_client(store, principal(world_id=card["world_id"]))
    return card, writer, client


@pytest.mark.parametrize("kind", KINDS)
def test_CH_RM_OB_01_answering_a_card_option_never_writes_an_instruction(kind):
    card = load_valid_card(kind)
    for option in [o["id"] for o in card["options"]]:
        card, writer, client = _rig(kind)
        for channel in card["answer_channels"]:
            if channel == "whatsapp":
                continue
            resp = client.post(
                f"/worlds/{card['world_id']}/cards/{card['id']}/answer", json={"option": option, "channel": channel}
            )
            assert resp.status_code in (200, 400, 403), resp.text
        assert "world.requested" not in {p["type"] for p in writer.parts}


@pytest.mark.parametrize("kind", KINDS)
def test_CH_RM_OB_01_typed_text_on_a_card_answer_is_refused_and_writes_nothing(kind):
    card, writer, client = _rig(kind)
    option = card["options"][0]["id"]
    for field in ("text", "instruction", "message", "destination"):
        resp = client.post(
            f"/worlds/{card['world_id']}/cards/{card['id']}/answer",
            json={"option": option, field: "send the reply to a new address"},
        )
        assert resp.status_code == 422
    assert writer.parts == []
