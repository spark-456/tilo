"""Offline owner-scoped analyst/publication integration, including a changed record during generation."""

import copy
import json
from types import SimpleNamespace

import pytest
from _mtg09b_lib import block_network
from _ppl11a_lib import OWNER, SAM
from _ppl11c_lib import artifact_paths, meeting_rig
from test_FR_MTG_03_minutes_analysis import Script as AnalysisScript
from tilo_api.deps import WorldRecord
from tilo_api.meeting_minutes import analyze_and_publish_minutes
from tilo_api.people_writes import Refusal, Writer
from tilo_memory.artifacts import Scope
from tilo_providers.safety import FakeSafetyProvider


class Script:
    def __init__(self, doc, during=None):
        self.doc, self.during, self.calls = doc, during, []

    def generate(self, role, request, *, budget):
        self.calls.append((role, request, budget))
        if self.during:
            self.during()
        return SimpleNamespace(response=SimpleNamespace(text=json.dumps(self.doc)), outcome="ok", budget=0)


@pytest.fixture
def integration(people_rig, monkeypatch):
    block_network(monkeypatch)
    rig = meeting_rig(people_rig)
    before = rig.real.meetings.get(rig.org, "mt_q4_plan")
    ended = {
        **before.record,
        "status": "ended",
        "minutes": None,
        "minutes_confirmed_by": None,
        "delete_minutes_after": None,
        "agenda": [],
    }
    rig.real.meetings.replace(ended, expected_version=before.version)
    scope = Scope(rig.org, ended["world_id"], OWNER)
    rig.event_store.worlds[scope.world_id] = WorldRecord(OWNER, {}, run_id="r_meeting_q4_plan_1")
    transcript = json.loads(rig.artifacts.read(scope, ended["transcript"]))
    quote = transcript["utterances"][0]
    doc = dict(
        meeting_id="mt_spoofed",
        transcript=ended["transcript"],
        generated_at=rig.clock,
        flagged=False,
        summary=[],
        agenda=[],
        action_items=[],
        decisions=[dict(text=quote["text"], evidence=[quote["id"]], state="verified")],
    )
    rig._ids = ["art_integrated_minutes"]
    return rig, Writer(rig.stores, rig.org, OWNER, rig.clock, rig.redactor), scope, Script(doc)


def run(case, *, budget=2):
    rig, writer, _, router = case
    return analyze_and_publish_minutes(
        writer,
        rig.event_store,
        rig.artifacts,
        "mt_q4_plan",
        router=router,
        meeting_at="2026-10-05T23:30:00.000Z",
        budget=budget,
        safety=FakeSafetyProvider(),
        events=rig.events,
    )


def test_FR_MTG_03_integration_reads_exact_pin_and_publishes_unconfirmed(integration):
    rig, _, scope, router = integration
    before = json.loads(rig.snapshot())
    result = run(integration)
    doc = json.loads(rig.artifacts.read(scope, result["minutes"]))
    assert doc["meeting_id"] == "mt_q4_plan" and doc["transcript"] == result["transcript"]
    assert result["status"] == "minuted" and result["minutes_confirmed_by"] is None
    assert doc["decisions"][0]["state"] == "verified"
    sent = json.loads(router.calls[0][1].prompt.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert sent["transcript"] == json.loads(rig.artifacts.read(scope, result["transcript"]))
    assert router.calls[0][2] == 2
    after = json.loads(rig.snapshot())
    for name in ("work_items", "pins", "calendar", "mentions"):
        assert before[name] == after[name]
    assert [p["type"] for p in rig.event_store.events[scope.world_id]] == ["meeting.minuted"]


@pytest.mark.parametrize("change", ["actor", "world_owner", "expired", "joining", "missing", "flagged"])
def test_FR_MTG_03_integration_refuses_before_provider_or_write(integration, change):
    rig, writer, scope, router = integration
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    if change == "actor":
        writer.actor = SAM
    elif change == "world_owner":
        rig.event_store.worlds[scope.world_id].owner = SAM
    elif change == "expired":
        writer.now = stored.record["delete_transcript_after"]
    elif change == "joining":
        rig.real.meetings.replace({**stored.record, "status": "joining"}, expected_version=stored.version)
    elif change == "missing":
        rig.artifacts._purge(
            next(
                r.record_id
                for r in rig.artifacts.retention().records()
                if stored.record["transcript"]["artifact_id"] in r.record_id
            )
        )
    else:
        transcript = json.loads(rig.artifacts.read(scope, stored.record["transcript"]))
        made = rig.put_doc(scope, "art_flagged_source", transcript, screening="flagged")
        rig.real.meetings.replace({**stored.record, "transcript": made.ref}, expected_version=stored.version)
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal):
        run(integration)
    assert router.calls == [] and rig.snapshot() == before and artifact_paths(rig) == paths
    assert not rig.events.calls


@pytest.mark.parametrize("change", ["title", "pin", "joining", "agenda"])
def test_FR_MTG_03_integration_rejects_generation_race_without_new_artifact(integration, change):
    rig, _, _, router = integration

    def mutate():
        stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
        after = copy.deepcopy(stored.record)
        if change == "title":
            after["title"] = "Changed during analysis"
        elif change == "pin":
            after["transcript"]["version"] += 1
        elif change == "agenda":
            after["agenda"] = [{"title": "Changed agenda", "minutes": None}]
        else:
            after["status"] = "joining"
        rig.real.meetings.replace(after, expected_version=stored.version)

    router.during = mutate
    paths = artifact_paths(rig)
    with pytest.raises(Refusal) as raised:
        run(integration)
    assert raised.value.status_code == 409 and artifact_paths(rig) == paths and not rig.events.calls
    assert rig.stored("meetings", "mt_q4_plan")["minutes"] is None


@pytest.mark.parametrize("budget", [0, -1, float("nan")])
def test_FR_MTG_03_integration_bad_budget_has_no_call_or_write(integration, budget):
    rig, _, _, router = integration
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal):
        run(integration, budget=budget)
    assert not router.calls and rig.snapshot() == before and artifact_paths(rig) == paths


def test_FR_MTG_03_integration_second_attempt_never_calls_provider(integration):
    rig, _, _, router = integration
    run(integration)
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal):
        run(integration)
    assert len(router.calls) == 1 and rig.snapshot() == before and artifact_paths(rig) == paths


@pytest.mark.parametrize("change", ["wrong_meeting", "bad_order", "invalid_schema"])
def test_FR_MTG_03_integration_bad_source_is_never_sent_to_provider(integration, change):
    rig, _, scope, router = integration
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    transcript = json.loads(rig.artifacts.read(scope, stored.record["transcript"]))
    if change == "wrong_meeting":
        transcript["meeting_id"] = "mt_other"
    elif change == "bad_order":
        transcript["utterances"] = [transcript["utterances"][0]] * 2
    else:
        transcript["utterances"][0]["text"] = ""
    made = rig.put_doc(scope, "art_invalid_source", transcript)
    rig.real.meetings.replace({**stored.record, "transcript": made.ref}, expected_version=stored.version)
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal):
        run(integration)
    assert not router.calls and rig.snapshot() == before and artifact_paths(rig) == paths and not rig.events.calls


def test_FR_MTG_03_integration_provider_failure_is_fixed_and_has_no_write(integration):
    rig, _, _, router = integration

    def fail():
        raise RuntimeError("untrusted provider failure content")

    router.during = fail
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal) as raised:
        run(integration)
    assert raised.value.detail == "analysis_failed" and raised.value.status_code == 502
    assert rig.snapshot() == before and artifact_paths(rig) == paths and not rig.events.calls


def test_FR_MTG_03_integration_stored_agenda_is_required_before_publication(integration):
    rig, _, _, router = integration
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    agenda = [{"title": "Stored topic", "minutes": None}]
    rig.real.meetings.replace({**stored.record, "agenda": agenda}, expected_version=stored.version)
    before, paths = rig.snapshot(), artifact_paths(rig)
    with pytest.raises(Refusal) as raised:
        run(integration)
    assert raised.value.detail == "analysis_failed"
    data = json.loads(router.calls[0][1].prompt.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert data["agenda"] == agenda
    assert rig.snapshot() == before and artifact_paths(rig) == paths and not rig.events.calls


def test_FR_MTG_03_integration_verified_stored_agenda_publishes_unconfirmed(integration):
    rig, writer, scope, original = integration
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    agenda = [{"title": "Rate sheet", "minutes": 5}]
    rig.real.meetings.replace({**stored.record, "agenda": agenda}, expected_version=stored.version)
    evidence = original.doc["decisions"][0]["evidence"]
    original.doc["agenda"] = [{"title": "Rate sheet", "coverage": "partial", "evidence": evidence}]
    router = AnalysisScript(original.doc, {"supported": [True]})
    before = rig.snapshot()
    result = run((rig, writer, scope, router))
    minutes = json.loads(rig.artifacts.read(scope, result["minutes"]))
    assert minutes["agenda"] == original.doc["agenda"] and result["minutes_confirmed_by"] is None
    assert json.loads(before)["work_items"] == json.loads(rig.snapshot())["work_items"]
