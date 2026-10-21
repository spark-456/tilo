"""WORLDS-MANAGE (owner ask, 21 Oct 2026): `DELETE /worlds/{world_id}` takes a world off its owner's Worlds list.

Owner only, on a full web sign-in bound to no world; anyone else, a missing world and a teammate get the one 404.
A world still at work is a 409 (no single-world stop event exists: the person pauses it first). Nothing is erased
and no event is written: the record stays (flagged `hidden`), its events stay, and only the lists stop showing it.
"""

from __future__ import annotations

from _api_lib import as_principal
from test_S_14_worlds_list import ALICE, BOB, ids, listing, seed_world
from tilo_api import deps
from tilo_api.durable_store import _plain, _world_from
from tilo_api.sample_world import SAMPLE_WORLD_ID

UNKNOWN = {"detail": "Tilo could not find that."}


def owner(user: str = ALICE, **over) -> None:
    as_principal(deps.Principal(user_id=user, role="owner", world_id=None, full_session=True, **over))


def test_WORLDS_MANAGE_owner_deletes_a_world_and_it_leaves_the_list(client, store):
    seed_world(store, "w_keep", ALICE, after=("world.started", "world.completed"))
    seed_world(store, "w_gone", ALICE, after=("world.started", "world.failed"))
    events_before = [dict(e) for e in store.events["w_gone"]]
    owner()

    response = client.delete("/worlds/w_gone")

    assert response.status_code == 204, response.text
    assert ids(listing(client)) == ["w_keep"]
    assert store.worlds["w_gone"].hidden is True  # the record stays: nothing is erased
    assert store.events["w_gone"] == events_before  # and no event is written
    again = client.delete("/worlds/w_gone")
    assert again.status_code == 204  # deleting again changes nothing


def test_WORLDS_MANAGE_anyone_but_the_owners_full_session_gets_the_one_unknown_world_404(client, store):
    seed_world(store, "w_alice", ALICE, after=("world.started", "world.completed"))
    for who in (
        lambda: owner(BOB),  # another person
        lambda: as_principal(deps.Principal(user_id=ALICE, role="owner", world_id=None)),  # not a full session
        lambda: owner(demo_session=True),
        lambda: owner(channel="email"),
        lambda: as_principal(
            deps.Principal(user_id=ALICE, role="owner", world_id="w_alice", full_session=True)
        ),  # a world-bound session
        lambda: as_principal(deps.Principal(user_id=ALICE, role="viewer", world_id=None, full_session=True)),
    ):
        who()
        response = client.delete("/worlds/w_alice")
        assert response.status_code == 404 and response.json() == UNKNOWN
    owner(BOB)
    assert client.delete("/worlds/w_nobody").json() == UNKNOWN  # an unknown id reads the same
    owner()
    assert ids(listing(client)) == ["w_alice"]
    assert store.worlds["w_alice"].hidden is False


def test_WORLDS_MANAGE_a_world_still_at_work_is_refused_until_it_is_paused(client, store):
    seed_world(store, "w_busy", ALICE, after=("world.started",))
    owner()

    busy = client.delete("/worlds/w_busy")

    assert busy.status_code == 409
    assert busy.json() == {"detail": "This world is still working. Pause it first, then delete it."}
    assert store.worlds["w_busy"].hidden is False
    seed_world(store, "w_busy", ALICE, after=("world.started", "world.paused"))
    assert client.delete("/worlds/w_busy").status_code == 204


def test_WORLDS_MANAGE_a_world_being_planned_is_refused(client, store):
    seed_world(store, "w_planning", ALICE)  # requested, nothing started yet
    store.runs["w_planning"] = object()  # the Director is still planning it
    owner()
    assert client.delete("/worlds/w_planning").status_code == 409
    del store.runs["w_planning"]
    assert client.delete("/worlds/w_planning").status_code == 204


def test_WORLDS_MANAGE_the_sample_is_a_replay_not_a_world_to_delete(client):
    owner()
    response = client.delete(f"/worlds/{SAMPLE_WORLD_ID}")
    assert response.status_code == 409 and response.json() == {"detail": "sample_is_a_replay"}


def test_WORLDS_MANAGE_the_hidden_flag_is_stored_and_an_old_doc_reads_as_listed():
    record = deps.WorldRecord(owner=ALICE, districts={}, hidden=True)
    stored = _plain(record)
    assert _world_from(stored).hidden is True
    del stored["hidden"]  # a world stored before the flag existed
    assert _world_from(stored).hidden is False


def test_WORLDS_MANAGE_a_hidden_world_is_not_offered_to_a_teammate(store):
    from fastapi import HTTPException

    store.worlds["w_shared"] = deps.WorldRecord(owner=ALICE, districts={}, hidden=True)
    teammate = deps.Principal(user_id=BOB, role="owner", world_id=None, full_session=True)
    try:
        deps.team_reader(teammate, store, lambda: None, lambda: "2026-10-21T00:00:00Z", "w_shared")
    except HTTPException as refused:
        assert refused.status_code == 404
    else:  # pragma: no cover - the refusal is the test
        raise AssertionError("a hidden world must not be read by a team reader")
