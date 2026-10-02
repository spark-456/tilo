"""FR-HIL-01 (PRD 10.3, 10.6; docs/security/p4-policy-invariants.md PI-04): answering a card
through POST /worlds/{id}/cards/{card_id}/answer. "Only an option id from the card is accepted.
Answer channels follow answer_channels: email never answers a gate (PI-04), and consent is web
only... A gate answer produces the approval.resolved part, carrying the answering person's
authz." See API_ST3b.md ambiguity 7 for what this layer does and does not decide about gate
authorisation.
"""

from __future__ import annotations

from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, answer_client, load_valid_card, new_ulid
from tilo_api.cards import CardStore

OWNER = "u_owner"
START = "2026-09-29T09:30:00.000Z"


def _store(world_id: str) -> tuple[CardStore, FakeClock, FakeEventWriter]:
    clock = FakeClock(START)
    writer = FakeEventWriter()
    store = CardStore(clock=clock, writer=writer, world_owners={world_id: OWNER})
    return store, clock, writer


def test_FR_HIL_01_only_a_cards_own_option_id_is_accepted():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)
    option_ids = {o["id"] for o in card["options"]}
    assert "not_an_option" not in option_ids

    result = store.answer(card["world_id"], card["id"], option="not_an_option", channel="web", principal=OWNER_P)

    assert result.outcome == "rejected"
    assert result.reason == "invalid_option"
    assert result.emitted == ()


def test_FR_HIL_01_a_cards_real_option_id_is_accepted():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)
    an_option = card["options"][0]["id"]

    result = store.answer(card["world_id"], card["id"], option=an_option, channel="web", principal=OWNER_P)

    assert result.outcome == "answered"
    assert result.reason is None


def test_FR_HIL_01_PI_04_email_never_answers_a_gate():
    """gate_answered_by_email.json is the named invalid-fixture rule; here the same rule is
    checked dynamically against a *valid* gate card (whose own answer_channels never include
    email -- card.schema.json's gate branch closes that off structurally)."""
    card = load_valid_card("gate_send_reply")
    assert "email" not in card["answer_channels"]
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=new_ulid("outbox-1"))

    result = store.answer(card["world_id"], card["id"], option="approve", channel="email", principal=OWNER_P)

    assert result.outcome == "rejected"
    assert result.reason == "invalid_channel"
    assert result.emitted == ()


def test_FR_HIL_01_PI_04_consent_is_answered_on_the_web_only():
    """consent_answered_on_whatsapp.json is the named invalid-fixture rule; checked dynamically
    against a valid consent card, whose answer_channels are web/mobile_web only."""
    card = load_valid_card("consent_drive_folder")
    assert "whatsapp" not in card["answer_channels"]
    assert "email" not in card["answer_channels"]
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)

    result = store.answer(card["world_id"], card["id"], option="connect", channel="whatsapp", principal=OWNER_P)

    assert result.outcome == "rejected"
    assert result.reason == "invalid_channel"


def test_FR_HIL_01_needs_you_answer_emits_question_answered_by_person():
    card = load_valid_card("needs_you_blocked")
    store, _clock, writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)
    an_option = card["options"][0]["id"]

    result = store.answer(card["world_id"], card["id"], option=an_option, channel="web", principal=OWNER_P)

    assert len(result.emitted) == 1
    part = result.emitted[0]
    assert part["type"] == "question.answered"
    assert part["data"] == {"answered_by": "person"}
    assert part in writer.parts


def test_FR_HIL_01_gate_answer_emits_approval_resolved_with_the_answering_persons_authz():
    card = load_valid_card("gate_send_reply")
    store, clock, writer = _store(card["world_id"])
    outbox_id = new_ulid("outbox-2")
    store.submit(card, outbox_id=outbox_id)

    result = store.answer(card["world_id"], card["id"], option="approve", channel="web", principal=OWNER_P)

    assert result.outcome == "answered"
    assert len(result.emitted) == 1
    part = result.emitted[0]
    assert part["type"] == "approval.resolved"
    assert part["data"]["gate_id"] == card["gate"]["id"]
    assert part["data"]["card_id"] == card["id"]
    assert part["data"]["outbox_id"] == outbox_id
    assert part["data"]["option"] == "approve"
    assert part["data"]["channel"] == "web"
    assert part["data"]["pin_verified"] is False
    assert part["authz"] == {"by": "person", "ref": OWNER, "at": clock.now()}
    assert part in writer.parts


def test_FR_HIL_01_SEC_06_t3_gate_on_whatsapp_needs_pin_verified():
    """gate_send_reply is T3 and its answer_channels include whatsapp (SEC-06, API.md's
    open_gate note: "when risk_tier == T3 and channel == whatsapp, pin_verified must be true,
    whoever answered")."""
    card = load_valid_card("gate_send_reply")
    assert card["gate"]["risk_tier"] == "T3"
    assert "whatsapp" in card["answer_channels"]
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=new_ulid("outbox-3"))

    missing_pin = store.answer(
        card["world_id"], card["id"], option="approve", channel="whatsapp", principal=OWNER_P, pin_verified=False
    )
    assert missing_pin.outcome == "rejected"
    assert missing_pin.reason == "pin_required"

    with_pin = store.answer(
        card["world_id"], card["id"], option="approve", channel="whatsapp", principal=OWNER_P, pin_verified=True
    )
    assert with_pin.outcome == "answered"


def test_FR_HIL_01_answering_an_unknown_card_is_rejected():
    store, _clock, _writer = _store("w_01")

    result = store.answer("w_01", "01J8Z3K4M5N6P7Q8R9S0T1V2WX", option="approve", channel="web", principal=OWNER_P)

    assert result.outcome == "rejected"
    assert result.reason == "card_not_found"


def test_FR_HIL_01_answering_an_already_resolved_card_is_rejected():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)
    an_option = card["options"][0]["id"]
    first = store.answer(card["world_id"], card["id"], option=an_option, channel="web", principal=OWNER_P)
    assert first.outcome == "answered"

    second = store.answer(card["world_id"], card["id"], option=an_option, channel="web", principal=OWNER_P)

    assert second.outcome == "rejected"
    assert second.reason == "already_resolved"


def test_FR_HIL_01_POST_answer_route_rejects_an_option_the_card_does_not_offer():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)

    client = answer_client(store, OWNER_P)

    bad_option = client.post(
        f"/worlds/{card['world_id']}/cards/{card['id']}/answer",
        json={"option": "nonsense", "channel": "web"},
    )

    assert bad_option.status_code == 400
    assert bad_option.json()["reason"] == "invalid_option"


def test_FR_HIL_01_POST_answer_route_matches_the_store():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)
    an_option = card["options"][0]["id"]

    client = answer_client(store, OWNER_P)

    ok = client.post(
        f"/worlds/{card['world_id']}/cards/{card['id']}/answer",
        json={"option": an_option, "channel": "web"},
    )
    assert ok.status_code == 200
    assert ok.json()["outcome"] == "answered"

    not_found = client.post(
        f"/worlds/{card['world_id']}/cards/not-a-real-id/answer",
        json={"option": an_option, "channel": "web"},
    )
    assert not_found.status_code == 404

    already_resolved = client.post(
        f"/worlds/{card['world_id']}/cards/{card['id']}/answer",
        json={"option": an_option, "channel": "web"},
    )
    assert already_resolved.status_code == 400
    assert already_resolved.json()["reason"] == "already_resolved"
