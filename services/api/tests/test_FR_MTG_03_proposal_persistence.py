"""Offline guarded linking and bounded compensation across independent stores."""

import json

import pytest
from _ppl11c_lib import artifact_paths, gone_meeting
from test_FR_MTG_03_minutes_publication import publish
from test_FR_MTG_03_proposed_items import prepare
from tilo_api.meeting_proposals import persist_proposed_items
from tilo_api.people_events import WorkEvents
from tilo_api.people_writes import Refusal, confirm_item, confirm_minutes

pytest_plugins = ["test_FR_MTG_03_minutes_publication"]


def ready(case):
    rig, writer, _, _ = case
    publish(case)
    writer.events = WorkEvents(rig.events, rig.desks)
    rig._ids = ["art_linked_minutes"]
    return prepare(case)


def persist(case, batch):
    rig, writer, _, _ = case
    return persist_proposed_items(writer, rig.event_store, rig.artifacts, "mt_q4_plan", batch)


def test_FR_MTG_03_persistence_links_proposed_items_without_confirmation(publication):
    rig, _, scope, doc = publication
    batch = ready(publication)
    after = persist(publication, batch)
    linked = json.loads(rig.artifacts.read(scope, after["minutes"]))
    assert after["minutes_confirmed_by"] is None and after["transcript"] == batch.transcript
    for item in batch.items:
        assert rig.stored("work_items", item["id"]) == item
        action = next(row for row in linked["action_items"] if row["id"] == item["source"]["ref"].split("#")[1])
        assert action["work_item_id"] == item["id"]
        assert item["status"] == "proposed" and item["confirmed_by"] is None
    assert json.loads(rig.artifacts.read(scope, batch.minutes)) == doc
    assert prepare(publication).items == ()


@pytest.mark.parametrize("change", ["batch", "confirmation", "deleted", "stale", "world"])
def test_FR_MTG_03_persistence_revalidates_snapshot_before_writes(publication, change):
    rig, writer, scope, _ = publication
    batch = ready(publication)
    if change == "batch":
        batch.items[0]["title"] = "Forged action"
    elif change == "confirmation":
        confirm_minutes(writer, "mt_q4_plan")
    elif change in ("deleted", "stale"):
        stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
        after = (
            gone_meeting(dict(stored.record), "deleted") if change == "deleted" else {**stored.record, "title": "Edit"}
        )
        rig.real.meetings.replace(after, expected_version=stored.version)
    else:
        rig.event_store.worlds[scope.world_id].owner = "u_someone_else"
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal):
        persist(publication, batch)
    assert rig.snapshot() == before and artifact_paths(rig) == paths


@pytest.mark.parametrize("change", ["deleted", "confirmation", "event", "artifact"])
def test_FR_MTG_03_persistence_compensates_boundary_failures(publication, monkeypatch, change):
    rig, writer, _, _ = publication
    batch = ready(publication)
    before = rig.stored("meetings", "mt_q4_plan")
    paths = artifact_paths(rig)
    if change == "artifact":

        def fail(*args, **kwargs):
            raise RuntimeError("offline unavailable")

        monkeypatch.setattr(rig.artifacts, "put", fail)
    else:
        original = writer.events.record

        def race(*args):
            if change == "event":
                raise RuntimeError("offline unavailable")
            original(*args)
            if change == "confirmation":
                confirm_minutes(writer, "mt_q4_plan")
            else:
                stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
                rig.real.meetings.replace(gone_meeting(dict(stored.record), "deleted"), expected_version=stored.version)

        monkeypatch.setattr(WorkEvents, "record", lambda self, *args: race(*args))
    with pytest.raises(Refusal):
        persist(publication, batch)
    assert all(rig.real.work_items.get(rig.org, row["id"]) is None for row in batch.items)
    assert artifact_paths(rig) == paths
    current = rig.stored("meetings", "mt_q4_plan")
    assert current["status"] == "deleted" if change == "deleted" else current["minutes"] == before["minutes"]
    if change == "confirmation":
        assert current["minutes_confirmed_by"] == writer.stamp()


def test_FR_MTG_03_persistence_rollback_preserves_racing_item_confirmation(publication, monkeypatch):
    rig, writer, _, _ = publication
    batch = ready(publication)
    original = writer.events.record
    fired = False

    def race(self, *args):
        nonlocal fired
        original(*args)
        if not fired:
            fired = True
            confirm_item(writer, args[-1]["id"])
            confirm_minutes(writer, "mt_q4_plan")

    monkeypatch.setattr(WorkEvents, "record", race)
    with pytest.raises(Refusal):
        persist(publication, batch)
    saved = rig.stored("work_items", batch.items[0]["id"])
    assert saved["status"] == "open" and saved["confirmed_by"] == writer.stamp()


@pytest.mark.parametrize("change", ["confirmation", "confirmation_lost_ack", "deleted", "world"])
def test_FR_MTG_03_persistence_preserves_consumed_links_after_final_cas(publication, monkeypatch, change):
    rig, writer, scope, _ = publication
    batch = ready(publication)
    original = rig.stores.meetings.replace
    fired = False

    def race(record, *, expected_version):
        nonlocal fired
        result = original(record, expected_version=expected_version)
        if not fired and record["minutes"] != batch.minutes:
            fired = True
            if change.startswith("confirmation"):
                confirm_minutes(writer, "mt_q4_plan")
                if change == "confirmation_lost_ack":
                    raise RuntimeError("offline lost acknowledgement")
            elif change == "deleted":
                original(gone_meeting(dict(record), "deleted"), expected_version=result.version)
            else:
                rig.event_store.worlds[scope.world_id].owner = "u_someone_else"
        return result

    monkeypatch.setattr(rig.stores.meetings, "replace", race)
    with pytest.raises(Refusal):
        persist(publication, batch)
    current = rig.stored("meetings", "mt_q4_plan")
    if change.startswith("confirmation"):
        assert current["minutes_confirmed_by"] == writer.stamp()
        doc = json.loads(rig.artifacts.read(scope, current["minutes"]))
        linked = {row["work_item_id"] for row in doc["action_items"] if row["work_item_id"]}
        assert linked == {row["id"] for row in batch.items}
        assert all(rig.real.work_items.get(rig.org, item_id) is not None for item_id in linked)
    else:
        assert all(rig.real.work_items.get(rig.org, row["id"]) is None for row in batch.items)


def test_FR_MTG_03_persistence_stale_link_cas_never_overwrites_edit(publication):
    rig, _, _, _ = publication
    batch = ready(publication)
    before, paths = rig.stored("meetings", "mt_q4_plan"), artifact_paths(rig)
    rig.conflicting_stores("meetings")
    with pytest.raises(Refusal) as raised:
        persist(publication, batch)
    assert raised.value.status_code == 409
    assert rig.stored("meetings", "mt_q4_plan") == before and artifact_paths(rig) == paths
    assert all(rig.real.work_items.get(rig.org, row["id"]) is None for row in batch.items)
