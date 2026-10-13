"""PEOPLE-SEAMS-1: the Desk and Outpost world makers on the API's own store, and the four seams through the real people
routes (plate, work-item create with a mail source, meeting world). The writer is the real `WorldWriterAdapter` over
the harness' memory events store, so a Desk event is validated as in production. A deployed process with no store
configured stays 503 `not_configured` on every seam. No network."""

from __future__ import annotations

import pytest
from _cards_lib import FakeClock
from _peopleseams1_lib import (
    OTHER,
    OWNER,
    STAMP,
    W1,
    W2,
    card,
    ev,
    mail_doc,
    process,
    rig_with_mail,
    run_with_cards,
    seed_world,
)
from _ppl11a_lib import PRIYA
from _ppl11c_lib import MEETING_BODY
from _pw1b_lib import make_rig
from fastapi import HTTPException
from tilo_api import deps, seams_store
from tilo_api.durable_store import DurableStore
from tilo_api.people_events import WorkEvents

ORG = deps.ORG_ID
PLATE_NOW, CARD_AT = "2026-10-06T10:00:00.000Z", "2026-10-06T09:30:00.000Z"  # the people rig's clock, a fresh card


def _item(owner: str, item_id: str = "wi_ps1a", change: str = "created") -> dict:
    return {
        "id": item_id, "owner": owner, "status": "open", "source": {"kind": "manual", "ref": None},
        "history": [{"at": STAMP, "by": owner, "change": change, "status": "open"}],
    }  # fmt: skip


# -- the Desk world -------------------------------------------------------------------------------------------------


def test_PEOPLE_SEAMS_1_each_person_has_one_desk_world_that_only_they_own():
    store = process(make_rig("memory"))
    desks = seams_store.StoreDeskWorlds(store)
    mine, theirs = desks.desk_world(ORG, OWNER), desks.desk_world(ORG, OTHER)
    assert mine == desks.desk_world(ORG, OWNER) != theirs and mine.startswith("w_desk_")
    assert (desks.desk_owner(mine), desks.desk_owner(theirs)) == (OWNER, OTHER)
    assert [desks.desk_owner(w) for w in ("w_desk_unknown", W1, mine + "\n", "w_desk_", "", None, 7)] == [None] * 7


@pytest.mark.parametrize(
    ("org", "user"), [("org_other", OWNER), (ORG, "u_a\n"), (ORG, "owner"), (ORG, None), (ORG, "u_")]
)
def test_PEOPLE_SEAMS_1_a_desk_world_is_made_only_for_a_valid_person_of_this_org(org, user):
    store = process(make_rig("memory"))
    with pytest.raises(ValueError):
        seams_store.StoreDeskWorlds(store).desk_world(org, user)
    assert store.worlds == {}


def test_PEOPLE_SEAMS_1_a_desk_id_held_by_someone_else_is_never_adopted():
    store = process(make_rig("memory"))
    desks = seams_store.StoreDeskWorlds(store)
    desk_id = desks.desk_world(ORG, OWNER)
    store.worlds[desk_id].owner = OTHER  # the id is held by another owner
    with pytest.raises(HTTPException) as caught:
        desks.desk_world(ORG, OWNER)
    assert caught.value.status_code == 503 and desks.desk_owner(desk_id) == OTHER


def test_PEOPLE_SEAMS_1_work_item_events_go_through_the_real_writer_to_the_owners_own_desk_only():
    rig = make_rig("memory")
    store, writer = rig.process()
    events = WorkEvents(writer, seams_store.StoreDeskWorlds(store))
    events.record(ORG, OWNER, _item(OWNER))
    events.record(ORG, OTHER, _item(OTHER, "wi_ps1b", "done"))
    mine, theirs = (seams_store.StoreDeskWorlds(store).desk_world(ORG, u) for u in (OWNER, OTHER))
    assert [(e["type"], e["seq"], e["vis"]) for e in rig.stream(mine)] == [("work_item.created", 1, [])]
    assert [e["type"] for e in rig.stream(theirs)] == ["work_item.changed"]
    writer.reopen()  # a stopping process releases its leases (SIGTERM, `close_deployed`)
    restarted, writer2 = rig.process()  # the next process makes the same Desk id and continues its stream
    WorkEvents(writer2, seams_store.StoreDeskWorlds(restarted)).record(ORG, OWNER, _item(OWNER, "wi_ps1c", "edited"))
    assert [e["seq"] for e in rig.stream(mine)] == [1, 2] and len(rig.stream(theirs)) == 1


# -- the Outpost world of a meeting ---------------------------------------------------------------------------------


def test_PEOPLE_SEAMS_1_a_meeting_world_is_one_persisted_world_owned_by_the_meetings_owner():
    rig = make_rig("memory")
    store = process(rig)
    maker = seams_store.StoreMeetingWorlds(store)
    world = maker.make_meeting_world(org_id=ORG, owner=OWNER, meeting_id="mt_ps1a")
    assert world.startswith("w_mtg_") and len(world) <= 50
    assert maker.make_meeting_world(org_id=ORG, owner=OWNER, meeting_id="mt_ps1a") == world
    assert maker.make_meeting_world(org_id=ORG, owner=OWNER, meeting_id="mt_ps1b") != world
    assert rig.backend.read("worlds", world)["owner"] == OWNER, "stored, not only cached"
    restarted = seams_store.StoreMeetingWorlds(process(rig))
    assert restarted.make_meeting_world(org_id=ORG, owner=OWNER, meeting_id="mt_ps1a") == world
    with pytest.raises(ValueError):  # the same meeting asked by another owner: the held world is not theirs
        restarted.make_meeting_world(org_id=ORG, owner=OTHER, meeting_id="mt_ps1a")


@pytest.mark.parametrize(
    ("org", "owner", "meeting"),
    [
        ("org_other", OWNER, "mt_a"),
        (ORG, "owner", "mt_a"),
        (ORG, OWNER, "w_a"),
        (ORG, OWNER, "mt_a\n"),
        (ORG, OWNER, ""),
    ],
)
def test_PEOPLE_SEAMS_1_a_meeting_world_is_refused_for_malformed_ids(org, owner, meeting):
    store = process(make_rig("memory"))
    with pytest.raises(ValueError):
        seams_store.StoreMeetingWorlds(store).make_meeting_world(org_id=org, owner=owner, meeting_id=meeting)
    assert store.worlds == {}


def test_PEOPLE_SEAMS_1_two_instances_racing_to_make_a_meeting_world_end_with_one_world():
    rig = make_rig("memory")
    first, second = process(rig), process(rig)
    real_commit = second.commit

    def lost_race(**kwargs):
        seams_store.StoreMeetingWorlds(first).make_meeting_world(org_id=ORG, owner=OWNER, meeting_id="mt_ps1a")
        second.commit = real_commit
        real_commit(**kwargs)  # the world now exists: a create is a 409 `stale`

    second.commit = lost_race
    won = seams_store.StoreMeetingWorlds(first).make_meeting_world(org_id=ORG, owner=OWNER, meeting_id="mt_ps1a")
    rig2 = seams_store.StoreMeetingWorlds(process(rig))
    assert rig2.make_meeting_world(org_id=ORG, owner=OWNER, meeting_id="mt_ps1a") == won


# -- through the real routes ----------------------------------------------------------------------------------------


def _wired(people_rig, store: DurableStore, writer, *unwire: str):
    rig = people_rig()
    rig.add_people()
    overrides = rig.app.dependency_overrides
    overrides[deps.get_store] = lambda: store
    overrides[deps.get_event_writer] = lambda: writer
    rig.unwire(*unwire)
    return rig


def test_PEOPLE_SEAMS_1_the_plate_route_shows_only_the_signed_in_persons_cards_and_runs(people_rig):
    store = process(make_rig("memory"))
    clock = FakeClock(PLATE_NOW)
    for world, owner in ((W1, PRIYA), (W2, OWNER)):
        seed_world(store, world, owner, goal=f"Goal of {owner}")
        store.events[world] = [ev("world.started")]
        blocked = card(world, ord(world[-1]), name="needs_you_blocked", created_at=CARD_AT)
        assert run_with_cards(store, world, owner, clock).submit(blocked)
    rig = _wired(people_rig, store, None, "plate_sources", "source_owners")
    rig.as_user(PRIYA)
    plate = rig.plate().json()
    refs = {(r["ref"]["kind"], r["ref"]["id"]) for r in plate["rows"]}
    assert ("world", W1) in refs and ("world", W2) not in refs
    assert {r["ref"]["id"] for r in plate["rows"] if r["ref"]["kind"] == "card"} == {card(W1, ord(W1[-1]))["id"]}
    assert "Goal of u_owner" not in str(plate)


def test_PEOPLE_SEAMS_1_a_viewer_of_someone_elses_world_gets_nothing_of_it_on_their_plate(people_rig):
    store = process(make_rig("memory"))
    seed_world(store, W2, OWNER, goal="Secret goal")
    store.events[W2] = [ev("world.started")]
    run_with_cards(store, W2, OWNER, FakeClock(PLATE_NOW)).submit(
        card(W2, 9, name="needs_you_blocked", created_at=CARD_AT)
    )
    rig = _wired(people_rig, store, None, "plate_sources", "source_owners")
    rig.as_user(PRIYA, role="viewer", world_id=W2)  # a Viewer principal naming the owner's world
    plate = rig.plate().json()
    assert plate["user"] == PRIYA and plate["rows"] == [] and "Secret" not in str(plate)


def test_PEOPLE_SEAMS_1_a_work_item_with_a_mail_source_needs_the_signed_in_persons_own_mail(people_rig):
    rig_store, _ = rig_with_mail([mail_doc(PRIYA, "m1"), mail_doc(OWNER, "m2")])
    store, writer = rig_store.process()
    rig = _wired(people_rig, store, writer, "source_owners", "desk_worlds")
    rig.as_user(PRIYA)
    body = {"title": "Reply to Sam", "source": {"kind": "mail", "ref": "m1"}}
    assert rig.post("/v1/work-items", body).status_code == 201
    desk_id = seams_store.StoreDeskWorlds(store).desk_world(deps.ORG_ID, PRIYA)
    assert [e["type"] for e in rig_store.stream(desk_id)] == ["work_item.created"]
    for ref in ("m2", "nobody"):  # another person's message, and one nobody holds: the same refusal
        refused = rig.post("/v1/work-items", {"title": "Reply", "source": {"kind": "mail", "ref": ref}})
        assert refused.status_code == 422 and refused.json()["detail"] == "source_not_found", ref
    assert len(rig_store.stream(desk_id)) == 1


def test_PEOPLE_SEAMS_1_the_meeting_world_route_makes_the_owners_world_and_nobody_elses(people_rig):
    rig_store = make_rig("memory")
    store = process(rig_store)
    rig = _wired(people_rig, store, None, "meeting_worlds")
    rig.as_user(PRIYA)
    meeting_id = rig.post("/v1/meetings", MEETING_BODY).json()["id"]
    first = rig.post(f"/v1/meetings/{meeting_id}/world")
    assert first.status_code == 200 and first.json()["world_id"].startswith("w_mtg_"), first.text[:200]
    world_id = first.json()["world_id"]
    assert rig_store.backend.read("worlds", world_id)["owner"] == PRIYA
    assert rig.post(f"/v1/meetings/{meeting_id}/world").json()["world_id"] == world_id
    rig.as_user(OWNER)  # another person asks for the same meeting: a plain 404, and no world is made for them
    assert rig.post(f"/v1/meetings/{meeting_id}/world").status_code == 404
    assert list(rig_store.backend.docs) == [("worlds", world_id)]


# -- not configured -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("seam", ["get_plate_sources", "get_source_owners", "get_desk_worlds", "get_meeting_worlds"])
def test_PEOPLE_SEAMS_1_a_deployed_process_with_no_store_config_answers_503_not_configured(monkeypatch, seam):
    for name in ("TILO_API_STORE", "TILO_FIRESTORE_PROJECT", "FIRESTORE_EMULATOR_HOST", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    with pytest.raises(HTTPException) as caught:
        getattr(deps, seam)()
    assert (caught.value.status_code, caught.value.detail) == (503, "not_configured")
