"""WORLDS-MANAGE (owner ask, 21 Oct 2026): `DELETE /worlds/{world_id}` takes a world off its owner's Worlds list.

Owner only, on a full web sign-in bound to no world; anyone else, a missing world and a teammate get the one 404.
A world still at work is a 409 (no single-world stop event exists: the person pauses it first), and so is a world
whose meeting bot is still booked. Nothing is erased and no event is written: the record stays (flagged `hidden`), its
events stay, and only the lists stop showing it.

Security review (21 Oct): a deleted world is then gone everywhere (every route naming it is the unknown 404, share
links are revoked, `/costs` still counts and labels its spend), it is stopped like a paused one (no run starts, a run
writes nothing, the outbox sweep holds its entries), and the delete re-checks the status under the locks and commits a
copy, never changing the shared record in place.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _api_lib import as_principal
from _peopleseams1_lib import directory
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test_FR_HIL_12_approver_share_links import APPROVER, APPROVER_P, LEAD, OTHER, OWNER, VIEWER, World
from test_S_14_worlds_list import ALICE, BOB, ids, listing, seed_world
from tilo_api import _world_views, app, cards, deps, runs, schedules, sharing, world_delete
from tilo_api.durable_store import _plain, _world_from
from tilo_api.sample_world import SAMPLE_WORLD_ID
from tilo_metering import LedgerEntry
from tilo_people.stores import PeopleStores

UNKNOWN = {"detail": "Tilo could not find that."}
WORKING = {"detail": "This world is still working. Pause it first, then delete it."}
MEETING_FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "meeting" / "valid"


@pytest.fixture(autouse=True)
def people():
    """The people stores the route reads for a booked meeting: in memory, empty unless a test books one."""
    stores = PeopleStores.in_memory()
    app.dependency_overrides[deps.get_people_stores] = lambda: stores
    yield stores
    app.dependency_overrides.pop(deps.get_people_stores, None)


def owner(user: str = ALICE, **over) -> None:
    as_principal(deps.Principal(user_id=user, role="owner", world_id=None, full_session=True, **over))


def book(people: PeopleStores, world_id: str, fixture: str, meeting_id: str) -> None:
    """A meeting of ALICE's, from a valid contract fixture, naming `world_id`."""
    meeting = json.loads((MEETING_FIXTURES / fixture).read_text(encoding="utf-8"))
    meeting.update(id=meeting_id, org_id=deps.ORG_ID, owner=ALICE, world_id=world_id)
    people.meetings.create(meeting)


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
    assert client.delete("/worlds/w_gone").json() == UNKNOWN  # deleting again: the world is gone


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

    assert busy.status_code == 409 and busy.json() == WORKING
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
    store.worlds["w_shared"] = deps.WorldRecord(owner=ALICE, districts={}, hidden=True)
    teammate = deps.Principal(user_id=BOB, role="owner", world_id=None, full_session=True)
    with pytest.raises(HTTPException) as refused:
        deps.team_reader(teammate, store, lambda: None, lambda: "2026-10-21T00:00:00Z", "w_shared")
    assert refused.value.status_code == 404


# --- MEDIUM 1: nothing keeps going for a world nobody can open ---------------------------------------------------


def test_WORLDS_MANAGE_a_world_whose_meeting_bot_is_still_booked_is_refused(client, store, people):
    seed_world(store, "w_meet", ALICE, after=("world.started", "world.completed"))
    seed_world(store, "w_minuted", ALICE, after=("world.started", "world.completed"))
    book(people, "w_meet", "bot_live.json", "mt_live")  # its bot is in the call now
    book(people, "w_minuted", "upload_minuted_with_world.json", "mt_done")  # this meeting is over
    owner()

    booked = client.delete("/worlds/w_meet")

    assert booked.status_code == 409
    assert booked.json()["detail"].startswith("A meeting for this world is still booked or under way.")
    assert store.worlds["w_meet"].hidden is False
    assert client.delete("/worlds/w_minuted").status_code == 204


def test_WORLDS_MANAGE_a_people_store_that_cannot_be_read_is_a_503_never_a_guess(client, store):
    seed_world(store, "w_x", ALICE, after=("world.started", "world.completed"))

    def unreadable():
        raise HTTPException(status_code=503, detail="not_configured")

    app.dependency_overrides[deps.get_people_stores] = unreadable
    owner()

    response = client.delete("/worlds/w_x")

    assert response.status_code == 503
    assert response.json() == {"detail": "Tilo could not check this world's meetings. Try again."}
    assert store.worlds["w_x"].hidden is False


def test_WORLDS_MANAGE_a_deleted_world_is_stopped_like_a_paused_one(store, monkeypatch):
    store.worlds["w_gone"] = deps.WorldRecord(owner=ALICE, districts={}, hidden=True)
    store.worlds["w_live"] = deps.WorldRecord(owner=ALICE, districts={})

    # a run still holding it writes nothing more, and its browser step (which asks the same) ends
    assert runs.Run.paused(cast(Any, SimpleNamespace(store=store, world_id="w_gone"))) is True
    assert runs.Run.paused(cast(Any, SimpleNamespace(store=store, world_id="w_live"))) is False

    # no run starts in it (a routine's slot, an approve, a rerun all go through start_run)
    task = deps.TaskRecord(ALICE, "w_gone", "r_gone", {}, {}, [], 3)
    runs.start_run(store, task, approach={}, budget_cap=1.0, seams=cast(Any, None))
    assert "w_gone" not in store.runs

    # the Scheduler's outbox sweep holds its unsent entries, as it does a paused world's
    seen: dict[str, Any] = {}
    monkeypatch.setenv("TILO_OUTBOX_STORE", "firestore")
    monkeypatch.setattr(
        "tilo_api.outbox_firestore.sweep_due", lambda _s, _a, _c, paused, **_kw: seen.update(paused=paused)
    )
    overrides = {deps.get_outbox_store: lambda: object(), deps.get_connector_adapters: lambda: {}}
    request = SimpleNamespace(app=SimpleNamespace(dependency_overrides=overrides))
    schedules._sweep_outbox(cast(Any, request), lambda: datetime(2026, 10, 21, tzinfo=UTC), lambda: store)
    assert seen["paused"]("w_gone") is True and seen["paused"]("w_live") is False


# --- MEDIUM 2: a deleted world is gone, through any old link ---------------------------------------------------------


def test_WORLDS_MANAGE_every_route_naming_a_deleted_world_is_the_unknown_world_404(client, store):
    seed_world(store, "w_gone", ALICE, after=("world.started", "world.completed"))
    owner()
    assert client.get("/worlds/w_gone/events").status_code == 200
    assert client.delete("/worlds/w_gone").status_code == 204

    for path in ("", "/events", "/layout", "/result", "/cards", "/delivery"):
        response = client.get(f"/worlds/w_gone{path}")
        assert response.status_code == 404 and response.json() == UNKNOWN, path
    assert client.post("/worlds/w_gone/rerun", json={}).json() == UNKNOWN

    # a session bound to it (an old signed link) reads nothing either
    as_principal(deps.Principal(user_id=ALICE, role="owner", world_id="w_gone", full_session=True))
    for path in ("/events", "/costs", "/cards"):
        assert client.get(f"/worlds/w_gone{path}").json() == UNKNOWN, path
    with pytest.raises(HTTPException):
        deps.member_world(deps.Principal(user_id=ALICE, role="owner", world_id="w_gone"), store, "w_gone")

    # someone not signed in still gets the route's own 401: nobody learns which ids were deleted
    def signed_out():
        raise HTTPException(status_code=401, detail="Sign in to use this.")

    app.dependency_overrides[deps.get_current_principal] = signed_out
    assert client.get("/worlds/w_gone/events").status_code == 401


class DeletableWorld(World):
    """FR-HIL-12's one-gate world, served through a resolver that says whether its owner deleted it."""

    hidden = False

    @property
    def http(self) -> TestClient:
        if self._http is None:
            shared = FastAPI()
            shared.include_router(cards.build_router(self.store))
            shared.include_router(
                sharing.build_router(lambda: lambda _w: sharing.WorldView(self.store, hidden=self.hidden))
            )
            shared.dependency_overrides[deps.get_current_principal] = self._principal
            people = directory(OWNER, APPROVER, OTHER, LEAD, VIEWER)
            shared.dependency_overrides[deps.get_people_stores] = lambda: people
            self._http = TestClient(shared)
        return self._http


def test_WORLDS_MANAGE_a_share_link_into_a_deleted_world_is_revoked(store):
    gate = DeletableWorld()
    link = gate.shared()
    assert gate.open(APPROVER_P, link["token"]).status_code == 200

    gate.hidden = True  # the owner deleted the world

    assert gate.open(APPROVER_P, link["token"]).status_code == 410
    assert gate.answer(APPROVER_P, link["token"]).status_code == 410
    store.worlds["w_gone"] = deps.WorldRecord(owner=ALICE, districts={}, hidden=True)
    store.worlds["w_live"] = deps.WorldRecord(owner=ALICE, districts={})
    views = _world_views(store)
    assert views("w_gone").hidden is True and views("w_live").hidden is False  # the app's own resolver says so


def test_WORLDS_MANAGE_costs_still_count_a_deleted_worlds_spend_and_label_it(client, store):
    seed_world(store, "w_spent", ALICE, after=("world.started", "world.completed"))
    seed_world(store, "w_kept", ALICE, after=("world.started", "world.completed"))
    store.worlds["w_spent"] = dataclasses.replace(store.worlds["w_spent"], run_id="r_spent")
    store.worlds["w_kept"] = dataclasses.replace(store.worlds["w_kept"], run_id="r_kept")
    at = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    ledger = [
        LedgerEntry("commit", run, ALICE, deps.ORG_ID, at, step="s1", credits=4.0) for run in ("r_spent", "r_kept")
    ]
    app.dependency_overrides[deps.get_ledger] = lambda: ledger
    owner()
    assert client.delete("/worlds/w_spent").status_code == 204

    report = client.get("/costs").json()

    tasks = {t["run_id"]: t for t in report["tasks"]}
    assert tasks["r_spent"]["world_deleted"] is True  # spent before the delete, still counted, said plainly
    assert "world_deleted" not in tasks["r_kept"]
    assert report["totals"]["credits"] == 8.0


# --- LOW 3: the status is read again under the locks, and the shared record is never changed in place ---------------


def test_WORLDS_MANAGE_a_start_landing_between_the_check_and_the_commit_is_refused(client, store, monkeypatch):
    seed_world(store, "w_race", ALICE)  # requested, nothing running: the first check passes

    def a_run_starts_meanwhile(_people, _owner, world_id):
        store.runs[world_id] = object()
        return False

    monkeypatch.setattr(world_delete, "_meeting_booked", a_run_starts_meanwhile)
    owner()

    response = client.delete("/worlds/w_race")

    assert response.status_code == 409 and response.json() == WORKING
    assert store.worlds["w_race"].hidden is False


def test_WORLDS_MANAGE_the_delete_commits_a_copy_and_a_refused_commit_leaves_the_record_as_it_was(
    client, store, monkeypatch
):
    seed_world(store, "w_a", ALICE, after=("world.started", "world.completed"))
    seed_world(store, "w_b", ALICE, after=("world.started", "world.completed"))
    a, b = store.worlds["w_a"], store.worlds["w_b"]
    owner()

    assert client.delete("/worlds/w_a").status_code == 204
    assert a.hidden is False and store.worlds["w_a"] is not a and store.worlds["w_a"].hidden is True

    def unavailable(**_records):
        raise HTTPException(status_code=503, detail="store_unavailable")

    monkeypatch.setattr(store, "commit", unavailable)
    assert client.delete("/worlds/w_b").status_code == 503
    assert store.worlds["w_b"] is b and b.hidden is False  # nothing to roll back: nothing was changed

    monkeypatch.setattr(store, "commit", lambda **_records: None)  # a kill switch's cached record won the write
    changed = client.delete("/worlds/w_b")
    assert changed.status_code == 409
    assert changed.json() == {"detail": "This world changed while it was being deleted. Try again."}
