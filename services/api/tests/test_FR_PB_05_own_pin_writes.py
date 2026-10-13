"""Caller-owned pin writes: existing schemas, oracle, CAS and Desk events."""

import json

import pytest
from _api_lib import FlakyEventWriter
from _ppl11a_lib import CONTRACTS, DEV, OWNER, PRIYA, SAM
from _ppl11c_lib import assert_gated, stamped, validate_event


def create(rig, **fields):
    return rig.post("/v1/pinboards", {"title": "My recorded note", **fields})


def test_FR_PB_02_create_private_pin_and_remove_records_existing_events(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    answer = create(rig)
    assert answer.status_code == 201
    pin = answer.json()
    assert pin["scope"] == {"kind": "personal", "user": PRIYA}
    assert pin["set_up_by"] == PRIYA and pin["owner"] is None
    assert pin["created_by"]["ref"] == PRIYA and pin["status"] == "active"
    removed = rig.post(f"/v1/pinboards/{pin['id']}/delete", {})
    assert removed.status_code == 200
    assert removed.json()["status"] == "removed"
    assert removed.json()["history"][-1]["change"] == "removed"
    events = stamped(rig, "w_desk_priya")
    assert [e["type"] for e in events] == ["pinboard.item_added", "pinboard.item_changed"]
    assert all(e["vis"] == [] and "My recorded note" not in str(e) for e in events)
    for event in events:
        validate_event(event)
    assert rig.get("/v1/pinboards").json()["items"] == []


@pytest.mark.parametrize("actor", [DEV, OWNER, SAM])
def test_FR_PB_05_another_person_never_removes_private_pin(people_rig, actor):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    answer = create(rig)
    assert answer.status_code == 201
    rig.as_user(actor)
    before = rig.snapshot()
    refused = rig.post(f"/v1/pinboards/{answer.json()['id']}/delete", {})
    assert refused.status_code == 404
    assert rig.snapshot() == before


def test_FR_PB_05_pin_writes_keep_auth_declaration_and_required_event_seams(people_rig):
    routes = [("POST", "/v1/pinboards"), ("POST", "/v1/pinboards/{pin_id}/delete")]
    assert_gated(people_rig, routes)
    for seam in ("people_stores", "event_writer", "desk_worlds"):
        rig = people_rig()
        rig.add_people()
        rig.as_user(PRIYA)
        rig.unwire(seam)
        before = rig.snapshot()
        for path, body in [("/v1/pinboards", {"title": "Note"}), ("/v1/pinboards/pb_missing/delete", {})]:
            answer = rig.post(path, body)
            assert answer.status_code == 503
            assert answer.json() == {"detail": "not_configured"}
        assert rig.snapshot() == before


def test_FR_PB_05_removed_membership_refuses_setter_and_cas_loss_writes_no_event(people_rig, monkeypatch):
    from tilo_people.errors import VersionConflict

    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    answer = create(rig, team="tm_launch")
    assert answer.status_code == 201
    pin_id = answer.json()["id"]
    person = rig.stored("persons", PRIYA)
    person["memberships"] = []
    rig.real.persons.replace(person, expected_version=1)
    assert rig.post(f"/v1/pinboards/{pin_id}/delete", {}).status_code == 404
    private = create(rig)
    assert private.status_code == 201
    before = rig.snapshot()
    events = stamped(rig, "w_desk_priya")

    def conflict(*args, **kwargs):
        raise VersionConflict()

    monkeypatch.setattr(rig.stores.pins, "replace", conflict)
    assert rig.post(f"/v1/pinboards/{private.json()['id']}/delete", {}).status_code == 409
    assert rig.snapshot() == before
    assert stamped(rig, "w_desk_priya") == events


def test_FR_PB_06_tilo_personal_remove_requires_own_source_and_records_undo(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    pin = json.loads((CONTRACTS / "fixtures/pinboard_item/valid/personal_added_by_tilo.json").read_text())
    pin["source"] = {"kind": "request", "ref": "req_own", "evidence": []}
    rig.add("pins", pin)
    path = f"/v1/pinboards/{pin['id']}/delete"
    assert rig.post(path, {}).status_code == 404
    rig.owners.owners[("request", "req_own")] = OWNER
    answer = rig.post(path, {})
    assert answer.status_code == 200
    assert answer.json()["history"][-1]["change"] == "undone"
    assert answer.json()["source"] == pin["source"]
    event = stamped(rig, "w_desk_owner")[0]
    validate_event(event)
    assert event["data"]["change"] == "undone"


def test_FR_PB_01_team_creation_needs_membership_and_setter_alone_can_remove(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(SAM)
    assert create(rig, team="tm_launch").status_code == 403
    rig.as_user(PRIYA)
    answer = create(rig, team="tm_launch")
    assert answer.status_code == 201
    pin = answer.json()
    assert pin["scope"] == {"kind": "team", "team": "tm_launch"}
    rig.as_user(DEV)
    assert rig.post(f"/v1/pinboards/{pin['id']}/delete", {}).status_code == 404
    rig.as_user(PRIYA)
    assert rig.post(f"/v1/pinboards/{pin['id']}/delete", {}).status_code == 200


def test_FR_PB_05_closed_body_and_idempotency_preserve_server_identity(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    for field in ("id", "org_id", "scope", "set_up_by", "status", "owner"):
        assert create(rig, **{field: OWNER}).status_code == 422
    headers = {"Idempotency-Key": "own-pin"}
    first = rig.post("/v1/pinboards", {"title": "One pin"}, headers=headers)
    assert first.status_code == 201
    second = rig.post("/v1/pinboards", {"title": "One pin"}, headers=headers)
    assert second.json() == first.json()
    assert len(stamped(rig, "w_desk_priya")) == 1


def test_FR_PB_05_event_failure_undoes_create_and_delete(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    rig.events = FlakyEventWriter(rig.event_store, failing=True)
    before = rig.snapshot()
    assert create(rig).status_code == 503
    assert rig.snapshot() == before
    rig.events.failing = False
    answer = create(rig)
    assert answer.status_code == 201
    before = rig.snapshot()
    rig.events.failing = True
    assert rig.post(f"/v1/pinboards/{answer.json()['id']}/delete", {}).status_code == 503
    # Existing CAS rollback restores every byte of content while advancing the revision twice.
    expected = json.loads(before)
    expected["pins"][answer.json()["id"]][0] += 2
    before = json.dumps(expected, sort_keys=True)
    assert rig.snapshot() == before
