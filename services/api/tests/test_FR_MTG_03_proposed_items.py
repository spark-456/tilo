"""Offline proposal preparation must retain evidence, privacy and optimistic version guards."""

import copy
import json

import pytest
from _ppl11a_lib import OWNER, SAM, conforms
from test_FR_MTG_03_minutes_publication import publish
from tilo_api.meeting_proposals import prepare_proposed_items
from tilo_api.people_writes import Refusal

pytest_plugins = ["test_FR_MTG_03_minutes_publication"]


def prepare(case, **kwargs):
    rig, writer, _, _ = case
    return prepare_proposed_items(writer, rig.event_store, rig.artifacts, "mt_q4_plan", **kwargs)


def test_FR_MTG_03_prepares_pinned_proposals_without_any_write_or_confirmation(publication):
    rig, _, scope, doc = publication
    publish(publication)
    before = rig.snapshot()
    result = prepare(publication)
    assert result.meeting_version == rig.version_of("meetings", "mt_q4_plan")
    assert result.minutes == rig.stored("meetings", "mt_q4_plan")["minutes"]
    assert result.transcript == doc["transcript"]
    assert result.items
    actions = {row["id"]: row for row in doc["action_items"]}
    for item in result.items:
        assert conforms("work_item.schema.json", item)
        action = actions[item["source"]["ref"].split("#")[1]]
        assert item["title"] == action["text"] and item["owner"] == action["owner"]
        assert item["source"]["evidence"] == action["evidence"]
        assert item["due"] == action["due"] and item["due_text"] == action["due_text"]
        assert item["status"] == "proposed" and item["confirmed_by"] is None
        assert item["assigned_by"]["by"] == OWNER and len(item["history"]) == 1
    assert prepare(publication) == result
    assert rig.snapshot() == before
    assert json.loads(rig.artifacts.read(scope, result.minutes)) == doc


@pytest.mark.parametrize("change", ["unverified", "unresolved", "long_title", "many_quotes"])
def test_FR_MTG_03_ineligible_actions_stay_in_minutes(publication, change):
    _, _, _, doc = publication
    doc["action_items"] = [copy.deepcopy(doc["action_items"][0])]
    action = doc["action_items"][0]
    if change == "unverified":
        action["state"] = "unverified"
    elif change == "unresolved":
        action["owner"] = None
    elif change == "long_title":
        action["text"] = "a" * 141
    else:
        # A schema-valid transcript may contain six supporting utterances.
        rig, _, scope, _ = publication
        transcript = json.loads(rig.artifacts.read(scope, doc["transcript"]))
        utterance = transcript["utterances"][0]
        transcript["utterances"] = [{**utterance, "id": f"u{i:04}"} for i in range(1, 7)]
        made = rig.put_doc(scope, "art_six_quotes", transcript)
        stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
        rig.real.meetings.replace({**stored.record, "transcript": made.ref}, expected_version=stored.version)
        doc["transcript"] = made.ref
        action["evidence"] = [row["id"] for row in transcript["utterances"]]
        doc["summary"], doc["decisions"], doc["agenda"] = [], [], []
        rig._ids = ["art_publication_minutes"]
    publish(publication)
    assert prepare(publication).items == ()


@pytest.mark.parametrize("change", ["owner", "world_owner", "minutes_expired", "transcript_expired", "stale"])
def test_FR_MTG_03_proposals_refuse_scope_retention_and_stale_versions(publication, change):
    rig, writer, scope, _ = publication
    publish(publication)
    kwargs = {}
    if change == "owner":
        writer.actor = SAM
    elif change == "world_owner":
        rig.event_store.worlds[scope.world_id].owner = SAM
    elif change.endswith("expired"):
        field = "delete_minutes_after" if change == "minutes_expired" else "delete_transcript_after"
        writer.now = rig.stored("meetings", "mt_q4_plan")[field]
    else:
        kwargs["expected_version"] = 1
    before = rig.snapshot()
    with pytest.raises(Refusal):
        prepare(publication, **kwargs)
    assert rig.snapshot() == before


def test_FR_MTG_04_proposals_reject_duplicate_action_ids(publication):
    _, _, _, doc = publication
    doc["action_items"].append(copy.deepcopy(doc["action_items"][0]))
    publish(publication)
    with pytest.raises(Refusal):
        prepare(publication)


def test_FR_MTG_03_proposals_recheck_meeting_version_after_artifact_reads(publication, monkeypatch):
    rig, _, _, _ = publication
    publish(publication)
    original = rig.artifacts.read

    def racing_read(*args, **kwargs):
        result = original(*args, **kwargs)
        stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
        rig.real.meetings.replace({**stored.record, "title": "Concurrent edit"}, expected_version=stored.version)
        return result

    monkeypatch.setattr(rig.artifacts, "read", racing_read)
    with pytest.raises(Refusal) as raised:
        prepare(publication)
    assert raised.value.status_code == 409


def test_FR_MTG_03_proposals_propagate_source_flags(publication):
    _, _, _, doc = publication
    doc["flagged"] = True
    publish(publication)
    items = prepare(publication).items
    assert items and all(item["flagged"] for item in items)


@pytest.mark.parametrize("change", ["evidence", "transcript_pin", "meeting_id"])
def test_FR_MTG_04_proposals_reject_tampered_pinned_minutes(publication, change):
    rig, _, scope, _ = publication
    publish(publication)
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    doc = json.loads(rig.artifacts.read(scope, stored.record["minutes"]))
    if change == "evidence":
        doc["action_items"][0]["evidence"] = ["u9999"]
    elif change == "transcript_pin":
        doc["transcript"]["version"] += 1
    else:
        doc["meeting_id"] = "mt_elsewhere"
    made = rig.put_doc(scope, "art_tampered_minutes", doc)
    rig.real.meetings.replace({**stored.record, "minutes": made.ref}, expected_version=stored.version)
    before = rig.snapshot()
    with pytest.raises(Refusal):
        prepare(publication)
    assert rig.snapshot() == before


def test_FR_MTG_05_proposals_do_not_trust_an_owner_id_that_disagrees_with_directory(publication):
    _, _, _, doc = publication
    doc["action_items"] = [copy.deepcopy(doc["action_items"][0])]
    doc["action_items"][0]["owner"] = SAM
    publish(publication)
    assert prepare(publication).items == ()


def test_FR_MTG_03_proposals_recheck_world_ownership_after_reads(publication, monkeypatch):
    rig, _, scope, _ = publication
    publish(publication)
    original = rig.artifacts.read

    def racing_read(*args, **kwargs):
        result = original(*args, **kwargs)
        rig.event_store.worlds[scope.world_id].owner = SAM
        return result

    monkeypatch.setattr(rig.artifacts, "read", racing_read)
    with pytest.raises(Refusal) as raised:
        prepare(publication)
    assert raised.value.status_code == 404
