"""FR-HIL-10 security review fixes (PRD 10.1, 16.2, BQ-90): the console answer route has the cards router's Pause all
guard; a domain-routed question is answerable only through the console by its own domain's lead (never on the cards
routes); and only a schema-valid Team Lead record the world's owner assigned, not in the future, grants the console."""

from __future__ import annotations

import copy

import pytest
from _cards_lib import (
    FakeClock,
    FakeEventWriter,
    clone_card,
    load_valid_card,
    new_ulid,
    principal,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import cards, console, deps, runs
from tilo_api.cards import CardStore

START = "2026-09-29T09:30:00.000Z"
W, OWNER = "w_01", "u_owner"
GOOD = {
    "id": "tl_security",
    "user": "u_sec",
    "domain": "security",
    "assigned_by": {"by": OWNER, "at": "2026-09-01T00:00:00.000Z"},
}
SEC = principal(role="team_lead", user_id="u_sec", world_id=W, districts=("D1",))
FIN = principal(role="team_lead", user_id="u_fin", world_id=W, districts=("D1",))
FIN_RECORD = {**GOOD, "id": "tl_finance", "user": "u_fin", "domain": "finance"}


def setup(team_leads, who=SEC, *, paused: bool | None = None):
    writer = FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={W: OWNER})
    q = clone_card(load_valid_card("needs_you_blocked"), id_=new_ulid("q"), created_at=START, building="B2")
    assert store.submit(q, district="D1", domain="security").outcome == "accepted"
    app = FastAPI()
    guard = None
    if paused is not None:
        guard = runs.answer_guard
        state = deps.Store()
        state.worlds[W] = deps.WorldRecord(owner=OWNER, districts={}, paused=paused)
        app.dependency_overrides[deps.get_store] = lambda: state
    app.include_router(console.build_router(store, answer_guard=guard))
    app.include_router(cards.build_router(store))
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    app.dependency_overrides[console.get_team_leads] = lambda: list(team_leads)
    return TestClient(app), store, writer, q


def test_FR_HIL_10_a_paused_world_refuses_a_console_answer_and_writes_nothing():
    http, _, writer, q = setup([GOOD], paused=True)

    response = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"})

    assert response.status_code == 409 and writer.parts == []


def test_FR_HIL_10_an_unpaused_world_still_takes_a_console_answer_through_the_guard():
    http, _, writer, q = setup([GOOD], paused=False)

    response = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"})

    assert response.status_code == 200 and len(writer.of_type("question.answered")) == 1


def test_FR_HIL_10_a_team_lead_of_another_domain_cannot_list_or_answer_a_routed_question_on_the_cards_routes():
    http, _, writer, q = setup([GOOD, FIN_RECORD], who=FIN)  # finance lead, same district as the security question

    listed = http.get(f"/worlds/{W}/cards")
    answered = http.post(f"/worlds/{W}/cards/{q['id']}/answer", json={"option": "per_kwh"})

    assert listed.status_code == 200 and listed.json() == []
    assert answered.status_code == 404 and answered.json() == {"outcome": "rejected", "reason": "card_not_found"}
    assert writer.parts == []


def test_FR_HIL_10_even_the_leads_own_domain_answers_a_routed_question_only_through_the_console():
    http, _, writer, q = setup([GOOD], who=SEC)

    assert http.get(f"/worlds/{W}/cards").json() == []
    assert http.post(f"/worlds/{W}/cards/{q['id']}/answer", json={"option": "per_kwh"}).status_code == 404
    assert writer.parts == []
    assert http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"}).status_code == 200


def _without(record, *keys):
    return {k: v for k, v in record.items() if k not in keys}


BAD_RECORDS = {
    "assigned by someone else": {**GOOD, "assigned_by": {"by": "u_mallory", "at": "2026-09-01T00:00:00.000Z"}},
    "assigned in the future": {**GOOD, "assigned_by": {"by": OWNER, "at": "2099-01-01T00:00:00.000Z"}},
    "no id": _without(GOOD, "id"),
    "no assigned_by": _without(GOOD, "assigned_by"),
    "assigned_by without at": {**GOOD, "assigned_by": {"by": OWNER}},
    "extra key": {**GOOD, "note": "x"},
    "domain not a slug": {**GOOD, "domain": "Not A Slug"},
    "bad timestamp": {**GOOD, "assigned_by": {"by": OWNER, "at": "yesterday"}},
}


@pytest.mark.parametrize("record", list(BAD_RECORDS.values()), ids=list(BAD_RECORDS))
def test_FR_HIL_10_a_team_lead_record_not_assigned_by_the_owner_is_403_never_500(record):
    http, _, writer, q = setup([copy.deepcopy(record)])

    listing = http.get(f"/worlds/{W}/console")
    answer = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"})

    assert listing.status_code == 403 and answer.status_code == 403
    assert writer.parts == []


def test_FR_HIL_10_a_later_valid_record_of_the_same_user_still_grants_the_console():
    http, _, _, _ = setup([BAD_RECORDS["assigned by someone else"], GOOD])

    assert http.get(f"/worlds/{W}/console").status_code == 200
