"""Offline publication of analysed Minutes: pinned evidence, owner review, no follow-up release."""

import copy
import json
from datetime import datetime, timedelta

import pytest
from _mtg09b_lib import block_network
from _ppl11a_lib import OWNER, SAM, conforms
from _ppl11c_lib import artifact_paths, gone_meeting, meeting_rig, transcript_case
from tilo_api.deps import WorldRecord
from tilo_api.meeting_minutes import publish_minutes
from tilo_api.people_writes import Refusal, Writer
from tilo_memory.artifacts import Scope


@pytest.fixture
def publication(people_rig, monkeypatch):
    block_network(monkeypatch)
    rig = meeting_rig(people_rig)
    before = rig.stored("meetings", "mt_q4_plan")
    ended = {**before, "status": "ended", "minutes": None, "minutes_confirmed_by": None, "delete_minutes_after": None}
    rig.real.meetings.replace(ended, expected_version=1)
    scope = Scope(rig.org, ended["world_id"], OWNER)
    rig.event_store.worlds[scope.world_id] = WorldRecord(OWNER, {}, run_id="r_meeting_q4_plan_1")
    rig._ids = ["art_publication_minutes"]
    doc = copy.deepcopy(transcript_case("owner_reads_quotes")["minutes"])
    for row in doc["action_items"]:
        row["work_item_id"] = None
    return rig, Writer(rig.stores, rig.org, OWNER, rig.clock, rig.redactor), scope, doc


def publish(case):
    rig, writer, _, doc = case
    return publish_minutes(writer, rig.event_store, rig.artifacts, "mt_q4_plan", doc, events=rig.events)


def test_FR_MTG_03_publication_pins_minutes_for_owner_review_without_releasing_items(publication):
    rig, _, scope, doc = publication
    before = rig.snapshot()
    result = publish(publication)
    stored = rig.stored("meetings", "mt_q4_plan")
    assert result == stored and conforms("meeting.schema.json", stored)
    assert stored["status"] == "minuted" and stored["minutes_confirmed_by"] is None
    assert stored["transcript"] == doc["transcript"]
    assert json.loads(rig.artifacts.read(scope, stored["minutes"])) == doc
    until = datetime.fromisoformat(rig.clock.replace("Z", "+00:00")) + timedelta(days=90)
    assert stored["delete_minutes_after"] == until.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    original, after = json.loads(before), json.loads(rig.snapshot())
    for name in ("work_items", "pins", "calendar", "mentions"):
        assert original[name] == after[name]
    events = rig.event_store.events[scope.world_id]
    assert [event["type"] for event in events] == ["meeting.minuted"]
    event = events[0]
    assert event["vis"] == [] and conforms("event.schema.json", event)
    assert event["data"] == {
        "meeting_id": "mt_q4_plan",
        "minutes": stored["minutes"],
        "decisions": len(doc["decisions"]),
        "action_items": len(doc["action_items"]),
        "flagged": doc["flagged"],
        "unverified": sum(row["state"] == "unverified" for row in doc["decisions"] + doc["action_items"]),
    }
    assert all(row["text"] not in json.dumps(event) for row in doc["summary"] + doc["decisions"])


@pytest.mark.parametrize("change", ["actor", "scheduled", "joining", "discarded", "deleted", "minuted"])
def test_FR_MTG_03_publication_requires_owner_and_ended_meeting(publication, change):
    rig, writer, _, _ = publication
    if change == "actor":
        writer.actor = SAM
    else:
        stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
        after = {**stored.record, "status": change}
        if change in ("discarded", "deleted"):
            after = gone_meeting(dict(stored.record), change)
        elif change == "minuted":
            original = transcript_case("owner_reads_quotes")["meeting"]
            after.update(minutes=original["minutes"], delete_minutes_after=original["delete_minutes_after"])
        assert conforms("meeting.schema.json", after)
        rig.real.meetings.replace(after, expected_version=stored.version)
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal) as raised:
        publish(publication)
    assert raised.value.status_code in (404, 409)
    assert rig.snapshot() == before and artifact_paths(rig) == paths and not rig.events.calls


@pytest.mark.parametrize("change", ["meeting", "pin", "expired", "missing", "transcript_meeting"])
def test_FR_MTG_03_publication_refuses_wrong_or_unavailable_pinned_transcript(publication, change):
    rig, writer, scope, doc = publication
    if change == "meeting":
        doc["meeting_id"] = "mt_other"
    elif change == "pin":
        doc["transcript"]["version"] += 1
    elif change == "expired":
        writer.now = rig.stored("meetings", "mt_q4_plan")["delete_transcript_after"]
    elif change == "missing":
        rig.artifacts._purge(
            next(
                r.record_id
                for r in rig.artifacts.retention().records()
                if doc["transcript"]["artifact_id"] in r.record_id
            )
        )
    else:
        transcript = json.loads(rig.artifacts.read(scope, doc["transcript"]))
        transcript["meeting_id"] = "mt_other"
        made = rig.put_doc(scope, "art_wrong_transcript", transcript)
        doc["transcript"] = made.ref
        stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
        rig.real.meetings.replace({**stored.record, "transcript": made.ref}, expected_version=stored.version)
    before = rig.snapshot()
    with pytest.raises(Refusal):
        publish(publication)
    assert rig.snapshot() == before and not rig.events.calls


@pytest.mark.parametrize("group", ["summary", "decisions", "action_items"])
def test_FR_MTG_04_publication_checks_evidence_ids_against_stored_transcript(publication, group):
    rig, _, _, doc = publication
    doc[group][0]["evidence"] = ["u9999"]
    if group != "summary":
        doc[group][0]["state"] = "verified"
    before = rig.snapshot()
    with pytest.raises(Refusal) as raised:
        publish(publication)
    assert raised.value.status_code == 422
    assert rig.snapshot() == before and not rig.events.calls


def test_FR_MTG_03_publication_cas_conflict_purges_only_new_artifact_and_emits_nothing(publication):
    rig, _, _, _ = publication
    rig.conflicting_stores("meetings")
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal) as raised:
        publish(publication)
    assert raised.value.status_code == 409
    assert rig.snapshot() == before and artifact_paths(rig) == paths and not rig.events.calls


def test_FR_MTG_03_publication_preserves_flagged_transcript_verdict(publication):
    rig, _, scope, doc = publication
    transcript = json.loads(rig.artifacts.read(scope, doc["transcript"]))
    made = rig.put_doc(scope, "art_flagged_transcript", transcript, screening="flagged")
    doc["transcript"], doc["flagged"] = made.ref, False
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    rig.real.meetings.replace({**stored.record, "transcript": made.ref}, expected_version=stored.version)
    rig._ids = ["art_publication_minutes"]
    result = publish(publication)
    published = json.loads(rig.artifacts.read(scope, result["minutes"]))
    assert published["flagged"] is True
    assert rig.event_store.events[scope.world_id][0]["data"]["flagged"] is True


def test_FR_MTG_03_second_publication_cannot_duplicate_artifact_or_event(publication):
    rig, _, scope, _ = publication
    publish(publication)
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal) as raised:
        publish(publication)
    assert raised.value.status_code == 409
    assert rig.snapshot() == before and artifact_paths(rig) == paths
    assert len(rig.event_store.events[scope.world_id]) == 1


def test_FR_MTG_03_failed_event_recording_rolls_back_publication(publication, monkeypatch):
    rig, _, scope, _ = publication
    before, paths = rig.stored("meetings", "mt_q4_plan"), artifact_paths(rig)

    def failed(*args, **kwargs):
        raise RuntimeError("offline event writer unavailable")

    monkeypatch.setattr(rig.events, "append", failed)
    with pytest.raises((Refusal, RuntimeError)):
        publish(publication)
    assert rig.stored("meetings", "mt_q4_plan") == before
    assert artifact_paths(rig) == paths and not rig.event_store.events.get(scope.world_id)
