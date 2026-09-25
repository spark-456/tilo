"""FR-HIL-01 (PRD 10.2, 10.3, 10.6): "the API serves and answers cards that validate against
contracts/card.schema.json and the CR rules" (contracts/card.rules.md). This file covers intake
(CardStore.submit) and the owner's listing (GET /worlds/{id}/cards); answering is in
test_FR_HIL_01_answering.py. See API_ST3b.md for the pinned shapes and the ambiguities this
ticket resolved (district == header.building, outbox_id on gate cards, "for the owner").

tilo_api.cards does not exist yet, so every test below fails at collection with
ModuleNotFoundError until a builder ships it -- that is the "fail for the right reason" this
ticket asks for.
"""

from __future__ import annotations

import pytest
from _cards_lib import (
    FakeClock,
    FakeEventWriter,
    card_errors,
    clone_card,
    fixtures_dir,
    invalid_card_fixture_cases,
    load_json,
    load_valid_card,
    new_ulid,
    valid_card_fixture_cases,
)
from tilo_api.cards import CardStore

OWNER = "u_owner"
OTHER = "u_someone_else"
START = "2026-09-29T09:30:00.000Z"


def _store(world_id: str = "w_01") -> tuple[CardStore, FakeClock, FakeEventWriter]:
    clock = FakeClock(START)
    writer = FakeEventWriter()
    store = CardStore(clock=clock, writer=writer, world_owners={world_id: OWNER})
    return store, clock, writer


def _outbox_id_for(card: dict) -> str | None:
    return new_ulid(card["id"]) if card.get("kind") == "gate" else None


@pytest.mark.parametrize("name,card", valid_card_fixture_cases(), ids=[c[0] for c in valid_card_fixture_cases()])
def test_FR_HIL_01_valid_card_fixtures_are_accepted(name, card, registry):
    # Belt and braces: the fixture itself must be schema-valid (else this test would pass for
    # the wrong reason -- a store that accepts everything).
    assert card_errors(card, registry) == [], f"{name}: fixture is not schema-valid, cannot be used as a positive case"

    store, _clock, _writer = _store(card["world_id"])
    result = store.submit(card, outbox_id=_outbox_id_for(card))

    assert result.outcome in ("accepted", "merged"), f"{name}: a schema-valid card must be accepted"
    assert result.card_id == card["id"]
    assert result.errors == ()


@pytest.mark.parametrize("name,card", invalid_card_fixture_cases(), ids=[c[0] for c in invalid_card_fixture_cases()])
def test_FR_HIL_01_invalid_card_fixtures_are_refused(name, card, registry):
    assert card_errors(card, registry) != [], f"{name}: fixture must itself be schema-invalid (contracts/card.rules.md)"

    store, _clock, _writer = _store(card.get("world_id", "w_01"))
    result = store.submit(card, outbox_id=_outbox_id_for(card))

    assert result.outcome == "rejected", f"{name}: an invalid card must never be accepted or shown"
    assert result.card_id is None
    assert result.errors != ()


def test_FR_HIL_01_gate_card_requires_outbox_id():
    """card.schema.json's gate object has no outbox_id (approval.resolved.schema.json needs one
    for the outbox entry the gate releases, card.rules.md CR-12) -- CardStore.submit takes it as
    a companion argument, required for a gate card."""
    card = load_valid_card("gate_send_reply")
    store, _clock, _writer = _store(card["world_id"])

    result = store.submit(card, outbox_id=None)

    assert result.outcome == "rejected"
    assert result.card_id is None


def test_FR_HIL_01_non_gate_card_requires_no_outbox_id():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])

    result = store.submit(card, outbox_id=new_ulid("unexpected"))

    assert result.outcome == "rejected", "a non-gate card must not be given an outbox_id"


def test_FR_HIL_01_gate_and_consent_safe_default_must_be_hold():
    """PRD 10.3, card.rules.md CR-04: "Gates default to hold and never time out to 'go'"; a
    consent card never times out to a grant either. gate_safe_default_go and
    consent_safe_default_connect are the named fixtures for this rule."""
    gate = load_valid_card("gate_send_reply")
    consent = load_valid_card("consent_drive_folder")
    assert gate["safe_default"] == "hold"
    assert consent["safe_default"] == "hold"

    bad_gate = clone_card(gate)
    bad_gate["safe_default"] = "approve"
    bad_consent = clone_card(consent)
    bad_consent["safe_default"] = "connect"

    store, _clock, _writer = _store(gate["world_id"])
    assert store.submit(bad_gate, outbox_id=new_ulid("g")).outcome == "rejected"
    assert store.submit(bad_consent, outbox_id=None).outcome == "rejected"


def test_FR_HIL_01_gate_card_cannot_be_delegated_to_the_director():
    """card.rules.md CR-06: gate and consent cards offer no "Delegate to Director" action --
    approving a side effect and granting a connection are authorisations, and a model never
    authorises. Uses the named fixture gate_delegated_to_director.json."""
    card = load_json(fixtures_dir("invalid") / "gate_delegated_to_director.json")
    store, _clock, _writer = _store(card["world_id"])

    result = store.submit(card, outbox_id=new_ulid("g"))

    assert result.outcome == "rejected"


def test_FR_HIL_01_consent_card_cannot_be_delegated_to_the_director():
    card = load_json(fixtures_dir("invalid") / "consent_delegated_to_director.json")
    store, _clock, _writer = _store(card["world_id"])

    result = store.submit(card, outbox_id=None)

    assert result.outcome == "rejected"


def test_FR_HIL_01_listing_returns_the_worlds_cards_for_the_owner():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)

    cards = store.list_for_world(card["world_id"], as_user=OWNER)

    assert [c["id"] for c in cards] == [card["id"]]


def test_FR_HIL_01_listing_refuses_a_non_owner():
    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)

    with pytest.raises(PermissionError):
        store.list_for_world(card["world_id"], as_user=OTHER)


def test_FR_HIL_01_GET_worlds_cards_route_serves_the_owner():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tilo_api.cards import build_router

    card = load_valid_card("needs_you_blocked")
    store, _clock, _writer = _store(card["world_id"])
    store.submit(card, outbox_id=None)

    app = FastAPI()
    app.include_router(build_router(store))
    client = TestClient(app)

    ok = client.get(f"/worlds/{card['world_id']}/cards", params={"as_user": OWNER})
    assert ok.status_code == 200
    assert [c["id"] for c in ok.json()] == [card["id"]]

    forbidden = client.get(f"/worlds/{card['world_id']}/cards", params={"as_user": OTHER})
    assert forbidden.status_code == 403
