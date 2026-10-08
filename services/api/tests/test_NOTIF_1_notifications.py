"""NOTIF-1: `GET /v1/notifications`, the owner's bell (the Park app's `fixtures/notifications.ts`).

Derived only from records that already exist: the owner's open cards ("needs") and, from their worlds' recorded
events, `artifact.created` and `data.transfer` ("done", which is what a hosted meeting's success writes). Nothing is
stored. Titles are fixed text per source, so no address, link, card text or event summary can leak into the bell
(PE-22 spirit; HR-1: nothing without a recorded record behind it). Shape and defaults: BQ-NOTIF-1.
"""

from __future__ import annotations

import pytest
from _api_lib import base_event
from fastapi.testclient import TestClient
from test_S_06_cards_feed import SECRET, World, at, sign_in
from tilo_api import app, deps
from tilo_api.cards import CardStore

ALICE, BOB = "u_alice", "u_bob"
DONE_TYPES = ("artifact.created", "data.transfer")


def _event(store, world_id: str, seq: int, type_: str, ts: str, summary: str = "x") -> dict:
    ev = base_event(seq=seq, type_=type_, data={"note": SECRET}, world_id=world_id, summary=summary, ts=ts)
    store.events.setdefault(world_id, []).append(ev)
    return ev


def _get(client, **params):
    return client.get("/v1/notifications", params=params)


def test_NOTIF_1_open_cards_and_done_events_are_the_owners_notifications_newest_first(client, store):
    world = World(store, "w_a", ALICE)
    card = world.add("gate", created_at=at(10))
    done = _event(store, "w_a", 1, "artifact.created", at(20))
    sign_in(ALICE)
    body = _get(client).json()
    got = [(n["kind"], n["world_id"], n["id"]) for n in body["notifications"]]
    assert got == [("done", "w_a", f"e:{done['id']}"), ("needs", "w_a", f"c:{card['id']}")]
    assert body["count"] == 2


def test_NOTIF_1_only_artifact_created_and_data_transfer_count_as_done(client, store):
    World(store, "w_a", ALICE)
    for seq, type_ in enumerate(("world.started", "unit.started", *DONE_TYPES), start=1):
        _event(store, "w_a", seq, type_, at(seq))
    sign_in(ALICE)
    kinds = [n["kind"] for n in _get(client).json()["notifications"]]
    assert kinds == ["done", "done"]


def test_NOTIF_1_a_resolved_card_is_gone(client, store):
    world = World(store, "w_a", ALICE)
    card = world.add("needs_you", created_at=at(1))
    world.resolve(card)
    sign_in(ALICE)
    assert _get(client).json() == {"notifications": [], "count": 0}


def test_NOTIF_1_no_card_text_summary_or_event_data_reaches_the_bell(client, store):
    world = World(store, "w_a", ALICE)
    world.add("gate", created_at=at(1), what_happened=SECRET)
    _event(store, "w_a", 1, "data.transfer", at(2), summary=SECRET)
    sign_in(ALICE)
    response = _get(client)
    assert SECRET not in response.text and "@" not in response.text and "http" not in response.text
    for n in response.json()["notifications"]:
        assert set(n) == {"id", "kind", "created_at", "world_id", "title", "card_id", "artifact_id"}
        assert n["kind"] in ("needs", "done") and isinstance(n["title"], str) and n["title"]


def test_NOTIF_1_another_persons_worlds_never_appear_and_a_non_owner_sees_nothing(client, store):
    World(store, "w_b", BOB).add("needs_you", created_at=at(1))
    _event(store, "w_b", 1, "artifact.created", at(2))
    sign_in(ALICE)
    assert _get(client).json() == {"notifications": [], "count": 0}
    World(store, "w_a", ALICE).add("needs_you", created_at=at(3))
    sign_in(ALICE, role="viewer", world_id="w_a")
    assert _get(client).json() == {"notifications": [], "count": 0}


@pytest.mark.parametrize("limit,status", [(1, 200), (100, 200), (0, 422), (101, 422)])
def test_NOTIF_1_limit_is_one_to_one_hundred(client, store, limit, status):
    sign_in(ALICE)
    assert _get(client, limit=limit).status_code == status


def test_NOTIF_1_limit_cuts_the_list_but_count_is_the_whole_bell(client, store):
    World(store, "w_a", ALICE)
    for seq in range(1, 4):
        _event(store, "w_a", seq, "artifact.created", at(seq))
    sign_in(ALICE)
    body = _get(client, limit=2).json()
    assert len(body["notifications"]) == 2 and body["count"] == 3
    assert body["notifications"][0]["created_at"] == at(3)


def test_NOTIF_1_malformed_events_are_skipped_not_a_500(client, store):
    World(store, "w_a", ALICE)
    good = _event(store, "w_a", 1, "artifact.created", at(5))
    _event(store, "w_a", 2, ["artifact.created"], at(6))  # non-str type
    odd = _event(store, "w_a", 3, "artifact.created", at(7))
    odd["data"] = "not a dict"
    bad_id = _event(store, "w_a", 4, "artifact.created", at(8))
    bad_id["data"] = {"artifact_id": "x" * 40 + "<script>"}
    sign_in(ALICE)
    quiet = TestClient(app, raise_server_exceptions=False)
    response = quiet.get("/v1/notifications")
    assert response.status_code == 200, response.text
    items = response.json()["notifications"]
    assert good["id"] in {n["id"][2:] for n in items} and all(n["artifact_id"] is None for n in items)


def test_NOTIF_1_a_failing_card_store_is_a_fixed_503_with_no_exception_text(client, store):
    class Exploding(CardStore):
        def list_for_world(self, world_id, *, principal):
            raise RuntimeError(SECRET)

    World(store, "w_a", ALICE, store_cls=Exploding)
    sign_in(ALICE)
    quiet = TestClient(app, raise_server_exceptions=False)
    response = quiet.get("/v1/notifications")
    assert response.status_code == 503
    assert SECRET not in response.text and "RuntimeError" not in response.text


def test_NOTIF_1_no_sign_in_is_401(client, store):
    app.dependency_overrides.pop(deps.get_current_principal, None)
    assert _get(client).status_code == 401


@pytest.mark.parametrize("role", ["viewer", "team_lead", "approver"])
def test_NOTIF_1_only_the_owner_role_gets_items(client, store, role):
    World(store, "w_a", ALICE).add("needs_you", created_at=at(1))
    _event(store, "w_a", 1, "artifact.created", at(2))
    sign_in(ALICE, role=role, world_id="w_a")
    assert _get(client).json() == {"notifications": [], "count": 0}
