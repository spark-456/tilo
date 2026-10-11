"""S-14 Worlds list and replays (PRD 18.x S-14 row, Must, P3; FR-WLD-08 replay): `GET /worlds` in tilo-api.

Acceptance tests, written before any implementation (ticket API-WORLDS-LIST, BQ-WIRE1-3). The pinned shape, order,
pagination rules and every default chosen are in API_S_14_WORLDS_LIST.md and docs/open-questions.md (BQ-S14-1..5).

Through the public interface only: the real `tilo_api.app` over the in-memory `Store` the other route tests use
(`client`, `store`, `writer` from conftest.py). No network, no model, no paid call, no cloud.
Until the route exists `GET /worlds` is a 404 (the `/worlds/{world_id}` routes do not match it), so every test that
reads the list fails on the missing route, not on an import or a typo.
"""

from __future__ import annotations

import math

import pytest
from _api_lib import as_principal, base_event, make_district, make_principal, make_world
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import app, deps

ALICE, BOB, CARA = "u_alice", "u_bob", "u_cara"
ITEM_KEYS = {"world_id", "title", "status", "created_at", "last_seq"}  # BQ-S14-2
DEFAULT_LIMIT, MAX_LIMIT = 20, 100  # BQ-S14-3
T1, T2, T3, T4 = (f"2026-09-29T09:30:0{n}.000Z" for n in (1, 2, 3, 4))

_serial = iter(range(1, 10**9))


def _ev(world_id: str, seq: int, type_: str, data: dict, *, owner: str, ts: str, vis="all", district=None) -> dict:
    event = base_event(
        seq=seq, type_=type_, data=data, world_id=world_id, actor=owner, ts=ts, vis=vis, district=district
    )
    event["id"] = f"01JB5VQ{next(_serial):019d}"  # unique across worlds (common.schema.json ulid shape)
    return event


def seed_world(
    store: deps.Store,
    world_id: str,
    owner: str,
    *,
    title: str | None = None,
    ts: str = T1,
    after: tuple[str, ...] = (),
) -> None:
    """A world whose stream starts with world.requested (title and ts), then one event per type in `after`."""
    store.worlds[world_id] = make_world(owner=owner)
    events = [
        _ev(world_id, 1, "world.requested", {"title": title or f"Title of {world_id}", "channel": "web",
                                             "destination": None}, owner=owner, ts=ts)
    ]  # fmt: skip
    for n, type_ in enumerate(after, start=2):
        events.append(_ev(world_id, n, type_, {}, owner=owner, ts=ts))
    store.events[world_id] = events


def sign_in(user: str, role: str = "owner", world_id: str | None = None, districts: tuple[str, ...] = ()) -> None:
    as_principal(make_principal(user_id=user, role=role, world_id=world_id, districts=districts))


def listing(client, **params):
    return client.get("/worlds", params=params)


def ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["world_id"] for item in response.json()["worlds"]]


def walk(client, limit: int | None = None, *, max_pages: int = 60) -> tuple[list[dict], list[str]]:
    """Every page, following next_cursor to the end. Returns (all items in order, every cursor used)."""
    items: list[dict] = []
    cursors: list[str] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params: dict = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/worlds", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["worlds"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items, cursors
        cursors.append(cursor)
    raise AssertionError("pagination did not end")


def expected_order(rows: list[tuple[str, str]]) -> list[str]:
    """(world_id, created_at) -> ids newest first by created_at, ties broken by world_id descending (BQ-S14-3)."""
    return [w for w, _ in sorted(rows, key=lambda r: (r[1], r[0]), reverse=True)]


# --- 1. auth: the same as the existing world routes --------------------------------------------


def test_S_14_worlds_list_unauthenticated_fails_exactly_like_the_other_world_routes(client, store):
    seed_world(store, "w_one", ALICE)
    app.dependency_overrides.pop(deps.get_current_principal)  # no sign-in wired: the real dependency answers
    reference = client.get("/worlds/w_one/cards")
    assert reference.status_code == 401
    response = client.get("/worlds")
    assert (response.status_code, response.json()) == (reference.status_code, reference.json())
    assert client.get("/worlds/w_one").status_code == 401  # the route family is consistent


def test_S_14_worlds_list_is_read_only_no_other_verbs_and_no_events_written(client, store, writer):
    seed_world(store, "w_one", ALICE)
    sign_in(ALICE)
    before = {w: list(e) for w, e in store.events.items()}
    assert client.get("/worlds").status_code == 200
    assert client.post("/worlds", json={}).status_code in (404, 405)
    assert client.put("/worlds", json={}).status_code in (404, 405)
    assert client.delete("/worlds").status_code in (404, 405)
    assert writer.calls == []  # nothing is appended, nothing queued (HR-1: nothing without a recorded event)
    assert store.pending_events == {}
    assert store.events == before


# --- 2. scoped to the caller ---------------------------------------------------------------------


def test_S_14_worlds_list_returns_only_the_worlds_the_owner_owns(client, store):
    seed_world(store, "w_a1", ALICE, ts=T1)
    seed_world(store, "w_a2", ALICE, ts=T2)
    seed_world(store, "w_b1", BOB, ts=T3)
    sign_in(ALICE)
    assert ids(listing(client)) == ["w_a2", "w_a1"]
    sign_in(BOB)
    assert ids(listing(client)) == ["w_b1"]


def test_S_14_worlds_list_owner_sees_every_owned_world_whatever_world_the_principal_names(client, store):
    """Like GET /costs (tilo_api.costs): the owner's own worlds, not only the one their session names (BQ-S14-1)."""
    seed_world(store, "w_a1", ALICE, ts=T1)
    seed_world(store, "w_a2", ALICE, ts=T2)
    seed_world(store, "w_b1", BOB, ts=T3)
    for named in (None, "w_a1", "w_a2"):
        sign_in(ALICE, world_id=named)
        assert ids(listing(client)) == ["w_a2", "w_a1"], named


def test_S_14_worlds_list_a_member_who_is_not_the_owner_sees_only_the_one_world_they_belong_to(client, store):
    seed_world(store, "w_a1", ALICE, ts=T1)
    seed_world(store, "w_a2", ALICE, ts=T2)
    seed_world(store, "w_b1", BOB, ts=T3)
    for role in ("viewer", "approver", "team_lead"):
        sign_in(CARA, role=role, world_id="w_a1")
        assert ids(listing(client)) == ["w_a1"], role


def test_S_14_worlds_list_a_member_with_no_world_or_an_unknown_one_gets_an_empty_list_not_an_error(client, store):
    seed_world(store, "w_a1", ALICE)
    sign_in(CARA, role="viewer", world_id=None)
    assert listing(client).json() == {"worlds": [], "next_cursor": None}
    sign_in(CARA, role="viewer", world_id="w_does_not_exist")
    assert listing(client).json() == {"worlds": [], "next_cursor": None}  # no membership oracle (404 would tell)


def test_S_14_worlds_list_a_new_user_gets_an_empty_list(client, store):
    sign_in("u_new")  # STARTER-1: "empty" is only the sample project, never one of this person's own worlds
    assert ids(listing(client)) == ["w_sample_village_basic"]
    seed_world(store, "w_a1", ALICE)  # other people's worlds exist; they are not this person's
    assert ids(listing(client)) == ["w_sample_village_basic"]


def test_S_14_worlds_list_never_shows_a_fixture_or_sample_world(client, store):
    """HR-1..HR-7: every listed id is a stored world of the caller; nothing is made up to fill a page."""
    for n in range(4):
        seed_world(store, f"w_a{n}", ALICE, ts=f"2026-09-29T09:30:0{n}.000Z")
    sign_in(ALICE)
    shown = ids(listing(client))
    assert sorted(shown) == sorted(w for w, rec in store.worlds.items() if rec.owner == ALICE)
    store.worlds.clear()
    store.events.clear()
    assert ids(listing(client)) == ["w_sample_village_basic"]  # STARTER-1: the one recorded sample, flagged `sample`


# --- 4. item shape: only what already exists (title, status, created time, last seq) -------------


def test_S_14_worlds_list_item_carries_exactly_id_title_status_created_at_last_seq(client, store):
    seed_world(store, "w_a1", ALICE, title="Weekly supplier summary", ts=T2, after=("world.started", "world.completed"))
    sign_in(ALICE)
    body = listing(client).json()
    assert set(body) == {"worlds", "next_cursor"}
    (item,) = body["worlds"]
    assert set(item) == ITEM_KEYS  # no owner id, no districts, no event bodies, no run id
    assert item == {
        "world_id": "w_a1",
        "title": "Weekly supplier summary",  # world.requested data.title (the first one)
        "status": "completed",
        "created_at": T2,  # ts of that world.requested event
        "last_seq": 3,
    }


@pytest.mark.parametrize(
    ("after", "status"),
    [
        ((), "idle"),
        (("world.started",), "started"),
        (("world.started", "world.paused"), "paused"),
        (("world.started", "world.paused", "world.resumed"), "started"),
        (("world.started", "world.completed"), "completed"),
        (("world.started", "world.failed"), "failed"),
        (("world.started", "world.exploded"), "started"),  # HR-5: an unregistered type changes nothing
    ],
)
def test_S_14_worlds_list_status_is_the_latest_world_event_never_a_stored_flag(client, store, after, status):
    seed_world(store, "w_a1", ALICE, after=after)
    store.worlds["w_a1"].paused = True  # a bare flag with no event behind it says nothing (HR-1)
    sign_in(ALICE)
    (item,) = listing(client).json()["worlds"]
    assert item["status"] == status
    assert item["last_seq"] == 1 + len(after)  # the seq of the last recorded event: where a replay (FR-WLD-08) ends


def test_S_14_worlds_list_a_world_with_no_recorded_event_is_honest_about_it(client, store):
    store.worlds["w_empty"] = make_world(owner=ALICE)  # a record, no events yet
    sign_in(ALICE)
    (item,) = listing(client).json()["worlds"]
    assert item == {"world_id": "w_empty", "title": None, "status": "idle", "created_at": None, "last_seq": 0}


def test_S_14_worlds_list_title_and_created_at_come_from_the_first_world_requested_event(client, store):
    seed_world(store, "w_a1", ALICE, title="First ask", ts=T1)
    later = {"title": "Later ask", "channel": "web", "destination": None}
    store.events["w_a1"].append(_ev("w_a1", 2, "world.requested", later, owner=ALICE, ts=T4))
    sign_in(ALICE)
    (item,) = listing(client).json()["worlds"]
    assert (item["title"], item["created_at"], item["last_seq"]) == ("First ask", T1, 2)


def test_S_14_worlds_list_a_scoped_member_never_learns_the_size_of_events_they_cannot_see(client, store):
    """The member's last_seq is the last seq of THEIR view of the events route (renumbered, hidden events dropped),
    so the list leaks neither a hidden event's existence nor the owner's true count (SEC-07, FR-HIL-09)."""
    seed_world(store, "w_a1", ALICE, ts=T1)
    store.worlds["w_a1"].districts = {"D1": make_district("Inbox", "mail"), "D2": make_district("Money", "pay")}
    store.events["w_a1"] += [
        _ev("w_a1", 2, "world.started", {}, owner=ALICE, ts=T2, vis=["D2"], district="D2"),
        _ev("w_a1", 3, "world.completed", {}, owner=ALICE, ts=T3),
    ]
    sign_in(CARA, role="viewer", world_id="w_a1", districts=("D1",))
    (item,) = listing(client).json()["worlds"]
    seen = client.get("/worlds/w_a1/events").json()["events"]
    assert [e["seq"] for e in seen] == [1, 2]  # D2's event is gone and the rest renumbered
    assert item["last_seq"] == seen[-1]["seq"] == 2
    sign_in(ALICE, world_id="w_a1")
    (owner_item,) = listing(client).json()["worlds"]
    assert owner_item["last_seq"] == 3


# --- 3. pagination: order, default and max size, opaque cursor, no duplicates or gaps ------------


def test_S_14_worlds_list_order_is_newest_first_by_created_at_ties_by_world_id_descending(client, store):
    seed_world(store, "w_m", ALICE, ts=T2)
    seed_world(store, "w_a", ALICE, ts=T3)
    seed_world(store, "w_z", ALICE, ts=T1)
    seed_world(store, "w_b", ALICE, ts=T2)  # ties w_m at T2: w_m (the larger id) first
    store.worlds["w_none"] = make_world(owner=ALICE)  # no created_at: after every dated world
    sign_in(ALICE)
    assert ids(listing(client)) == ["w_a", "w_m", "w_b", "w_z", "w_none"]
    assert ids(listing(client)) == ids(listing(client))  # deterministic


def test_S_14_worlds_list_default_page_size_is_20_and_the_cursor_continues_it(client, store):
    for n in range(25):
        seed_world(store, f"w_a{n:02d}", ALICE, ts=f"2026-09-29T09:{n:02d}:00.000Z")
    sign_in(ALICE)
    first = listing(client).json()
    assert len(first["worlds"]) == DEFAULT_LIMIT
    assert isinstance(first["next_cursor"], str) and first["next_cursor"]
    second = listing(client, cursor=first["next_cursor"]).json()
    assert [w["world_id"] for w in first["worlds"] + second["worlds"]] == [f"w_a{n:02d}" for n in range(24, -1, -1)]
    assert len(second["worlds"]) == 5
    assert second["next_cursor"] is None


def test_S_14_worlds_list_max_page_size_is_100_and_101_is_refused(client, store):
    for n in range(105):
        seed_world(store, f"w_a{n:03d}", ALICE, ts=f"2026-09-29T{n // 60:02d}:{n % 60:02d}:00.000Z")
    sign_in(ALICE)
    page = listing(client, limit=MAX_LIMIT).json()
    assert len(page["worlds"]) == MAX_LIMIT
    assert page["next_cursor"] is not None
    assert len(listing(client, limit=1).json()["worlds"]) == 1
    bad = listing(client, limit=MAX_LIMIT + 1)
    assert 400 <= bad.status_code < 500


@pytest.mark.parametrize("limit", ["0", "-1", "abc", "1.5", "101", "100000", ""])
def test_S_14_worlds_list_a_bad_limit_is_a_4xx_in_the_api_error_shape(client, store, limit):
    seed_world(store, "w_a1", ALICE)
    sign_in(ALICE)
    response = client.get("/worlds", params={"limit": limit})
    assert response.status_code in (400, 422)  # BQ-S14-5
    assert "detail" in response.json()  # the shape every route here uses: {"detail": ...}


@pytest.mark.parametrize(
    "cursor",
    ["not-a-cursor", "!!!", "0", "w_a1", "x" * 5000, "%00", "eyJ9"],
    ids=["words", "punctuation", "zero", "a_world_id", "5000_chars", "nul", "short_base64"],
)
def test_S_14_worlds_list_a_bad_cursor_is_a_4xx_in_the_api_error_shape(client, store, cursor):
    seed_world(store, "w_a1", ALICE)
    sign_in(ALICE)
    response = client.get("/worlds", params={"cursor": cursor})
    assert response.status_code in (400, 422)
    assert "detail" in response.json()


def test_S_14_worlds_list_the_cursor_is_opaque_it_does_not_spell_out_a_world_id(client, store):
    for n in range(4):
        seed_world(store, f"w_a{n}", ALICE, ts=f"2026-09-29T09:30:0{n}.000Z")
    sign_in(ALICE)
    cursor = listing(client, limit=2).json()["next_cursor"]
    assert isinstance(cursor, str) and cursor
    assert not any(world_id in cursor for world_id in store.worlds)


def test_S_14_worlds_list_the_last_page_has_no_cursor_and_no_empty_page_follows(client, store):
    for n in range(4):
        seed_world(store, f"w_a{n}", ALICE, ts=f"2026-09-29T09:30:0{n}.000Z")
    sign_in(ALICE)
    first = listing(client, limit=2).json()
    second = listing(client, limit=2, cursor=first["next_cursor"]).json()
    assert len(second["worlds"]) == 2
    assert second["next_cursor"] is None  # exactly full, and nothing left
    assert listing(client, limit=4).json()["next_cursor"] is None
    assert listing(client, limit=3).json()["next_cursor"] is not None


def test_S_14_worlds_list_a_world_created_between_pages_causes_no_duplicate_and_no_gap(client, store):
    for n in range(1, 7):
        seed_world(store, f"w_a{n}", ALICE, ts=f"2026-09-29T09:30:0{n}.000Z")
    sign_in(ALICE)
    first = listing(client, limit=2).json()
    seed_world(store, "w_new", ALICE, ts="2026-09-29T09:30:09.000Z")  # newer than everything: lands before page 1
    seen = [w["world_id"] for w in first["worlds"]]
    cursor = first["next_cursor"]
    while cursor is not None:
        page = listing(client, limit=2, cursor=cursor).json()
        seen += [w["world_id"] for w in page["worlds"]]
        cursor = page["next_cursor"]
    assert seen == ["w_a6", "w_a5", "w_a4", "w_a3", "w_a2", "w_a1"]  # each of the six, once, in order


# --- 2. no cross-user leak, including through cursors --------------------------------------------


def test_S_14_worlds_list_a_cursor_minted_for_one_user_replayed_by_another_shows_none_of_the_first_users_worlds(
    client, store
):
    for n in range(5):
        seed_world(store, f"w_a{n}", ALICE, ts=f"2026-09-29T09:30:0{n}.000Z")
    for n in range(3):
        seed_world(store, f"w_b{n}", BOB, ts=f"2026-09-29T09:31:0{n}.000Z")
    sign_in(ALICE)
    _, cursors = walk(client, 2)
    assert cursors
    sign_in(BOB)
    for cursor in cursors:
        response = listing(client, limit=2, cursor=cursor)
        if response.status_code == 200:
            assert all(w.startswith("w_b") for w in ids(response)), cursor  # none of Alice's, ever
        else:
            assert 400 <= response.status_code < 500 and "detail" in response.json()


def test_S_14_worlds_list_a_tampered_cursor_is_refused_or_stays_inside_the_callers_worlds(client, store):
    for n in range(5):
        seed_world(store, f"w_a{n}", ALICE, ts=f"2026-09-29T09:30:0{n}.000Z")
    for n in range(3):
        seed_world(store, f"w_b{n}", BOB, ts=f"2026-09-29T09:31:0{n}.000Z")
    sign_in(ALICE)
    cursor = listing(client, limit=2).json()["next_cursor"]
    forged = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    response = listing(client, limit=2, cursor=forged)
    assert response.status_code < 500
    if response.status_code == 200:
        assert all(w.startswith("w_a") for w in ids(response))
    # a member replaying the owner's cursor still sees only their own world
    sign_in(CARA, role="viewer", world_id="w_a1")
    response = listing(client, limit=2, cursor=cursor)
    if response.status_code == 200:
        assert set(ids(response)) <= {"w_a1"}


def test_S_14_worlds_list_responses_carry_no_other_users_data_at_all(client, store):
    seed_world(store, "w_a1", ALICE, title="Alice private title", ts=T1)
    seed_world(store, "w_b1", BOB, title="Bob private title", ts=T2)
    sign_in(ALICE)
    response = listing(client)
    assert response.status_code == 200
    text = response.text
    assert "Bob private title" not in text and "w_b1" not in text and BOB not in text


_TS = st.sampled_from([T1, T2, T3, T4])  # few values on purpose: many ties, so the tie-break is exercised


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    a_stamps=st.lists(_TS, max_size=10),
    b_stamps=st.lists(_TS, max_size=10),
    limit=st.integers(min_value=1, max_value=6),
)
def test_S_14_worlds_list_property_pages_have_no_duplicates_no_gaps_and_no_cross_user_leak(
    client, store, a_stamps, b_stamps, limit
):
    store.worlds.clear()
    store.events.clear()
    mine = [(f"w_a{i:02d}", ts) for i, ts in enumerate(a_stamps)]
    theirs = [(f"w_b{i:02d}", ts) for i, ts in enumerate(b_stamps)]
    for world_id, ts in mine:
        seed_world(store, world_id, ALICE, ts=ts)
    for world_id, ts in theirs:
        seed_world(store, world_id, BOB, ts=ts)

    sign_in(ALICE)
    items, alice_cursors = walk(client, limit)
    items = [w for w in items if not w.get("sample")]  # STARTER-1: an owner with no worlds also gets the sample
    assert [w["world_id"] for w in items] == expected_order(mine)  # exactly Alice's, once each, in the pinned order
    assert len(alice_cursors) == (max(math.ceil(len(mine) / limit) - 1, 0))  # a cursor between pages only
    assert all(set(w) == ITEM_KEYS for w in items)

    sign_in(BOB)
    bobs, _ = walk(client, limit)
    bobs = [w for w in bobs if not w.get("sample")]
    assert [w["world_id"] for w in bobs] == expected_order(theirs)
    for cursor in alice_cursors:  # Alice's cursors in Bob's hands: an error, or Bob's own worlds only
        response = listing(client, limit=limit, cursor=cursor)
        if response.status_code == 200:
            assert set(ids(response)) <= {w for w, _ in theirs}
        else:
            assert 400 <= response.status_code < 500
