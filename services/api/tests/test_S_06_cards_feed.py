"""S-06 Needs-you queue and card (PRD 18 screen table S-06, Must, P4; FR-HIL-01 card structure, FR-HIL-02 timeouts and
batching, FR-HIL-11 an answer on one channel closes the card everywhere): `GET /cards` in tilo-api.

Acceptance tests, written before any implementation (ticket API-CARDS-FEED, BQ-WIRE1-4). The pinned shape, order,
paging rules and every default chosen are in API_S_06_CARDS_FEED.md and docs/open-questions.md (BQ-S06-1..8).

Through the public interface only: the real `tilo_api.app` over the in-memory `Store` the other route tests use
(`client`, `store`, `writer` from conftest.py). Each world's cards live where the per-world route reads them: the
world's run's `CardStore` (`store.runs[world_id].cards`, what `tilo_api.runs.get_card_store` returns), seeded here with
a real `CardStore` over a recording writer. No network, no model, no paid call, no cloud.
Until the route exists `GET /cards` is a 404, so every test that reads the feed fails on the missing route, not on an
import or a typo.
"""

from __future__ import annotations

import dataclasses
import math
import time
from types import SimpleNamespace

import pytest
from _api_lib import as_full_session, as_principal, make_principal, make_world
from _cards_lib import FakeClock, add_seconds, clone_card, load_valid_card, new_ulid
from _cards_lib import FakeEventWriter as CardWriter
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import app, cards, deps
from tilo_api.cards import CardStore

ALICE, BOB, CARA, DAN, EVE = "u_alice", "u_bob", "u_cara", "u_dan", "u_eve"
ITEM_KEYS = {"world_id", "card_id", "card"}  # BQ-S06-2
BODY_KEYS = {"cards", "count", "next_cursor"}  # BQ-S06-2, BQ-S06-6
DEFAULT_LIMIT, MAX_LIMIT = 20, 100  # BQ-S06-4
START = "2026-09-29T09:30:00.000Z"
SECRET = "secret-internal-detail-7731"

# kind -> (fixture, an option that resolves the card when a person picks it)
_KINDS = {
    "needs_you": ("needs_you_compare_basis", "per_kwh"),
    "gate": ("gate_send_reply", "approve"),  # a T3 gate: only a person's approve opens it
    "consent": ("consent_drive_folder", "connect"),
    "meeting": ("meeting_budget_split", "even"),
}
_serial = iter(range(1, 10**9))


class World:
    """One seeded world: its record, its run's CardStore and that store's recording writer."""

    def __init__(self, store: deps.Store, world_id: str, owner: str, *, store_cls: type[CardStore] = CardStore):
        self.world_id, self.owner = world_id, owner
        self.clock, self.writer = FakeClock(START), CardWriter()
        self.cards = store_cls(clock=self.clock, writer=self.writer, world_owners={world_id: owner})
        store.worlds[world_id] = make_world(owner=owner)
        store.runs[world_id] = SimpleNamespace(cards=self.cards)  # what runs.get_card_store reads

    def add(
        self,
        kind: str = "needs_you",
        *,
        created_at: str = START,
        district: str | None = None,
        assignee: str | None = None,
        domain: str | None = None,
        building: str | None = None,
        merge: bool = False,
        what_happened: str | None = None,
        timeout: int | None = None,
    ) -> dict:
        n = next(_serial)
        card = clone_card(
            load_valid_card(_KINDS[kind][0]), id_=new_ulid(f"{self.world_id}:{n}"), created_at=created_at,
            building=building or f"B{n}",
        )  # fmt: skip
        card["world_id"] = self.world_id
        if what_happened is not None:
            card["what_happened"] = what_happened
        if timeout is not None:
            card["timeout"] = timeout
        outbox = new_ulid(f"outbox:{n}") if kind == "gate" else None
        result = self.cards.submit(
            card, outbox_id=outbox, district=district, assignee=assignee, domain=domain, merge=merge
        )
        assert result.outcome in ("accepted", "merged"), result.errors
        return card

    def resolve(self, card: dict, *, by: str | None = None) -> None:
        """A person's answer that closes the card (the store's own `answer`, the route's callee)."""
        who = make_principal(user_id=by or self.owner, role="owner", world_id=self.world_id)
        kind = card["kind"]
        result = self.cards.answer(
            self.world_id, card["id"], option=_KINDS[kind][1], channel="web", principal=who
        )  # fmt: skip
        assert result.outcome == "answered", result.reason


def at(n: int) -> str:
    """A timestamp n seconds after START: an ordered, schema-valid stamp (ms precision, Z)."""
    return add_seconds(START, n)


def sign_in(user: str, role: str = "owner", world_id: str | None = None, districts: tuple[str, ...] = ()) -> None:
    # a full web sign-in session (BQ-XWORLD-10): the feed shows it full cards in every world in scope (BQ-XWORLD-9)
    as_principal(as_full_session(make_principal(user_id=user, role=role, world_id=world_id, districts=districts)))


def feed(client, **params):
    return client.get("/cards", params=params)


def get_feed(client, **params) -> dict:
    response = client.get("/cards", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def keys(response) -> list[tuple[str, str]]:
    assert response.status_code == 200, response.text
    return [(i["world_id"], i["card_id"]) for i in response.json()["cards"]]


def walk(client, limit: int | None = None, *, max_pages: int = 80) -> tuple[list[dict], list[str], list[int]]:
    """Every page, following next_cursor. Returns (all items in order, every cursor used, the count of each page)."""
    items: list[dict] = []
    cursors: list[str] = []
    counts: list[int] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params: dict = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/cards", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["cards"])
        counts.append(body["count"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items, cursors, counts
        cursors.append(cursor)
    raise AssertionError("paging did not end")


def feed_order(rows: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """(world_id, card_id, created_at) -> oldest first by created_at, ties by world_id then card_id (BQ-S06-3)."""
    return [(w, c) for w, c, _ in sorted(rows, key=lambda r: (r[2], r[0], r[1]))]


def per_world_cards(client, principal: deps.Principal, world_id: str) -> list[dict]:
    """What `GET /worlds/{id}/cards` returns the same person, a member of that world: the reference the feed mirrors."""
    as_principal(dataclasses.replace(principal, world_id=world_id))
    response = client.get(f"/worlds/{world_id}/cards")
    return response.json() if response.status_code == 200 else []  # 403 (a Viewer) / 404: nothing shown


# --- 1. the open cards across the worlds in scope ------------------------------------------------------------------


def test_S_06_feed_lists_the_owners_open_cards_across_every_owned_world(client, store):
    w1, w2, other = World(store, "w_a1", ALICE), World(store, "w_a2", ALICE), World(store, "w_b1", BOB)
    c1, c2 = w1.add(created_at=at(1)), w2.add("gate", created_at=at(2))
    other.add(created_at=at(3))
    sign_in(ALICE)
    assert keys(feed(client)) == [("w_a1", c1["id"]), ("w_a2", c2["id"])]
    sign_in(BOB)
    assert [w for w, _ in keys(feed(client))] == ["w_b1"]


def test_S_06_feed_owner_sees_every_owned_world_whatever_world_the_session_names(client, store):
    """As GET /worlds (BQ-S14-1): the owner's own worlds, not only the one their session names (BQ-S06-1)."""
    w1, w2 = World(store, "w_a1", ALICE), World(store, "w_a2", ALICE)
    c1, c2 = w1.add(created_at=at(1)), w2.add(created_at=at(2))
    for named in (None, "w_a1", "w_a2"):
        sign_in(ALICE, world_id=named)
        assert keys(feed(client)) == [("w_a1", c1["id"]), ("w_a2", c2["id"])], named


def test_S_06_feed_item_is_world_id_card_id_and_the_card_exactly_as_the_per_world_route_returns_it(client, store):
    """FR-HIL-01: a card keeps the structure card.schema.json gives it; the item adds only what routes an answer."""
    w = World(store, "w_a1", ALICE)
    w.add("needs_you", created_at=at(1))
    w.add("gate", created_at=at(2))
    w.add("consent", created_at=at(3))
    w.add("meeting", created_at=at(4))
    sign_in(ALICE, world_id="w_a1")
    reference = client.get("/worlds/w_a1/cards").json()
    body = get_feed(client)
    assert set(body) == BODY_KEYS
    assert len(body["cards"]) == len(reference) == 4
    for item, card in zip(body["cards"], reference, strict=True):
        assert set(item) == ITEM_KEYS  # no owner id, no district, no assignee, no outbox id
        assert item["card"] == card  # byte for byte what the per-world route shows, redaction included
        assert (item["world_id"], item["card_id"]) == (card["world_id"], card["id"])


def test_S_06_feed_never_shows_more_than_the_per_world_route_internal_fields_stay_out(client, store):
    w = World(store, "w_a1", ALICE)
    w.add("gate", created_at=at(1), district="D1", assignee=DAN)
    sign_in(ALICE, world_id="w_a1")
    response = feed(client)
    assert response.status_code == 200, response.text
    text = response.text
    for hidden in ("outbox", DAN, '"district"', "assignee", "owner_only"):
        assert hidden not in text, hidden


def test_S_06_feed_resolved_cards_are_excluded_an_answer_elsewhere_vanishes_on_the_next_read(client, store):
    """FR-HIL-11: the card answered on another channel is gone from the next read; the rest stay."""
    w = World(store, "w_a1", ALICE)
    keep, gone = w.add(created_at=at(1)), w.add(created_at=at(2))
    sign_in(ALICE)
    assert keys(feed(client)) == [("w_a1", keep["id"]), ("w_a1", gone["id"])]
    w.resolve(gone)  # answered elsewhere (the store's own answer, as every channel's route ends)
    assert keys(feed(client)) == [("w_a1", keep["id"])]


def test_S_06_feed_a_card_answered_by_email_leaves_the_web_feed_within_2_s(client, store):
    """FR-HIL-11 (channel rules, PRD 10.3): the same card answered by email updates the web in 2 s or less."""
    w = World(store, "w_a1", ALICE)
    card = w.add("needs_you", created_at=at(1))
    sign_in(ALICE, world_id="w_a1")
    assert keys(feed(client)) == [("w_a1", card["id"])]
    app.dependency_overrides[cards.get_channels_caller] = lambda: True  # tilo-channels, acting for the email session
    as_principal(make_principal(user_id=ALICE, role="owner", world_id="w_a1", channel="email"))
    started = time.monotonic()
    answered = client.post(f"/worlds/w_a1/cards/{card['id']}/answer", json={"option": "per_kwh", "channel": "email"})
    assert answered.status_code == 200, answered.text
    app.dependency_overrides.pop(cards.get_channels_caller)
    sign_in(ALICE)  # the web session reads again
    assert keys(feed(client)) == []
    assert time.monotonic() - started <= 2.0  # the number FR-HIL-11 names


def test_S_06_feed_a_held_gate_stays_listed_after_its_deadline_a_timed_out_question_does_not(client, store):
    """FR-HIL-02 / BQ-S06-5: a timeout resolves a question (safe default and a Nudge) but only holds a gate, which
    still waits for a person; the feed shows exactly the open cards, as the per-world route does."""
    w = World(store, "w_a1", ALICE)
    question, gate = w.add("needs_you", created_at=at(1)), w.add("gate", created_at=at(2))
    sign_in(ALICE)
    w.clock.advance(3600 + 1)  # both are past created_at + timeout (3600 s)
    assert w.writer.parts == []
    assert keys(feed(client)) == [("w_a1", question["id"]), ("w_a1", gate["id"])]  # not ticked yet: still open
    assert w.writer.parts == []  # reading the feed never ticks, never writes (BQ-S06-5)
    w.cards.tick()
    assert keys(feed(client)) == [("w_a1", gate["id"])]  # the question closed; the gate is held, not approved
    sign_in(ALICE, world_id="w_a1")
    assert [c["id"] for c in client.get("/worlds/w_a1/cards").json()] == [gate["id"]]


def test_S_06_feed_a_merged_batch_shows_as_one_card_like_the_per_world_route(client, store):
    """FR-HIL-02: three cards from one district in 60 s merge; the queue shows one until one answer closes the batch."""
    w = World(store, "w_a1", ALICE)
    first = w.add("needs_you", created_at=at(1), building="B2", merge=True, district="D1")
    w.add("needs_you", created_at=at(2), building="B2", merge=True, district="D1")
    w.add("needs_you", created_at=at(3), building="B2", merge=True, district="D1")
    sign_in(ALICE, world_id="w_a1")
    assert len(client.get("/worlds/w_a1/cards").json()) == 1
    assert keys(feed(client)) == [("w_a1", first["id"])]
    assert get_feed(client)["count"] == 1
    w.resolve(first)
    assert keys(feed(client)) == []  # one answer closed the whole batch


def test_S_06_feed_nothing_open_is_an_empty_list_never_a_fixture(client, store):
    World(store, "w_a1", ALICE)  # a world with no cards
    sign_in(ALICE)
    assert get_feed(client) == {"cards": [], "count": 0, "next_cursor": None}
    sign_in("u_new")  # a person with no world at all
    assert get_feed(client) == {"cards": [], "count": 0, "next_cursor": None}


def test_S_06_feed_order_is_oldest_open_first_ties_by_world_then_card_id_and_stable(client, store):
    wa, wb = World(store, "w_a", ALICE), World(store, "w_b", ALICE)
    rows: list[tuple[str, str, str]] = []
    for w, stamp in ((wb, at(2)), (wa, at(3)), (wb, at(1)), (wa, at(2)), (wa, at(2)), (wb, at(2))):
        card = w.add(created_at=stamp)
        rows.append((w.world_id, card["id"], stamp))
    sign_in(ALICE)
    assert keys(feed(client)) == feed_order(rows)
    assert keys(feed(client)) == keys(feed(client))  # deterministic


# --- 2. auth and scope ---------------------------------------------------------------------------------------------


def test_S_06_feed_unauthenticated_fails_exactly_like_the_other_world_routes(client, store):
    w = World(store, "w_one", ALICE)
    w.add()
    app.dependency_overrides.pop(deps.get_current_principal)  # no sign-in wired: the real dependency answers
    reference = client.get("/worlds/w_one/cards")
    assert reference.status_code == 401
    response = client.get("/cards")
    assert (response.status_code, response.json()) == (reference.status_code, reference.json())
    assert client.get("/worlds").status_code == 401  # the route family is consistent


def test_S_06_feed_the_user_comes_only_from_the_session_never_from_the_request(client, store):
    wa, wb = World(store, "w_a1", ALICE), World(store, "w_b1", BOB)
    ca, cb = wa.add(created_at=at(1)), wb.add(created_at=at(2))
    sign_in(ALICE)
    expected = [("w_a1", ca["id"])]
    claims = {"user_id": BOB, "owner": BOB, "uid": BOB, "world_id": "w_b1", "as": BOB}
    for name, value in claims.items():
        assert keys(client.get("/cards", params={name: value})) == expected, name
        assert keys(client.get("/cards", headers={f"x-{name.replace('_', '-')}": value})) == expected, name
    assert keys(client.get("/cards", headers={"x-test-principal": BOB, "authorization": f"Bearer {BOB}"})) == expected
    sign_in(BOB)
    assert keys(feed(client)) == [("w_b1", cb["id"])]


def test_S_06_feed_another_owners_session_that_names_your_world_sees_only_its_own_cards(client, store):
    wa, wb = World(store, "w_a1", ALICE), World(store, "w_b1", BOB)
    wa.add(created_at=at(1))
    cb = wb.add(created_at=at(2))
    sign_in(BOB, role="owner", world_id="w_a1")  # Bob's session names Alice's world: it makes him no member of it
    assert keys(feed(client)) == [("w_b1", cb["id"])]


def test_S_06_feed_responses_carry_no_other_users_data_at_all(client, store):
    wa, wb = World(store, "w_a1", ALICE), World(store, "w_b1", BOB)
    wa.add(created_at=at(1), what_happened="Alice private matter")
    cb = wb.add(created_at=at(2), what_happened="Bob private matter")
    sign_in(ALICE)
    response = feed(client)
    assert response.status_code == 200
    for leaked in ("Bob private matter", "w_b1", cb["id"], BOB):
        assert leaked not in response.text, leaked


def test_S_06_feed_a_team_lead_sees_only_their_districts_cards_and_never_a_hidden_ones_count(client, store):
    """FR-HIL-09 / SEC-07: the same visibility filter as the per-world route; a hidden district, its cards and its
    number never leave the API, and the count is of what the person can see."""
    w = World(store, "w_a1", ALICE)
    d1 = w.add("needs_you", created_at=at(1), district="D1")
    w.add("needs_you", created_at=at(2), district="D2", what_happened="SECRET about D2")
    w.add("gate", created_at=at(3), district=None)  # owner-only (no district)
    w.add("needs_you", created_at=at(4), district="D1", domain="pricing")  # routed to the console: not the lead's here
    sign_in(CARA, role="team_lead", world_id="w_a1", districts=("D1",))
    response = feed(client)
    assert keys(response) == [("w_a1", d1["id"])]
    assert response.json()["count"] == 1
    assert "SECRET about D2" not in response.text
    sign_in(ALICE, world_id="w_a1")
    assert get_feed(client)["count"] == 4  # the owner sees all four


def test_S_06_feed_an_approver_sees_only_the_cards_assigned_to_them(client, store):
    w = World(store, "w_a1", ALICE)
    mine = w.add("gate", created_at=at(1), district="D1", assignee=DAN)
    w.add("gate", created_at=at(2), district="D1", assignee=CARA)
    w.add("needs_you", created_at=at(3), district="D1")
    sign_in(DAN, role="approver", world_id="w_a1")
    response = feed(client)
    assert keys(response) == [("w_a1", mine["id"])]
    assert response.json()["count"] == 1


def test_S_06_feed_a_member_sees_only_the_one_world_they_belong_to(client, store):
    wa1, wa2 = World(store, "w_a1", ALICE), World(store, "w_a2", ALICE)
    wb = World(store, "w_b1", BOB)
    c1 = wa1.add(created_at=at(1), district="D1")
    wa2.add(created_at=at(2), district="D1")
    wb.add(created_at=at(3), district="D1")
    sign_in(CARA, role="team_lead", world_id="w_a1", districts=("D1",))
    assert keys(feed(client)) == [("w_a1", c1["id"])]


def test_S_06_feed_a_viewer_a_member_with_no_world_or_an_unknown_one_gets_an_empty_list_not_an_error(client, store):
    w = World(store, "w_a1", ALICE)
    w.add(district="D1")
    empty = {"cards": [], "count": 0, "next_cursor": None}
    sign_in(EVE, role="viewer", world_id="w_a1")  # the per-world route says 403 to a Viewer; the feed never says so
    assert get_feed(client) == empty
    sign_in(EVE, role="team_lead", world_id=None, districts=("D1",))
    assert get_feed(client) == empty
    sign_in(EVE, role="approver", world_id="w_does_not_exist")
    assert get_feed(client) == empty  # no membership oracle (a 404 would tell)


# --- 3. read only ----------------------------------------------------------------------------------------------------


def test_S_06_feed_is_read_only_no_other_verbs_no_events_no_state_change(client, store, writer):
    w = World(store, "w_a1", ALICE)
    gate, question = w.add("gate", created_at=at(1)), w.add("needs_you", created_at=at(2))
    w.clock.advance(3600 + 1)  # past both deadlines: a read must not tick them either
    sign_in(ALICE)
    before = {k: list(v) for k, v in store.events.items()}
    assert feed(client).status_code == 200
    assert feed(client, limit=1).status_code == 200
    assert client.post("/cards", json={}).status_code in (404, 405)
    assert client.put("/cards", json={}).status_code in (404, 405)
    assert client.delete("/cards").status_code in (404, 405)
    assert client.post(f"/cards/{gate['id']}/answer", json={"option": "approve"}).status_code in (404, 405)
    assert writer.calls == []  # nothing appended, nothing queued (HR-1: nothing without a recorded event)
    assert store.pending_events == {}
    assert store.events == before
    assert w.writer.parts == []  # the card store wrote no event part
    assert w.cards.is_open("w_a1", gate["id"]) and w.cards.is_open("w_a1", question["id"])  # nothing closed


def test_S_06_feed_t3_cards_are_shown_like_the_others_and_reading_never_opens_one(client, store):
    """No T3 without a person: the feed lists a T3 gate; only a person's answer on the existing route opens it."""
    w = World(store, "w_a1", ALICE)
    gate = w.add("gate", created_at=at(1))
    assert gate["gate"]["risk_tier"] == "T3"
    sign_in(ALICE, world_id="w_a1")
    for _ in range(3):
        (item,) = get_feed(client)["cards"]
        assert item["card"]["kind"] == "gate" and item["card"]["gate"]["risk_tier"] == "T3"
        assert item["card"] == client.get("/worlds/w_a1/cards").json()[0]
    assert w.writer.parts == [] and w.cards.is_open("w_a1", gate["id"])  # no approval.resolved from a read


def test_S_06_feed_item_routes_the_answer_to_the_existing_per_world_route_which_still_needs_a_person(client, store):
    w = World(store, "w_a1", ALICE)
    gate = w.add("gate", created_at=at(1))
    sign_in(ALICE, world_id="w_a1")
    ((world_id, card_id),) = keys(feed(client))
    assert (world_id, card_id) == ("w_a1", gate["id"])
    refused = client.post(
        f"/worlds/{world_id}/cards/{card_id}/answer", json={"option": "approve", "channel": "email"}
    )  # fmt: skip
    # a gate opens only in a signed-in web session (SEC-06): the route is unchanged, so email is refused
    assert refused.status_code in (400, 403)
    assert refused.json()["outcome"] == "rejected"
    assert keys(feed(client)) == [("w_a1", gate["id"])] and w.writer.parts == []
    answered = client.post(f"/worlds/{world_id}/cards/{card_id}/answer", json={"option": "approve"})
    assert answered.status_code == 200
    (part,) = w.writer.parts
    assert part["type"] == "approval.resolved" and part["authz"]["by"] == "person" and part["authz"]["ref"] == ALICE
    assert keys(feed(client)) == []  # FR-HIL-11: gone on the next read


# --- 4. paging, errors -----------------------------------------------------------------------------------------------


def test_S_06_feed_default_page_size_is_20_and_the_cursor_continues_it(client, store):
    w = World(store, "w_a1", ALICE)
    made = [w.add(created_at=at(n)) for n in range(25)]
    sign_in(ALICE)
    first = get_feed(client)
    assert len(first["cards"]) == DEFAULT_LIMIT
    assert first["count"] == 25  # the whole queue, not the page (BQ-S06-6)
    assert isinstance(first["next_cursor"], str) and first["next_cursor"]
    second = get_feed(client, cursor=first["next_cursor"])
    assert [i["card_id"] for i in first["cards"] + second["cards"]] == [c["id"] for c in made]
    assert len(second["cards"]) == 5 and second["next_cursor"] is None
    assert second["count"] == 25


def test_S_06_feed_max_page_size_is_100_and_101_is_refused(client, store):
    w = World(store, "w_a1", ALICE)
    for n in range(105):
        w.add(created_at=add_seconds(START, n))
    sign_in(ALICE)
    page = get_feed(client, limit=MAX_LIMIT)
    assert len(page["cards"]) == MAX_LIMIT and page["next_cursor"] is not None
    assert len(get_feed(client, limit=1)["cards"]) == 1
    assert feed(client, limit=MAX_LIMIT + 1).status_code == 422


@pytest.mark.parametrize("limit", ["0", "-1", "abc", "1.5", "101", "100000", ""])
def test_S_06_feed_a_bad_limit_is_a_422_in_the_api_error_shape(client, store, limit):
    World(store, "w_a1", ALICE).add()
    sign_in(ALICE)
    response = client.get("/cards", params={"limit": limit})
    assert response.status_code == 422
    assert "detail" in response.json()


@pytest.mark.parametrize(
    "cursor",
    ["not-a-cursor", "!!!", "0", "w_a1", "x" * 5000, "%00", "eyJ9", "e30.e30"],
    ids=["words", "punctuation", "zero", "a_world_id", "5000_chars", "nul", "short_base64", "forged_mac"],
)
def test_S_06_feed_a_bad_cursor_is_a_400_in_the_api_error_shape(client, store, cursor):
    World(store, "w_a1", ALICE).add()
    sign_in(ALICE)
    response = client.get("/cards", params={"cursor": cursor})
    assert response.status_code == 400
    assert "detail" in response.json()


def test_S_06_feed_the_cursor_is_opaque_it_spells_out_no_world_or_card_id(client, store):
    w = World(store, "w_a1", ALICE)
    made = [w.add(created_at=at(n)) for n in range(4)]
    sign_in(ALICE)
    cursor = get_feed(client, limit=2)["next_cursor"]
    assert isinstance(cursor, str) and cursor
    assert "w_a1" not in cursor and not any(c["id"] in cursor for c in made)


def test_S_06_feed_the_last_page_has_no_cursor_and_no_empty_page_follows(client, store):
    w = World(store, "w_a1", ALICE)
    for n in range(4):
        w.add(created_at=at(n))
    sign_in(ALICE)
    first = get_feed(client, limit=2)
    second = get_feed(client, limit=2, cursor=first["next_cursor"])
    assert len(second["cards"]) == 2 and second["next_cursor"] is None  # exactly full, nothing left
    assert get_feed(client, limit=4)["next_cursor"] is None
    assert get_feed(client, limit=3)["next_cursor"] is not None


def test_S_06_feed_a_card_answered_between_pages_causes_no_duplicate_and_no_gap(client, store):
    w = World(store, "w_a1", ALICE)
    made = [w.add(created_at=at(n)) for n in range(1, 7)]
    sign_in(ALICE)
    first = get_feed(client, limit=2)
    assert [i["card_id"] for i in first["cards"]] == [made[0]["id"], made[1]["id"]]
    w.resolve(made[3])  # answered elsewhere after page 1 was served (FR-HIL-11)
    w.resolve(made[0])  # a card already served on page 1 closes too: nothing shifts
    seen = [i["card_id"] for i in first["cards"]]
    cursor = first["next_cursor"]
    while cursor is not None:
        page = get_feed(client, limit=2, cursor=cursor)
        seen += [i["card_id"] for i in page["cards"]]
        cursor = page["next_cursor"]
    assert seen == [made[n]["id"] for n in (0, 1, 2, 4, 5)]  # each still-open card once, in order, made[3] gone


def test_S_06_feed_a_cursor_minted_for_one_user_replayed_by_another_is_a_400(client, store):
    wa, wb = World(store, "w_a1", ALICE), World(store, "w_b1", BOB)
    for n in range(5):
        wa.add(created_at=at(n))
    for n in range(3):
        wb.add(created_at=at(10 + n))
    sign_in(ALICE)
    _, cursors, _ = walk(client, 2)
    assert cursors
    sign_in(BOB)
    for cursor in cursors:
        response = feed(client, limit=2, cursor=cursor)
        assert response.status_code == 400 and "detail" in response.json(), cursor
        assert "u_alice" not in response.text and "w_a1" not in response.text
    sign_in(CARA, role="team_lead", world_id="w_a1", districts=("D1",))  # a member replaying the owner's cursor
    assert feed(client, limit=2, cursor=cursors[0]).status_code == 400


def test_S_06_feed_a_tampered_cursor_is_a_400(client, store):
    w = World(store, "w_a1", ALICE)
    for n in range(4):
        w.add(created_at=at(n))
    sign_in(ALICE)
    cursor = get_feed(client, limit=2)["next_cursor"]
    assert isinstance(cursor, str) and cursor
    forged = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    assert feed(client, limit=2, cursor=forged).status_code == 400


def test_S_06_feed_errors_never_leak_exception_text_and_a_broken_world_is_not_hidden(client, store):
    """BQ-S06-8: if one world's card store fails, the whole read is a 503 with a fixed message: a partial feed would
    silently drop a decision that is waiting for a person. Nothing of the failure's text reaches the caller."""

    class Exploding(CardStore):
        def list_for_world(self, world_id, *, principal):
            raise RuntimeError(SECRET)

    good = World(store, "w_a1", ALICE)
    good.add(created_at=at(1))
    World(store, "w_a2", ALICE, store_cls=Exploding)
    sign_in(ALICE)
    quiet = TestClient(app, raise_server_exceptions=False)  # an unhandled error becomes a 500 for the caller to see
    response = quiet.get("/cards")
    assert response.status_code == 503, response.text
    assert SECRET not in response.text and "RuntimeError" not in response.text and "Traceback" not in response.text
    assert "detail" in response.json()
    for bad in (quiet.get("/cards", params={"limit": "abc"}), quiet.get("/cards", params={"cursor": "!!!"})):
        assert SECRET not in bad.text and "Traceback" not in bad.text
        assert bad.status_code in (400, 422)  # validated before any world is read


# --- 5. consistency: the feed is the union of the per-world routes ---------------------------------------------------


def _build_example(store: deps.Store, spec: list[list[tuple[str, int, str | None, str | None, bool]]]):
    """worlds: w_a1, w_a2 (Alice), w_b1 (Bob); each card (kind, stamp, district, assignee, answered)."""
    store.worlds.clear()
    store.runs.clear()
    store.events.clear()
    built = []
    for (world_id, owner), cards_spec in zip((("w_a1", ALICE), ("w_a2", ALICE), ("w_b1", BOB)), spec, strict=True):
        w = World(store, world_id, owner)
        built.append(w)
        for kind, stamp, district, assignee, answered in cards_spec:
            card = w.add(kind, created_at=at(stamp), district=district, assignee=assignee)
            if answered:
                w.resolve(card)
    return built


_CARD = st.tuples(
    st.sampled_from(sorted(_KINDS)),
    st.integers(min_value=0, max_value=5),  # few stamps on purpose: many ties, so the tie-break is exercised
    st.sampled_from([None, "D1", "D2"]),
    st.sampled_from([None, DAN, CARA]),
    st.booleans(),
)
_WORLD = st.lists(_CARD, max_size=5)
_CALLERS = [
    (ALICE, "owner", None, ()),
    (ALICE, "owner", "w_a2", ()),
    (BOB, "owner", None, ()),
    (CARA, "team_lead", "w_a1", ("D1",)),
    (CARA, "team_lead", "w_b1", ("D1", "D2")),
    (DAN, "approver", "w_a2", ()),
    (EVE, "viewer", "w_a1", ()),
]


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(spec=st.lists(_WORLD, min_size=3, max_size=3), limit=st.integers(min_value=1, max_value=6))
def test_S_06_feed_property_items_equal_the_union_of_the_per_world_routes_for_every_caller(client, store, spec, limit):
    """The invariant: the feed shows exactly the open cards the per-world route shows each in-scope world, no more (no
    visibility or redaction difference), once each, oldest first, paged with no duplicate and no gap, with a count
    equal to the whole queue, and a read changes nothing."""
    worlds = _build_example(store, spec)
    snapshot = [(w.world_id, [r.status for r in (w.cards._records.get(w.world_id) or {}).values()]) for w in worlds]
    for user, role, named, districts in _CALLERS:
        me = make_principal(user_id=user, role=role, world_id=named, districts=districts)
        me = as_full_session(me)  # a full web sign-in session (BQ-XWORLD-10)
        in_scope = (
            [w.world_id for w in worlds if w.owner == user]
            if role == "owner"
            else ([named] if named is not None else [])
        )
        expected = []
        for world_id in in_scope:
            expected += per_world_cards(client, me, world_id)
        expected.sort(key=lambda c: (c["created_at"], c["world_id"], c["id"]))
        as_principal(me)
        items, cursors, counts = walk(client, limit)
        assert [i["card"] for i in items] == expected, (user, role, named)
        assert [(i["world_id"], i["card_id"]) for i in items] == [(c["world_id"], c["id"]) for c in expected]
        assert all(set(i) == ITEM_KEYS for i in items)
        assert len({(i["world_id"], i["card_id"]) for i in items}) == len(items)  # no duplicate
        assert counts and set(counts) == {len(expected)}  # the count is the whole queue on every page
        assert len(cursors) == max(math.ceil(len(expected) / limit) - 1, 0)  # a cursor between pages only
    after = [(w.world_id, [r.status for r in (w.cards._records.get(w.world_id) or {}).values()]) for w in worlds]
    assert after == snapshot  # reads closed nothing
    assert sum(len(w.writer.parts) for w in worlds) == sum(  # only the seeding answers wrote anything
        1 for cards_spec in spec for c in cards_spec if c[4]
    )


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(spec=st.lists(_WORLD, min_size=3, max_size=3), limit=st.integers(min_value=1, max_value=6))
def test_S_06_feed_property_no_cross_user_leak_and_a_foreign_cursor_never_works(client, store, spec, limit):
    worlds = _build_example(store, spec)
    mine = {w.world_id for w in worlds if w.owner == ALICE}
    sign_in(ALICE)
    items, alice_cursors, _ = walk(client, limit)
    assert {i["world_id"] for i in items} <= mine
    sign_in(BOB)
    bobs, _, _ = walk(client, limit)
    assert {i["world_id"] for i in bobs} <= {"w_b1"}
    for cursor in alice_cursors:
        assert feed(client, limit=limit, cursor=cursor).status_code == 400
