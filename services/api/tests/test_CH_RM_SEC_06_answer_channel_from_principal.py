"""CH-RM follow-ups (issue #388 items 1 and 2), SEC-06 as amended (SD-01, ADR-0019): a user's answer takes its channel
class from the authenticated principal, never from the request body: a web or mobile web session records either (one
signed-in session), and nothing else. A session of another class is refused before anything is resolved, closed or
written. A tilo-channels caller may claim only email, and only on a needs_you card; it never opens a gate. And `submit`
never stores a card nobody can answer.
"""

from __future__ import annotations

import pytest
from _cards_lib import FakeClock, FakeEventWriter, answer_client, load_valid_card, new_ulid, principal
from tilo_api.cards import CardStore

W = "w_01"
START = "2026-09-29T09:30:00.000Z"


def _store() -> tuple[CardStore, FakeEventWriter]:
    writer = FakeEventWriter()
    return CardStore(clock=FakeClock(START), writer=writer, world_owners={W: "u_owner"}), writer


def _card(store: CardStore, fixture: str) -> dict:
    card = load_valid_card(fixture)
    assert store.submit(card, outbox_id=new_ulid("ob") if card["kind"] == "gate" else None).outcome == "accepted"
    return card


def _post(client, card: dict, channel: str, option: str = "approve"):
    return client.post(f"/worlds/{W}/cards/{card['id']}/answer", json={"option": option, "channel": channel})


def _refused(resp) -> bool:
    return (resp.status_code, resp.json()) == (400, {"outcome": "rejected", "reason": "invalid_channel"})


@pytest.mark.parametrize(("session", "claimed"), [("web", "mobile_web"), ("mobile_web", "web"), ("web", "web")])
def test_CH_RM_SEC_06_a_signed_in_session_records_either_web_channel(session, claimed):
    """web and mobile_web are one signed-in session class (policy SIGNED_IN): a phone window on a dev-style principal
    (no channel, so web) records mobile_web, and nothing else is accepted from it."""
    store, writer = _store()
    card = _card(store, "gate_send_reply")

    assert _post(answer_client(store, principal(channel=session)), card, claimed).status_code == 200
    assert [p["data"]["channel"] for p in writer.of_type("approval.resolved")] == [claimed]


def test_CH_RM_SEC_06_the_dev_principal_with_no_channel_answers_on_mobile_web():
    from tilo_api.deps import Principal

    store, writer = _store()
    card = _card(store, "gate_send_reply")
    dev = Principal(user_id="u_owner", role="owner", world_id=W)  # as tilo_api.dev builds it

    assert _post(answer_client(store, dev), card, "mobile_web").status_code == 200
    assert [p["data"]["channel"] for p in writer.of_type("approval.resolved")] == ["mobile_web"]


@pytest.mark.parametrize("claimed", ["email", "whatsapp", "sms", ""])
@pytest.mark.parametrize("session", ["web", "mobile_web"])
def test_CH_RM_SEC_06_a_signed_in_session_never_records_another_channel(session, claimed):
    store, writer = _store()
    card = _card(store, "needs_you_blocked")
    client = answer_client(store, principal(channel=session))

    assert _post(client, card, claimed, card["options"][0]["id"]).status_code in (400, 403)
    assert writer.parts == []
    assert _post(client, card, session, card["options"][0]["id"]).status_code == 200  # the card stayed open


@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_CH_RM_SEC_06_a_signed_in_answer_on_the_session_channel_is_accepted(channel):
    store, writer = _store()
    card = _card(store, "gate_send_reply")

    assert _post(answer_client(store, principal(channel=channel)), card, channel).status_code == 200
    assert [p["data"]["channel"] for p in writer.of_type("approval.resolved")] == [channel]


def test_CH_RM_SEC_06_a_session_whose_channel_is_not_web_never_answers_without_the_channels_service():
    store, writer = _store()
    card = _card(store, "needs_you_blocked")
    option = card["options"][0]["id"]
    client = answer_client(store, principal(channel="email"))  # not from tilo-channels

    assert _post(client, card, "email", option).status_code == 403  # channel_not_permitted, as before
    assert _refused(_post(client, card, "web", option))  # an email session is not a signed-in web session
    assert writer.parts == []


def test_CH_RM_SEC_06_tilo_channels_may_claim_email_on_a_needs_you_card():
    store, writer = _store()
    card = _card(store, "needs_you_blocked")
    client = answer_client(store, principal(channel="email"), from_channels=True)

    assert _post(client, card, "email", card["options"][0]["id"]).status_code == 200
    assert [p["type"] for p in writer.parts] == ["question.answered"]


@pytest.mark.parametrize("claimed", ["web", "mobile_web", "whatsapp"])
def test_CH_RM_SEC_06_tilo_channels_may_claim_nothing_but_email(claimed):
    store, writer = _store()
    card = _card(store, "needs_you_blocked")
    client = answer_client(store, principal(channel="email"), from_channels=True)

    assert _refused(_post(client, card, claimed, card["options"][0]["id"]))
    assert writer.parts == []


def test_CH_RM_SEC_06_tilo_channels_cannot_claim_email_for_a_web_session():
    store, writer = _store()
    card = _card(store, "needs_you_blocked")
    client = answer_client(store, principal(channel="web"), from_channels=True)

    assert _refused(_post(client, card, "email", card["options"][0]["id"]))
    assert writer.parts == []


@pytest.mark.parametrize("fixture", ["gate_send_reply", "gate_save_file_reversible", "consent_drive_folder"])
def test_CH_RM_SEC_06_tilo_channels_never_opens_a_gate_or_consent(fixture):
    store, writer = _store()
    card = _card(store, fixture)
    option = "connect" if card["kind"] == "consent" else "approve"
    client = answer_client(store, principal(channel="email"), from_channels=True)

    assert _refused(_post(client, card, "email", option))
    assert writer.parts == []
    assert [c["id"] for c in store.list_for_world(W, principal=principal())] == [card["id"]]  # still open


def test_CH_RM_SEC_06_the_store_refuses_email_on_a_gate_even_if_a_stored_card_lists_it():
    store, writer = _store()
    card = _card(store, "gate_send_reply")
    store._records[W][card["id"]].card["answer_channels"].append("email")  # a record from an older run

    result = store.answer(W, card["id"], option="approve", channel="email", principal=principal(channel="email"))

    assert (result.outcome, result.reason) == ("rejected", "invalid_channel")
    assert writer.parts == []


# -- submit never stores a card nobody can answer (item 2) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "channels"),
    [
        ("gate_send_reply", ["whatsapp"]),
        ("gate_save_file_reversible", ["whatsapp"]),
        ("needs_you_blocked", ["whatsapp"]),
        ("meeting_budget_split", ["whatsapp"]),
    ],
)
def test_CH_RM_SEC_06_submit_refuses_a_card_with_no_channel_that_can_answer_it(fixture, channels):
    store, writer = _store()
    card = load_valid_card(fixture)
    card["answer_channels"] = channels

    result = store.submit(card, outbox_id=new_ulid("ob") if card["kind"] == "gate" else None)

    assert (result.outcome, result.card_id) == ("rejected", None)
    assert any("answer_channels" in e for e in result.errors)
    assert store.list_for_world(W, principal=principal()) == []
    assert writer.parts == []


def test_CH_RM_SEC_06_submit_still_accepts_a_card_that_lists_whatsapp_beside_a_web_channel():
    store, _writer = _store()
    card = load_valid_card("gate_send_reply")
    card["answer_channels"] = ["web", "whatsapp"]

    assert store.submit(card, outbox_id=new_ulid("ob")).outcome == "accepted"


def test_CH_RM_SEC_06_submit_accepts_an_email_only_needs_you_card():
    store, _writer = _store()
    card = load_valid_card("needs_you_blocked")
    card["answer_channels"] = ["email"]

    assert store.submit(card).outcome == "accepted"
