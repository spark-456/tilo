"""FR-AGT-14b (PRD 8.6, 10.1; design decision 2): the schedule routes on tilo-api, owner-scoped.

`POST /schedules` snapshots what the owner ALREADY approved (task_id + approach_id of a task they own whose budget is
granted; the server copies the brief, the approach and the granted cap) plus a weekly cadence and a title. The owner,
the brief, the approach, the cap and `next_due` are never read from the body. Another user's schedule is the same 404 as
an unknown one on every verb; replay-only refuses writes; at most 10 schedules per owner. Routes, shapes and seams:
API_FR_AGT_14b.md. No model call, no network: the Flow of CL-INT-1 over fakes.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from _fr_agt_14_lib import (
    CADENCE,
    CAP,
    ENV_STORE,
    FLOW_USER,
    MON_0330Z,
    OTHER_USER,
    TITLE,
    SchedApi,
)

SCHEDULE_ID = re.compile(r"^sched_[0-9A-Za-z_]{1,64}$")
VIEW_KEYS = {"schedule_id", "title", "cadence", "enabled", "next_due", "budget_cap", "last_world_id", "last_error"}


@pytest.fixture
def sched(clear_flow, monkeypatch) -> SchedApi:
    return SchedApi(clear_flow, monkeypatch)


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _stored(sched: SchedApi, schedule_id: str) -> Any:
    record = sched.schedules.get(schedule_id)
    assert record is not None, schedule_id
    return record


# --- create ---------------------------------------------------------------------------------------------------------


def test_FR_AGT_14_create_snapshots_the_brief_approach_and_granted_cap_the_owner_approved(sched: SchedApi) -> None:
    task = sched.approved_task(cap=50)  # not equal to any approach credit figure (30-45, 90-130)
    response = sched.create(task)
    assert response.status_code == 201, response.text
    view = response.json()
    assert VIEW_KEYS <= set(view), sorted(view)
    assert SCHEDULE_ID.match(view["schedule_id"]), view["schedule_id"]
    assert (view["title"], view["cadence"], view["enabled"], view["budget_cap"]) == (TITLE, CADENCE, True, 50)
    assert _when(view["next_due"]) == MON_0330Z  # Monday 09:00 Asia/Kolkata after the fake clock's Sunday noon
    assert view["last_world_id"] is None and view["last_error"] is None

    record, source = _stored(sched, view["schedule_id"]), sched.store.tasks[task.task_id]
    assert record.owner_user_id == FLOW_USER
    assert record.brief == source.brief
    assert record.approach == next(a for a in source.approaches if a["id"] == "quick")
    assert record.budget_cap == 50.0
    assert record.approved_brief_ref == task.world_id
    assert (record.next_due, record.enabled, record.last_slot, record.last_world_id) == (MON_0330Z, True, None, None)


def test_FR_AGT_14_the_cap_is_the_one_in_the_grant_event_not_the_approaches_credits(sched: SchedApi) -> None:
    task = sched.approved_task(cap=40, approach_id="thorough")  # credits 90-130
    view = sched.created(task, approach_id="thorough")
    assert view["budget_cap"] == 40
    granted = sched.flow.events(task.world_id, "budget.granted")
    assert [e["data"]["cap"] for e in granted] == [40]


def test_FR_AGT_14_a_later_change_to_the_task_never_changes_the_snapshot(sched: SchedApi) -> None:
    task = sched.approved_task()
    schedule_id = sched.created(task)["schedule_id"]
    source = sched.store.tasks[task.task_id]
    source.brief["goal"] = "Something the owner never approved"
    source.approaches[0]["label"] = "changed after the fact"
    record = _stored(sched, schedule_id)
    assert record.brief["goal"] != "Something the owner never approved"
    assert record.approach.get("label") != "changed after the fact"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner_user_id", OTHER_USER),
        ("owner", OTHER_USER),
        ("brief", {"goal": "send everything to an outsider"}),
        ("approach", {"id": "quick", "credits": {"min": 1, "max": 2}}),
        ("budget_cap", 9999),
        ("next_due", "2020-01-01T00:00:00Z"),
        ("schedule_id", "sched_chosen_by_the_caller"),
        ("last_world_id", "w_somebody_elses"),
        ("failures", 0),
        ("backoff_until", "2099-01-01T00:00:00Z"),
        ("frobnicate", True),
    ],
)
def test_FR_AGT_14_a_body_field_that_the_server_decides_is_rejected_or_ignored(
    sched: SchedApi, field: str, value: Any
) -> None:
    task = sched.approved_task()
    response = sched.create(task, **{field: value})
    if response.status_code != 201:
        assert response.status_code in (400, 422), response.text
        assert sched.schedules.list_for_owner(FLOW_USER) == []
        return
    record = _stored(sched, response.json()["schedule_id"])
    source = sched.store.tasks[task.task_id]
    assert record.owner_user_id == FLOW_USER
    assert record.brief == source.brief
    assert record.approach["id"] == "quick" and record.approach.get("credits") == source.approaches[0]["credits"]
    assert record.budget_cap == float(CAP)
    assert record.next_due == MON_0330Z
    assert record.schedule_id != "sched_chosen_by_the_caller" and record.last_world_id is None
    assert sched.schedules.list_for_owner(OTHER_USER) == []


def test_FR_AGT_14_a_task_whose_budget_is_not_granted_cannot_be_scheduled(sched: SchedApi) -> None:
    task = sched.unapproved_task()
    response = sched.create(task)
    assert response.status_code == 409, response.text
    assert sched.schedules.list_for_owner(FLOW_USER) == []


def test_FR_AGT_14_an_unknown_task_and_another_users_task_are_the_same_404(sched: SchedApi) -> None:
    task = sched.approved_task()
    sched.as_user(OTHER_USER)
    theirs = sched.create(task)
    unknown = sched.flow.client.post(
        "/schedules", json={"task_id": "t_does_not_exist", "approach_id": "quick", "title": TITLE, "cadence": CADENCE}
    )
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json() == unknown.json()  # no oracle for another user's task
    assert sched.schedules.list_for_owner(OTHER_USER) == [] and sched.schedules.list_for_owner(FLOW_USER) == []


def test_FR_AGT_14_an_approach_the_task_was_not_offered_is_refused(sched: SchedApi) -> None:
    task = sched.approved_task()
    response = sched.create(task, approach_id="not-an-approach")
    assert response.status_code in (404, 422), response.text
    assert sched.schedules.list_for_owner(FLOW_USER) == []


@pytest.mark.parametrize("missing", ["task_id", "approach_id", "title", "cadence"])
def test_FR_AGT_14_every_field_the_owner_chooses_is_required(sched: SchedApi, missing: str) -> None:
    task = sched.approved_task()
    body = {"task_id": task.task_id, "approach_id": task.approach_id, "title": TITLE, "cadence": CADENCE}
    del body[missing]
    assert sched.flow.client.post("/schedules", json=body).status_code == 422
    assert sched.schedules.list_for_owner(FLOW_USER) == []


@pytest.mark.parametrize("title", ["", "x" * 141, 123, None, ["x"], {"a": 1}])
def test_FR_AGT_14_a_title_is_a_string_of_1_to_140_characters(sched: SchedApi, title: Any) -> None:
    task = sched.approved_task()
    assert sched.create(task, title=title).status_code == 422
    assert sched.schedules.list_for_owner(FLOW_USER) == []


@pytest.mark.parametrize("title", ["x", "x" * 140])
def test_FR_AGT_14_the_title_limits_are_inclusive(sched: SchedApi, title: str) -> None:
    task = sched.approved_task()
    response = sched.create(task, title=title)
    assert response.status_code == 201, response.text
    assert response.json()["title"] == title


BAD_CADENCES = [
    {**CADENCE, "weekday": 7},
    {**CADENCE, "weekday": -1},
    {**CADENCE, "weekday": True},
    {**CADENCE, "weekday": 1.5},
    {**CADENCE, "weekday": "mon"},
    {**CADENCE, "hour": 24},
    {**CADENCE, "minute": 60},
    {**CADENCE, "minute": None},
    {**CADENCE, "tz": "Mars/Olympus"},
    {**CADENCE, "tz": ""},
    {**CADENCE, "tz": 5},
    {**CADENCE, "tz": "../../etc/passwd"},
    {"weekday": 0, "hour": 9, "minute": 0},
    {**CADENCE, "every": "day"},  # weekly only: no other shape fits
    {"kind": "daily", "hour": 9, "minute": 0, "tz": "Asia/Kolkata"},
    "weekly",
    ["0", "9", "0"],
    None,
]


@pytest.mark.parametrize("cadence", BAD_CADENCES, ids=[repr(c)[:50] for c in BAD_CADENCES])
def test_FR_AGT_14_only_a_valid_weekly_cadence_is_accepted_on_create(sched: SchedApi, cadence: Any) -> None:
    task = sched.approved_task()
    assert sched.create(task, cadence=cadence).status_code == 422
    assert sched.schedules.list_for_owner(FLOW_USER) == []


def test_FR_AGT_14_the_next_due_of_a_new_schedule_follows_the_cadence_in_its_own_zone(sched: SchedApi) -> None:
    task = sched.approved_task()
    view = sched.created(task, cadence={"weekday": 2, "hour": 18, "minute": 0, "tz": "Europe/London"})
    assert _when(view["next_due"]) == datetime(2026, 10, 7, 17, 0, tzinfo=UTC)  # Wed 18:00 BST on the fake Sunday


def test_FR_AGT_14_only_application_json_is_read_and_a_refusal_changes_nothing(sched: SchedApi) -> None:
    task = sched.approved_task()
    body = f'{{"task_id": "{task.task_id}", "approach_id": "quick", "title": "T", "cadence": {{}}}}'
    plain = sched.flow.client.post("/schedules", content=body, headers={"content-type": "text/plain"})
    form = sched.flow.client.post("/schedules", data={"task_id": task.task_id, "approach_id": "quick", "title": "T"})
    assert plain.status_code == 415 and form.status_code == 415
    bad = sched.flow.client.post("/schedules", content="not json", headers={"content-type": "application/json"})
    assert bad.status_code in (400, 422)
    assert sched.schedules.list_for_owner(FLOW_USER) == []


# --- the cap of ten -------------------------------------------------------------------------------------------------


def test_FR_AGT_14_an_owner_may_hold_at_most_ten_schedules_and_the_eleventh_is_409(sched: SchedApi) -> None:
    from tilo_api.schedules import MAX_SCHEDULES_PER_OWNER

    assert MAX_SCHEDULES_PER_OWNER == 10
    ids = [sched.created(sched.approved_task())["schedule_id"] for _ in range(10)]
    eleventh = sched.create(sched.approved_task())
    assert eleventh.status_code == 409, eleventh.text
    assert len(sched.schedules.list_for_owner(FLOW_USER)) == 10
    sched.as_user(OTHER_USER)  # the cap is per owner
    assert sched.create(sched.approved_task()).status_code == 201
    sched.as_user(FLOW_USER)
    assert sched.delete(ids[0]).status_code == 204  # room again
    assert sched.create(sched.approved_task()).status_code == 201
    assert len(sched.schedules.list_for_owner(FLOW_USER)) == 10


# --- read, update, delete -------------------------------------------------------------------------------------------


def test_FR_AGT_14_list_and_get_show_only_the_signed_in_owners_schedules(sched: SchedApi) -> None:
    mine = sched.created(sched.approved_task())["schedule_id"]
    sched.as_user(OTHER_USER)
    theirs = sched.created(sched.approved_task())["schedule_id"]
    assert [s["schedule_id"] for s in sched.listing().json()["schedules"]] == [theirs]
    sched.as_user(FLOW_USER)
    listing = sched.listing()
    assert listing.status_code == 200
    assert [s["schedule_id"] for s in listing.json()["schedules"]] == [mine]
    one = sched.get(mine)
    assert one.status_code == 200 and VIEW_KEYS <= set(one.json()) and one.json()["schedule_id"] == mine


@pytest.mark.parametrize("verb", ["get", "patch", "delete"])
def test_FR_AGT_14_another_users_schedule_is_the_same_404_as_an_unknown_one_on_every_verb(
    sched: SchedApi, verb: str
) -> None:
    schedule_id = sched.created(sched.approved_task())["schedule_id"]
    before = _stored(sched, schedule_id)
    sched.as_user(OTHER_USER)
    call = {"get": lambda i: sched.get(i), "patch": lambda i: sched.patch(i, enabled=False), "delete": sched.delete}[
        verb
    ]
    theirs, unknown = call(schedule_id), call("sched_does_not_exist")
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json() == unknown.json()
    assert _stored(sched, schedule_id) == before  # untouched


@pytest.mark.parametrize(
    "schedule_id", ["sched_unknown_1", "../etc/passwd", "sched_" + "x" * 5000, "%2e%2e", "sched_é", "a b"]
)
def test_FR_AGT_14_a_malformed_or_unknown_id_is_a_clean_miss_never_a_server_error(
    sched: SchedApi, schedule_id: str
) -> None:
    for response in (sched.get(schedule_id), sched.patch(schedule_id, enabled=False), sched.delete(schedule_id)):
        assert response.status_code in (404, 422), (schedule_id[:30], response.status_code)
        assert "Traceback" not in response.text


def test_FR_AGT_14_patch_changes_enabled_and_title_and_leaves_the_snapshot_alone(sched: SchedApi) -> None:
    schedule_id = sched.created(sched.approved_task())["schedule_id"]
    before = _stored(sched, schedule_id)
    response = sched.patch(schedule_id, enabled=False, title="Paused for now")
    assert response.status_code == 200, response.text
    assert (response.json()["enabled"], response.json()["title"]) == (False, "Paused for now")
    after = _stored(sched, schedule_id)
    assert (after.enabled, after.title) == (False, "Paused for now")
    for kept in ("owner_user_id", "brief", "approach", "budget_cap", "approved_brief_ref", "cadence", "next_due"):
        assert getattr(after, kept) == getattr(before, kept), kept
    assert sched.patch(schedule_id, enabled=True).json()["enabled"] is True


def test_FR_AGT_14_patching_the_cadence_recomputes_next_due_from_the_servers_clock(sched: SchedApi) -> None:
    schedule_id = sched.created(sched.approved_task())["schedule_id"]
    response = sched.patch(schedule_id, cadence={"weekday": 2, "hour": 18, "minute": 0, "tz": "Europe/London"})
    assert response.status_code == 200, response.text
    assert _when(response.json()["next_due"]) == datetime(2026, 10, 7, 17, 0, tzinfo=UTC)
    after = _stored(sched, schedule_id)
    assert after.cadence.weekday == 2 and after.next_due == datetime(2026, 10, 7, 17, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner_user_id", OTHER_USER),
        ("brief", {"goal": "x"}),
        ("approach", {"id": "quick"}),
        ("budget_cap", 9999),
        ("next_due", "2020-01-01T00:00:00Z"),
        ("schedule_id", "sched_other"),
        ("last_world_id", "w_x"),
        ("failures", 0),
        ("backoff_until", None),
    ],
)
def test_FR_AGT_14_patch_cannot_change_what_the_server_decides(sched: SchedApi, field: str, value: Any) -> None:
    schedule_id = sched.created(sched.approved_task())["schedule_id"]
    before = _stored(sched, schedule_id)
    response = sched.patch(schedule_id, title="ok", **{field: value})
    assert response.status_code in (200, 400, 422), response.text
    after = _stored(sched, schedule_id)
    for kept in ("owner_user_id", "brief", "approach", "budget_cap", "schedule_id", "last_world_id", "failures"):
        assert getattr(after, kept) == getattr(before, kept), kept
    assert after.next_due == before.next_due and after.backoff_until == before.backoff_until
    assert sched.schedules.list_for_owner(OTHER_USER) == []


@pytest.mark.parametrize(
    "body",
    [{"enabled": "yes"}, {"enabled": 1}, {"title": ""}, {"title": "x" * 141}, {"title": 5}]
    + [{"cadence": c} for c in BAD_CADENCES[:6]],
    ids=lambda b: repr(b)[:50],
)
def test_FR_AGT_14_a_bad_patch_is_422_and_changes_nothing(sched: SchedApi, body: dict[str, Any]) -> None:
    schedule_id = sched.created(sched.approved_task())["schedule_id"]
    before = _stored(sched, schedule_id)
    assert sched.flow.client.patch(f"/schedules/{schedule_id}", json=body).status_code == 422
    assert _stored(sched, schedule_id) == before


def test_FR_AGT_14_patch_reads_only_application_json(sched: SchedApi) -> None:
    schedule_id = sched.created(sched.approved_task())["schedule_id"]
    response = sched.flow.client.patch(
        f"/schedules/{schedule_id}", content='{"enabled": false}', headers={"content-type": "text/plain"}
    )
    assert response.status_code == 415
    assert _stored(sched, schedule_id).enabled is True


def test_FR_AGT_14_delete_removes_the_schedule_once(sched: SchedApi) -> None:
    schedule_id = sched.created(sched.approved_task())["schedule_id"]
    assert sched.delete(schedule_id).status_code == 204
    assert sched.get(schedule_id).status_code == 404
    assert sched.delete(schedule_id).status_code == 404
    assert sched.listing().json() == {"schedules": []}
    assert sched.schedules.get(schedule_id) is None


# --- sign-in, kill switch, store configuration ----------------------------------------------------------------------


def test_FR_AGT_14_every_verb_needs_a_signed_in_principal(sched: SchedApi) -> None:
    task = sched.approved_task()
    schedule_id = sched.created(task)["schedule_id"]
    sched.sign_out()
    results = [
        sched.create(task),
        sched.listing(),
        sched.get(schedule_id),
        sched.patch(schedule_id, enabled=False),
        sched.delete(schedule_id),
    ]
    assert [r.status_code for r in results] == [401] * 5
    assert _stored(sched, schedule_id).enabled is True


def test_FR_AGT_14_replay_only_refuses_every_write_and_leaves_reads_alone(sched: SchedApi) -> None:
    task = sched.approved_task()
    other = sched.approved_task()
    schedule_id = sched.created(task)["schedule_id"]
    sched.flags.set("replay_only", True, reason="NFR-24 test")

    refused = [sched.create(other), sched.patch(schedule_id, enabled=False), sched.delete(schedule_id)]
    for response in refused:
        assert response.status_code == 503, response.text
        assert response.json()["replay_only"] is True
    assert sched.listing().status_code == 200 and sched.get(schedule_id).status_code == 200
    assert [s.schedule_id for s in sched.schedules.list_for_owner(FLOW_USER)] == [schedule_id]
    assert _stored(sched, schedule_id).enabled is True

    sched.flags.set("replay_only", False, reason="cleared")
    assert sched.patch(schedule_id, enabled=False).status_code == 200


def test_FR_AGT_14_with_no_schedule_store_configured_every_route_is_503_not_configured(sched: SchedApi) -> None:
    from tilo_api import schedules

    task = sched.approved_task()
    del sched.app.dependency_overrides[schedules.get_schedule_store]
    getattr(schedules.get_schedule_store, "cache_clear", lambda: None)()
    results = [sched.create(task), sched.listing(), sched.get("sched_x"), sched.patch("sched_x", enabled=False)]
    results.append(sched.delete("sched_x"))
    for response in results:
        assert response.status_code == 503, response.text
        assert response.json()["detail"] == "not_configured"


def test_FR_AGT_14_the_default_store_is_memory_in_dev_mode_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException
    from tilo_api import schedules
    from tilo_harness.schedule_store import InMemoryScheduleStore

    clear = getattr(schedules.get_schedule_store, "cache_clear", lambda: None)
    for name in (ENV_STORE, "TILO_API_DEV", "K_SERVICE", "CLOUD_RUN_JOB", "LIVE", "TILO_FIRESTORE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    clear()
    with pytest.raises(HTTPException) as refused:  # not dev, no config: refuses
        schedules.get_schedule_store()
    assert refused.value.status_code == 503

    monkeypatch.setenv("TILO_API_DEV", "1")
    clear()
    assert isinstance(schedules.get_schedule_store(), InMemoryScheduleStore)  # dev default

    monkeypatch.setenv("K_SERVICE", "tilo-api")  # deployed: dev mode never opens the in-memory default
    clear()
    with pytest.raises(HTTPException) as deployed:
        schedules.get_schedule_store()
    assert deployed.value.status_code == 503

    monkeypatch.delenv("K_SERVICE")
    monkeypatch.delenv("TILO_API_DEV")
    monkeypatch.setenv(ENV_STORE, "memory")  # or by explicit name
    clear()
    assert isinstance(schedules.get_schedule_store(), InMemoryScheduleStore)
    clear()


def test_FR_AGT_14_firestore_is_chosen_only_by_explicit_config_and_never_opens_a_client_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException
    from google.cloud import firestore
    from tilo_api import schedules

    built: list[Any] = []

    def bomb(*args: Any, **kwargs: Any) -> Any:
        built.append((args, kwargs))
        raise AssertionError("a live Firestore client was opened")

    monkeypatch.setattr(firestore, "Client", bomb)
    clear = getattr(schedules.get_schedule_store, "cache_clear", lambda: None)
    for name in ("TILO_API_DEV", "K_SERVICE", "TILO_FIRESTORE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ENV_STORE, "firestore")  # the switch alone, no project
    clear()
    with pytest.raises(HTTPException) as refused:
        schedules.get_schedule_store()
    assert refused.value.status_code == 503 and built == []
    clear()
