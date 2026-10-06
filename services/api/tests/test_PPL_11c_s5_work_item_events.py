"""PPL-11c slice 5: the PE-12 events of the work-item writes (PE-12, PE-30, ADR-0021 "no new event", HR-1; the registry
already holds `work_item.created` and `work_item.changed`; API_PPL_11c.md section 5).

Needs slices 1, 1b and 3 first (it drives their routes) and the ADR-0009 contract change for `vis: []` (accepted by the
user 2026-10-05; `event.schema.json` `district_list` still has `minItems: 1`; needs contract change, architect PR).
Until that lands the tests widen `vis` to `"all"` for the schema check only and assert `vis == []` themselves.

Every event goes through the single writer (`deps.get_event_writer`) as an unstamped part with its own id, to the Desk
world of the person who may read the record in full (`deps.get_desk_worlds().desk_world(org_id, user_id)`, created
lazily), with `vis: []`, `district` null, `authz` null and a summary that names no title, quote, address or link. It is
written only after the record committed; a refused or lost write writes nothing; a failed append undoes the write (503).
"""

from __future__ import annotations

import pathlib

import pytest
from _api_lib import FlakyEventWriter
from _ppl11a_lib import MEERA, OWNER, PRIYA, SAM
from _ppl11c_lib import (
    ALL_WI_ACTIONS,
    R_TEAM_ADD,
    WORK_ITEM_BODY,
    act,
    emitted,
    item_for,
    meeting_rig,
    path_of,
    stamped,
    validate_event,
    work_rig,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
PART_KEYS = {
    "id",
    "type",
    "actor",
    "target",
    "summary",
    "vis",
    "authz",
    "data",
    "severity",
    "district",
    "level",
    "item",
    "credits",
    "cause",
    "trace",
}
CHANGE_OF = {
    "edit": "edited",
    "snooze": "snoozed",
    "done": "done",
    "reopen": "reopened",
    "not-mine": "reassign_requested",
    "put-back": "edited",
}


def _assert_part(part: dict, *, type_: str, actor: str, target: str) -> None:
    assert set(part) <= PART_KEYS and {"id", "type", "actor", "target", "summary", "vis", "authz", "data"} <= set(part)
    assert part["type"] == type_ and part["actor"] == actor and part["target"] == target
    assert part["vis"] == [] and part.get("district") is None, "PE-12: owner-only, no district"
    assert part["authz"] is None, "a work item event is no side effect"
    assert part.get("severity", "info") == "info" and part.get("item") is None
    summary = part["summary"]
    assert 1 <= len(summary) <= 140 and "http" not in summary and "@" not in summary


def test_PPL_11c_s5_PE_12_creating_an_item_writes_work_item_created_in_the_owners_desk_world(people_rig):
    """Given u_priya, when she adds an item, then exactly one event, `work_item.created`, in her Desk world (made
    lazily for her): actor and target her, `vis` empty, data ids and enums only, a summary with none of her words."""
    rig = work_rig(people_rig)
    body = {"title": "Quarterly vendor audit", "due_text": "tomorrow", "source": {"kind": "manual", "ref": None}}
    response = rig.post("/v1/work-items", body)
    assert response.status_code == 201
    item = response.json()
    [(world, part)] = emitted(rig)
    assert world == "w_desk_priya" and rig.desks.calls == [(rig.org, PRIYA)]
    _assert_part(part, type_="work_item.created", actor=PRIYA, target=PRIYA)
    assert part["data"] == {"work_item_id": item["id"], "owner": PRIYA, "status": "open", "source_kind": "manual"}
    assert not any(word.lower() in part["summary"].lower() for word in ("quarterly", "vendor", "audit", "tomorrow"))
    [event] = stamped(rig, world)
    validate_event(event)
    assert event["vis"] == [] and event["id"] == part["id"]


@pytest.mark.parametrize("action", list(ALL_WI_ACTIONS))
def test_PPL_11c_s5_PE_30_each_action_writes_work_item_changed_naming_what_the_history_recorded(people_rig, action):
    """The event's `change` is the history entry the write itself added and its `status` the record's new one
    (BQ-PPL10-14:
    an event is never built from what the request asked for)."""
    rig = work_rig(people_rig)
    item_id = item_for(rig, action)
    response = act(rig, action, item_id)
    assert response.status_code == 200, response.text[:200]
    stored = rig.stored("work_items", item_id)
    [(world, part)] = emitted(rig)
    assert world == "w_desk_priya"
    _assert_part(part, type_="work_item.changed", actor=PRIYA, target=PRIYA)
    assert part["data"] == {"work_item_id": item_id, "change": CHANGE_OF[action], "status": stored["status"]}
    assert stored["history"][-1]["change"] == part["data"]["change"]
    [event] = stamped(rig, world)
    validate_event(event)
    assert event["vis"] == []


def test_PPL_11c_s5_PE_12_a_confirm_is_written_in_the_assignees_desk_world_not_the_assigners(people_rig):
    """Confirming releases an item for u_sam: PE-12 puts "a record P may read in full (confirmed for P)" in P's Desk
    world,
    so the event lands there, with the confirmer (u_owner) as actor and u_sam as target."""
    rig = meeting_rig(people_rig)
    assert rig.post("/v1/work-items/wi_launch_note/confirm").status_code == 200
    [(world, part)] = emitted(rig)
    assert world == "w_desk_sam" and rig.desks.calls == [(rig.org, SAM)]
    _assert_part(part, type_="work_item.changed", actor=OWNER, target=SAM)
    assert part["data"] == {"work_item_id": "wi_launch_note", "change": "confirmed", "status": "open"}
    validate_event(stamped(rig, "w_desk_sam")[0])


def test_PPL_11c_s5_HR_1_a_refused_a_lost_or_a_read_only_request_writes_no_event_and_makes_no_world(people_rig):
    rig = work_rig(people_rig)
    for actor in (SAM, MEERA, OWNER, "u_ghost"):
        rig.as_user(actor)
        assert act(rig, "done", "wi_own1").status_code == 404
    rig.as_user(PRIYA)
    assert act(rig, "snooze", "wi_own1", {"until": "2020-01-01T00:00:00.000Z"}).status_code == 409
    assert act(rig, "snooze", "wi_own1", {"until": "soon"}).status_code == 422
    assert act(rig, "reopen", "wi_own1").status_code == 409
    assert act(rig, "edit", "wi_own1", {"source": {"ref": "x"}}).status_code == 422
    rig.conflicting_stores("work_items")
    assert act(rig, "done", "wi_own1").status_code == 409
    rig.stores.work_items.fail_replace = False
    assert rig.get("/v1/plate").status_code == 200 and rig.get("/v1/work-items/wi_own1/quote").status_code == 404
    assert emitted(rig) == [] and rig.desks.calls == [], "nothing happened, so nothing is said"


def test_PPL_11c_s5_PE_12_writes_that_have_no_registry_event_write_none_and_need_no_writer(people_rig):
    """A meeting create, a person create and a membership change have no event type, so they emit nothing and still
    work with the writer and the Desk worlds unwired."""
    rig = work_rig(people_rig)
    rig.unwire("event_writer", "desk_worlds")
    rig.as_user(PRIYA)
    assert rig.post("/v1/meetings", {"title": "Weekly sync", "source": "upload"}).status_code == 201
    rig.as_user(OWNER)
    person = rig.post(
        "/v1/people",
        {
            "display_name": "Nina",
            "aliases": [],
            "email": "nina@example.com",
            "time_zone": "Asia/Kolkata",
            "preferred_channel": "web",
        },
    )
    assert person.status_code == 201
    rig.require_route(R_TEAM_ADD)
    assert rig.client.post(path_of(R_TEAM_ADD, person_id=PRIYA), json={"team": "tm_ops"}).status_code == 200
    assert emitted(rig) == []


@pytest.mark.parametrize("action", ["done", "edit", "snooze", "not-mine"])
def test_PPL_11c_s5_HR_1_when_the_event_cannot_be_written_the_write_is_undone_and_the_answer_is_503(people_rig, action):
    """The record committed, the append failed: nothing may look changed. 503 (no record text) and the stored item is
    what it was (content; the version may have moved twice); with the writer back, the same call works."""
    rig = work_rig(people_rig)
    item_id = item_for(rig, action)
    before = rig.stored("work_items", item_id)
    rig.events = FlakyEventWriter(rig.event_store, failing=True)
    failed = act(rig, action, item_id)
    assert failed.status_code == 503 and "Water the plants" not in failed.text, failed.text[:200]
    assert rig.stored("work_items", item_id) == before
    assert rig.get("/v1/plate").status_code == 200
    rig.events.failing = False
    assert act(rig, action, item_id).status_code == 200


def test_PPL_11c_s5_HR_1_a_create_whose_event_fails_leaves_no_item_behind(people_rig):
    rig = work_rig(people_rig)
    before = [s.record for s in rig.real.work_items.list(rig.org)]
    rig.events = FlakyEventWriter(rig.event_store, failing=True)
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 503
    assert [s.record for s in rig.real.work_items.list(rig.org)] == before
    rig.events.failing = False
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201


def test_PPL_11c_s5_HR_1_a_confirm_whose_event_fails_leaves_the_item_proposed(people_rig):
    rig = meeting_rig(people_rig)
    before = rig.stored("work_items", "wi_launch_note")
    rig.events = FlakyEventWriter(rig.event_store, failing=True)
    assert rig.post("/v1/work-items/wi_launch_note/confirm").status_code == 503
    assert rig.stored("work_items", "wi_launch_note") == before and before["status"] == "proposed"


@pytest.mark.parametrize("seam", ["event_writer", "desk_worlds"])
def test_PPL_11c_s5_PE_19_without_the_writer_or_the_desk_worlds_every_work_item_write_is_503_and_changes_nothing(
    people_rig, seam
):
    """Fail closed: production has neither seam wired yet, so a work-item write answers 503 `not_configured` before it
    commits anything (a write whose event could never be recorded does not happen)."""
    rig = meeting_rig(people_rig)
    rig.unwire(seam)
    before = rig.snapshot()
    rig.as_user(PRIYA)
    for action in ("edit", "done", "snooze", "not-mine"):
        response = act(rig, action, "wi_rate_sheet")
        assert response.status_code == 503 and response.json() == {"detail": "not_configured"}, (action, response.text)
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).json() == {"detail": "not_configured"}
    rig.as_user(OWNER)
    assert rig.post("/v1/work-items/wi_launch_note/confirm").status_code == 503
    assert rig.snapshot() == before


def test_PPL_11c_s5_PE_19_a_desk_world_that_cannot_be_made_is_a_503_and_the_write_is_undone(people_rig):
    rig = work_rig(people_rig)
    before = [s.record for s in rig.real.work_items.list(rig.org)]
    rig.desks.fail = True
    assert act(rig, "done", "wi_own1").status_code == 503
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 503
    assert [s.record for s in rig.real.work_items.list(rig.org)] == before and emitted(rig) == []


def test_PPL_11c_s5_PE_19_a_retried_create_with_its_key_writes_one_event(people_rig):
    """Needs slice 4 (the key): the replay is the first answer and says nothing new (retries never duplicate)."""
    rig = work_rig(people_rig)
    key = {"Idempotency-Key": "event-once-0001"}
    assert rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=key).status_code == 201
    assert rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=key).status_code == 201
    assert len(emitted(rig)) == 1


STEPS = st.lists(st.sampled_from(["edit", "snooze", "done", "reopen", "not-mine", "put-back"]), max_size=10)


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(steps=STEPS)
def test_PPL_11c_s5_HR_1_events_equal_successful_writes_and_name_each_history_change_in_order(people_rig, steps):
    """Whatever sequence of actions: one event per success and none per refusal, each in the owner's Desk world with
    the change the history gained, `seq` strictly increasing in that world."""
    rig = work_rig(people_rig)
    seen_history = len(rig.stored("work_items", "wi_rate_sheet")["history"])
    successes: list[str] = []
    for n, action in enumerate(steps):
        body = {"title": f"Rate sheet {n}"} if action == "edit" else None
        response = act(rig, action, "wi_rate_sheet", body)
        stored = rig.stored("work_items", "wi_rate_sheet")
        if response.status_code == 200:
            assert len(stored["history"]) == seen_history + 1
            seen_history += 1
            successes.append(stored["history"][-1]["change"])
        else:
            assert len(stored["history"]) == seen_history
    events = stamped(rig, "w_desk_priya")
    assert [e["data"]["change"] for e in events] == successes
    assert [e["seq"] for e in events] == sorted({e["seq"] for e in events}), "seq strictly increasing"
    assert len(emitted(rig)) == len(successes)


def test_PPL_11c_s5_PE_12_dev_mode_records_the_work_item_event_in_the_dev_owners_desk_world(monkeypatch):
    """Dev mode wires a Desk world per person over its in-memory `Store`, and its writer (which refuses an event with
    no `vis` and validates every event against the contract) accepts `vis: []` once ADR-0009's contract change lands."""
    import json  # noqa: PLC0415

    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from tilo_api import deps, dev  # noqa: PLC0415
    from tilo_api.people import router  # noqa: PLC0415

    contract = json.loads((CONTRACTS / "event.schema.json").read_text(encoding="utf-8"))
    if contract["$defs"]["district_list"].get("minItems") == 1:
        pytest.skip("needs contract change: ADR-0009 (district_list minItems 1 -> 0) is not in contracts/ yet")

    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    app = FastAPI()
    app.include_router(router)
    dev.install(app, {})
    client = TestClient(app, base_url=f"http://localhost:{dev.PORT}", raise_server_exceptions=False)
    assert client.post("/v1/work-items", json=WORK_ITEM_BODY).status_code == 201
    store = app.dependency_overrides[deps.get_store]()
    [(world_id, committed)] = [(w, e) for w, e in store.events.items() if w.startswith("w_desk_")]
    assert world_id == "w_desk_" + dev.DEV_OWNER[2:] and store.worlds[world_id].owner == dev.DEV_OWNER
    assert [e["type"] for e in committed] == ["work_item.created"] and committed[0]["vis"] == []
