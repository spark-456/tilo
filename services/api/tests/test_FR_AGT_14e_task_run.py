"""FR-AGT-14e (Cloud Tasks hand-off; PRD 6.3, 8.6, SEC-05; design decision 1, second caller): a task's delivery.

Cloud Tasks calls the SAME route, `POST /internal/schedules/tick`, as `TILO_TASKS_CALLER` with the task's JSON body
(`schedule_id`, `slot`, `due`). That caller executes exactly ONE run: the route re-reads the schedule record,
never takes an owner, brief, approach or cap from the body, grants the budget only through the owner's own L3
policy (`ScheduleStarter.start`), then waits INSIDE the request until the run finished or is parked at a person (a
gate can wait 24 h), or until the in-request deadline, and answers 200
`{"ran": 1, "state": "done" | "parked" | "timeout"}`.

- a start that fails (or the run seams are unwired) answers a fixed 5xx so Cloud Tasks retries; the ids are
  deterministic from the slot, so the retry meets the world the failed start made instead of starting a second run;
- a permanent refusal (record gone, disabled, owner mismatch, no budget policy, no snapshot) answers 200
  `{"ran": 0, "skipped": "<code>"}`: Cloud Tasks must not retry it;
- a body that is not exactly what a task carries is 422; a slot that is not a slot of that schedule is refused without a
  run; the Scheduler identity can never execute a run and the Tasks identity can never fan out.

API_FR_AGT_14e.md. Fakes: `_fr_agt_14_lib.py`, `_fr_agt_14e_lib.py`, the CL-INT-2 run seams (scripted unit runner).
"""

from __future__ import annotations

import dataclasses
import threading
import time
from datetime import timedelta
from typing import Any

import pytest
from _api_contracts_lib import assert_valid_event
from _clint2_lib import REPO_ROOT, settle, wait_for
from _fr_agt_14_lib import (
    API_SA,
    AUDIENCE,
    ENV_QUEUE,
    ENV_TASKS_CALLER,
    FLOW_USER,
    GMAIL_SA,
    GOOGLE_ISSUER,
    MON_0330Z,
    SCHEDULE_SA,
    TASKS_SA,
    WEEK,
    SchedApi,
    bearer,
    l3_budget_policy,
    task_body,
    task_payload,
)
from _fr_agt_14e_lib import (
    POLICY_ID,
    armed,
    assert_record_untouched,
    assert_unchanged,
    block_network,
    gateless,
    refused,
    run_start,
    snapshot,
)
from fastapi.testclient import TestClient
from tilo_harness.schedule import slot_key


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    return block_network(monkeypatch)


@pytest.fixture
def rig(run_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(run_flow.flow, monkeypatch, rf=run_flow)
    rig.clock.set(MON_0330Z)
    return rig


def execute(rig: SchedApi, schedule_id: str = "sched_a", due: Any = MON_0330Z):
    return rig.task_call(task_body(schedule_id, due))


def stream_of(rig: SchedApi, world_id: str) -> list[dict[str, Any]]:
    settle(lambda: len(rig.events(world_id)), quiet_s=0.5)
    return rig.events(world_id)


def types(rig: SchedApi, world_id: str) -> list[str]:
    return [e["type"] for e in rig.events(world_id)]


def only_world(rig: SchedApi, source: Any) -> str:
    (world_id,) = rig.worlds_besides(source.world_id)
    return world_id


def scheduled(rig: SchedApi, **policy: Any) -> Any:
    """The owner's approved source task, a standing L3 budget policy and one due schedule `sched_a`."""
    source = armed(rig, **policy)
    rig.insert(source, "sched_a")
    return source


# --- one delivery, one run -------------------------------------------------------------------------


def test_FR_AGT_14e_a_task_executes_exactly_one_run_for_its_slot(rig: SchedApi) -> None:
    source = scheduled(rig)
    compiled = len(rig.rf.compile_calls)
    response = execute(rig)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ran"] == 1 and set(body) == {"ran", "state"}
    assert (
        body["state"] == "parked"
    )  # the scripted plan ends in a send: the run waits at its gate card, not in the request
    world_id = only_world(rig, source)
    assert rig.events(world_id, "approval.requested"), "answered before the gate existed"
    assert rig.store.worlds[world_id].owner == FLOW_USER
    stream = stream_of(rig, world_id)
    first = stream[0]
    assert (first["type"], first["seq"], first["actor"]) == ("world.requested", 1, FLOW_USER)
    assert first["data"]["channel"] == "schedule"
    (grant,) = [e for e in stream if e["type"] == "budget.granted"]
    assert (grant["authz"]["by"], grant["authz"]["ref"]) == ("policy", POLICY_ID)  # the owner's rule, never a person
    assert len(rig.rf.compile_calls) == compiled + 1
    assert rig.rf.compile_calls[-1]["brief"] == rig.schedules.get("sched_a").brief  # from the stored snapshot
    # the ids are the starter's own deterministic ones: starting the same slot again meets this very world
    assert rig.starter().start(run_start(rig, "sched_a")) == world_id
    assert rig.worlds_besides(source.world_id) == [world_id]


def test_FR_AGT_14e_a_duplicate_delivery_gives_one_world_one_run_and_a_2xx(rig: SchedApi) -> None:
    source = scheduled(rig)
    ran_before = list(rig.rf.runner.ran)
    first, second = execute(rig), execute(rig)
    assert first.status_code == 200 and first.json()["ran"] == 1
    assert 200 <= second.status_code < 300  # a duplicate is answered, never retried (what it says is not pinned)
    world_id = only_world(rig, source)
    stream_of(rig, world_id)
    for once in ("world.requested", "budget.granted", "world.started"):
        assert types(rig, world_id).count(once) == 1, once
    assert rig.rf.runner.ran[len(ran_before) :] == ["U1", "U2", "U3", "U4"]  # the work executed once


def test_FR_AGT_14e_concurrent_deliveries_of_one_task_still_meet_one_world_and_one_run(rig: SchedApi) -> None:
    source = scheduled(rig)
    ran_before = list(rig.rf.runner.ran)
    results: list[Any] = []
    lock, barrier = threading.Lock(), threading.Barrier(3)

    def deliver() -> None:
        client = TestClient(rig.app, raise_server_exceptions=False)  # a connection of its own, as Cloud Tasks has
        barrier.wait(timeout=10)
        response = client.post(
            "/internal/schedules/tick", headers=bearer(rig.tasks_token), json=task_body("sched_a", MON_0330Z)
        )
        with lock:
            results.append((response.status_code, response.json()))

    threads = [threading.Thread(target=deliver, daemon=True) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(results) == 3 and all(status == 200 for status, _body in results), results
    assert any(body.get("ran") == 1 for _status, body in results), results
    world_id = only_world(rig, source)
    stream_of(rig, world_id)
    for once in ("world.requested", "budget.granted", "world.started"):
        assert types(rig, world_id).count(once) == 1, once
    assert rig.rf.runner.ran[len(ran_before) :] == ["U1", "U2", "U3", "U4"]


def test_FR_AGT_14e_a_late_delivery_of_a_past_slot_still_runs(rig: SchedApi) -> None:
    """Cloud Tasks retries after its backoff: the slot is only ever in the past (never ahead of the clock)."""
    source = scheduled(rig)
    rig.clock.set(MON_0330Z + timedelta(hours=3))
    assert execute(rig).status_code == 200
    assert len(rig.worlds_besides(source.world_id)) == 1


def test_FR_AGT_14e_the_run_goes_on_after_the_request_returned_and_a_person_still_approves_its_gate(
    rig: SchedApi,
) -> None:
    source = scheduled(rig)
    assert execute(rig).json()["state"] == "parked"
    world_id = only_world(rig, source)
    sent_by_source = len(rig.rf.adapter.sent)
    rig.as_owner_of(world_id)
    cards = rig.flow.client.get(f"/worlds/{world_id}/cards")
    assert cards.status_code == 200
    (card,) = [c for c in cards.json() if c["kind"] == "gate"]
    answered = rig.flow.client.post(f"/worlds/{world_id}/cards/{card['id']}/answer", json={"option": "approve"})
    assert answered.status_code == 200, answered.text
    wait_for(lambda: rig.events(world_id, "world.completed"), what="the scheduled run to complete")
    (resolved,) = rig.events(world_id, "approval.resolved")
    assert (resolved["authz"]["by"], resolved["authz"]["ref"]) == ("person", FLOW_USER)  # T3 still needs a person
    assert len(rig.rf.adapter.sent) == sent_by_source + 1


def test_FR_AGT_14e_the_owner_is_the_records_never_the_bodys(rig: SchedApi) -> None:
    source = armed(rig)
    rig.store.policies["pol_other"] = l3_budget_policy("u_other", id_="pol_other")
    rig.insert(source, "sched_o", owner_user_id="u_other")
    response = execute(rig, "sched_o")
    assert response.status_code == 200 and response.json()["ran"] == 1, response.text
    world_id = only_world(rig, source)
    assert rig.store.worlds[world_id].owner == "u_other"
    stream = stream_of(rig, world_id)
    for event in stream:
        if event["type"] in ("world.requested", "budget.granted"):
            assert event["actor"] != FLOW_USER and (event.get("authz") or {}).get("ref") != FLOW_USER
    assert [e["authz"]["ref"] for e in stream if e["type"] == "budget.granted"] == ["pol_other"]


# --- a run that cannot start is retried, never doubled ---------------------------------------------


def test_FR_AGT_14e_a_start_that_fails_answers_a_fixed_5xx_and_the_retry_meets_the_same_world(
    rig: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import runs

    source = scheduled(rig)
    original, calls = runs.start_run, []
    texts = [
        "scheduler says: api key s3cret-value for alice@example.com is invalid",
        "a different failure with hunter2 in it",
    ]

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) <= 2:
            raise RuntimeError(texts[len(calls) - 1])
        return original(*args, **kwargs)

    monkeypatch.setattr(runs, "start_run", flaky)
    first, second = execute(rig), execute(rig)
    for response in (first, second):
        assert 500 <= response.status_code < 600, response.status_code  # Cloud Tasks retries a non-2xx
        for leaked in ("s3cret", "alice", "hunter2", "scheduler says", "Traceback"):
            assert leaked not in response.text
    assert first.json() == second.json()  # a fixed body: nothing of the failure shows
    third = execute(rig)
    assert third.status_code == 200 and third.json()["ran"] == 1, third.text
    world_id = only_world(rig, source)  # whatever the failed attempts made is this very world
    stream_of(rig, world_id)
    for once in ("world.requested", "budget.granted", "world.started"):
        assert types(rig, world_id).count(once) == 1, once
    assert len(calls) == 3


def test_FR_AGT_14e_unwired_run_seams_are_retryable_and_count_nothing_against_the_schedule(rig: SchedApi) -> None:
    from tilo_api import schedules

    source = scheduled(rig)
    before = snapshot(rig)
    rig.app.dependency_overrides[schedules.get_seams_factory] = lambda: lambda: None
    for _ in range(3):
        response = execute(rig)
        assert 500 <= response.status_code < 600 and "Traceback" not in response.text
    assert_unchanged(rig, before)
    assert_record_untouched(
        rig, "sched_a"
    )  # no failure, no backoff, no disabling: the whole service, not this schedule
    del rig.app.dependency_overrides[schedules.get_seams_factory]  # wired again
    assert execute(rig).json()["ran"] == 1  # the very same task, delivered again
    assert len(rig.worlds_besides(source.world_id)) == 1


# --- permanent refusals: 2xx and a fixed body, so Cloud Tasks does not retry -----------------------


def _disable(rig: SchedApi) -> None:
    assert rig.schedules.update("sched_a", enabled=False) is not None


def _erase_owner(rig: SchedApi) -> None:
    assert rig.schedules.disable_for_owner(FLOW_USER) == 1


def _no_policy(rig: SchedApi) -> None:
    del rig.store.policies[POLICY_ID]


def _other_owners_policy(rig: SchedApi) -> None:
    del rig.store.policies[POLICY_ID]
    rig.store.policies["pol_theirs"] = l3_budget_policy("u_other", id_="pol_theirs")


def _gone(rig: SchedApi) -> None:
    assert rig.schedules.delete("sched_a") is True


PERMANENT = [
    pytest.param(_gone, "schedule_missing", id="the schedule is gone (erased)"),
    pytest.param(_disable, "schedule_disabled", id="the schedule is disabled"),
    pytest.param(_erase_owner, "schedule_disabled", id="the owner was erased"),
    pytest.param(_no_policy, "budget_not_granted", id="no budget policy"),
    pytest.param(_other_owners_policy, "budget_not_granted", id="only another owner's policy"),
]


@pytest.mark.parametrize(("break_it", "code"), PERMANENT)
def test_FR_AGT_14e_a_permanent_refusal_is_a_2xx_with_a_fixed_body_and_runs_nothing(
    rig: SchedApi, break_it: Any, code: str
) -> None:
    scheduled(rig)
    break_it(rig)
    before = snapshot(rig)
    for _ in range(2):  # a retry would meet the same answer
        response = execute(rig)
        assert 200 <= response.status_code < 300, response.status_code
        assert response.json() == {"ran": 0, "skipped": code}
    assert_unchanged(rig, before)


def test_FR_AGT_14e_a_record_with_no_snapshot_is_a_permanent_refusal(rig: SchedApi) -> None:
    source = armed(rig)
    rig.insert(source, "sched_a", brief=None)
    before = snapshot(rig)
    response = execute(rig)
    assert 200 <= response.status_code < 300 and response.json() == {"ran": 0, "skipped": "snapshot_missing"}
    assert_unchanged(rig, before)


def test_FR_AGT_14e_a_world_that_belongs_to_someone_else_is_a_permanent_refusal(rig: SchedApi) -> None:
    source = scheduled(rig)
    assert execute(rig).json()["ran"] == 1
    world_id = only_world(rig, source)
    stream_of(rig, world_id)
    rig.store.worlds[world_id] = dataclasses.replace(rig.store.worlds[world_id], owner="u_other")
    before = snapshot(rig)
    response = execute(rig)
    assert 200 <= response.status_code < 300 and response.json() == {"ran": 0, "skipped": "owner_mismatch"}
    assert_unchanged(rig, before)


def test_FR_AGT_14e_replay_only_blocks_the_tasks_mode_too(rig: SchedApi) -> None:
    source = scheduled(rig)
    before = snapshot(rig)
    rig.flags.set("replay_only", True, reason="NFR-24 test")
    response = execute(rig)
    assert response.status_code == 503, (response.status_code, response.text)  # BQ-AGT14-5 R4: Cloud Tasks retries it
    assert "Traceback" not in response.text
    assert_unchanged(rig, before)
    assert_record_untouched(rig, "sched_a")
    assert rig.worlds_besides(source.world_id) == []
    rig.flags.set("replay_only", False, reason="cleared")
    assert execute(rig).json()["ran"] == 1  # the same task, delivered again once the flag is clear


# --- the body is untrusted -------------------------------------------------------------------------

GOOD = task_body("sched_a", MON_0330Z)
EXTRA = [
    ("owner_user_id", "u_other"),
    ("brief", {"title": "x"}),
    ("approach", {"id": "quick"}),
    ("budget_cap", 9999),
    ("cap", 9999),
    ("title", "Hijacked"),
    ("world_id", "w_x"),
    ("idempotency_key", "k"),
    ("extra", 1),
]  # fmt: skip  (BQ-AGT14-5 R1: `skipped` and `prior_world_id` left this list: they are the two server-written fields)


@pytest.mark.parametrize(("key", "value"), EXTRA, ids=[k for k, _ in EXTRA])
def test_FR_AGT_14e_an_unknown_field_is_422_and_nothing_is_read_from_it(rig: SchedApi, key: str, value: Any) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.task_call({**GOOD, key: value})
    assert response.status_code == 422, response.text
    assert "u_other" not in response.text and "Hijacked" not in response.text  # a 422 never echoes the input
    assert_unchanged(rig, before)
    assert_record_untouched(rig, "sched_a")


BAD_BODIES = [pytest.param({k: v for k, v in GOOD.items() if k != missing}, id=f"no {missing}") for missing in GOOD] + [
    pytest.param({**GOOD, "schedule_id": 5}, id="schedule_id is a number"),
    pytest.param({**GOOD, "schedule_id": None}, id="schedule_id is null"),
    pytest.param({**GOOD, "schedule_id": ["sched_a"]}, id="schedule_id is a list"),
    pytest.param({**GOOD, "slot": 5}, id="slot is a number"),
    pytest.param({**GOOD, "slot": None}, id="slot is null"),
    pytest.param({**GOOD, "due": 5}, id="due is a number"),
    pytest.param({**GOOD, "due": None}, id="due is null"),
    pytest.param({**GOOD, "due": "not a date"}, id="due is no date"),
    pytest.param({**GOOD, "due": ""}, id="due is empty"),
    pytest.param([], id="a list"),
    pytest.param("sched_a", id="a string"),
    pytest.param(5, id="a number"),
    pytest.param(None, id="null"),
    pytest.param({}, id="an empty object"),
]


@pytest.mark.parametrize("body", BAD_BODIES)
def test_FR_AGT_14e_a_body_that_is_not_exactly_a_task_is_422(rig: SchedApi, body: Any) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.task_call(body)
    assert response.status_code == 422, response.text
    assert "Traceback" not in response.text
    assert_unchanged(rig, before)


MALFORMED_IDS = [
    "", "sched_", "SCHED_A", "sched-a", "../sched_a", "sched_a/x", "sched_a\n", " sched_a", "sched_a ", "x",
    "sched_" + "x" * 65, "sched_é", "sched_a;drop", "sched_*", "orgs/o/schedules/sched_a",
]  # fmt: skip


@pytest.mark.parametrize("schedule_id", MALFORMED_IDS, ids=[repr(i)[:30] for i in MALFORMED_IDS])
def test_FR_AGT_14e_a_schedule_id_that_is_not_an_id_is_422(rig: SchedApi, schedule_id: str) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.task_call(
        {"schedule_id": schedule_id, "slot": f"{schedule_id}:{GOOD['due']}", "due": GOOD["due"]},
    )
    assert response.status_code == 422, (schedule_id, response.status_code, response.text)
    assert_unchanged(rig, before)


@pytest.mark.parametrize("due", ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00"])
def test_FR_AGT_14e_a_due_that_overflows_the_calendar_is_422_not_a_500(rig: SchedApi, due: str) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.task_call({"schedule_id": "sched_a", "slot": f"sched_a:{due}", "due": due})
    assert response.status_code == 422, (due, response.status_code, response.text)
    assert "Traceback" not in response.text and due not in response.text
    assert_unchanged(rig, before)


def test_FR_AGT_14e_the_first_instant_of_the_calendar_is_no_slot_and_runs_nothing(rig: SchedApi) -> None:
    scheduled(rig)
    before = snapshot(rig)
    due = "0001-01-01T00:00:00+00:00"  # a well-formed UTC instant whose predecessor does not exist
    response = rig.task_call({"schedule_id": "sched_a", "slot": f"sched_a:{due}", "due": due})
    assert (response.status_code, response.json()) == (200, {"ran": 0, "skipped": "slot_off_cadence"})
    assert_unchanged(rig, before)


def test_FR_AGT_14e_only_a_json_body_is_read(rig: SchedApi) -> None:
    scheduled(rig)
    before = snapshot(rig)
    wrong = rig.flow.client.post(
        "/internal/schedules/tick",
        headers={**bearer(rig.tasks_token), "content-type": "text/plain"},
        content=b'{"schedule_id": "sched_a"}',
    )
    broken = rig.flow.client.post(
        "/internal/schedules/tick",
        headers={**bearer(rig.tasks_token), "content-type": "application/json"},
        content=b"{",
    )
    assert wrong.status_code in (415, 422) and broken.status_code == 422
    assert_unchanged(rig, before)


FORGED = {
    "the slot of another schedule": {**GOOD, "slot": slot_key("sched_b", MON_0330Z)},
    "a slot key for another instant": {**GOOD, "slot": slot_key("sched_a", MON_0330Z + WEEK)},
    "a slot key with another schedule's prefix and this due": {**GOOD, "slot": f"sched_b:{GOOD['due']}"},
    "a slot that has not come yet": task_body("sched_a", MON_0330Z + WEEK),
    "a slot far in the future": task_body("sched_a", MON_0330Z + 52 * WEEK),
    "a slot off the cadence (an hour late)": task_body("sched_a", MON_0330Z + timedelta(hours=1)),
    "a slot off the cadence (the day before)": task_body("sched_a", MON_0330Z - timedelta(days=1)),
    "a slot off the cadence (a microsecond late)": task_body("sched_a", MON_0330Z + timedelta(microseconds=1)),
    "a naive instant": {**GOOD, "slot": "sched_a:2026-10-05T03:30:00", "due": "2026-10-05T03:30:00"},
    "the same instant spelled another way": {**GOOD, "due": "2026-10-05T03:30:00Z"},
    "the same instant in another offset": {**GOOD, "due": "2026-10-05T09:00:00+05:30"},
}


@pytest.mark.parametrize("label", sorted(FORGED))
def test_FR_AGT_14e_a_forged_slot_is_refused_without_a_run(rig: SchedApi, label: str) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.task_call(FORGED[label])
    assert refused(response), (label, response.status_code, response.text)  # 422, or a 2xx that ran nothing
    assert "Traceback" not in response.text
    assert_unchanged(rig, before)
    assert_record_untouched(rig, "sched_a")


def test_FR_AGT_14e_a_forged_slot_answers_a_fixed_code_not_the_input(rig: SchedApi) -> None:
    scheduled(rig)
    response = rig.task_call(FORGED["a slot that has not come yet"])
    if response.status_code != 422:
        body = response.json()
        assert set(body) == {"ran", "skipped"} and body["ran"] == 0
        assert isinstance(body["skipped"], str) and body["skipped"].isidentifier() and body["skipped"].islower()


# --- two callers, two modes: never crossed ---------------------------------------------------------


def _claimable(rig: SchedApi, schedule_id: str = "sched_a") -> bool:
    won = rig.schedules.claim(schedule_id, MON_0330Z)
    if won:
        rig.schedules.release(schedule_id, MON_0330Z)
    return won


def test_FR_AGT_14e_the_scheduler_identity_can_never_execute_a_run(rig: SchedApi) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.tick(rig.good_token, json=GOOD)  # the Scheduler's token with a task's body
    assert response.status_code in (403, 422), response.status_code
    for leaked in (SCHEDULE_SA, TASKS_SA, "iam.gserviceaccount.com", "Traceback"):
        assert leaked not in response.text
    assert_unchanged(rig, before)
    assert rig.tasks.calls == []  # not a fan-out either
    assert_record_untouched(rig, "sched_a")
    assert _claimable(rig)  # and nothing was claimed


def test_FR_AGT_14e_the_tasks_identity_can_never_fan_out(rig: SchedApi) -> None:
    source = scheduled(rig)
    rig.insert(source, "sched_b")
    before = snapshot(rig)
    url, headers = "/internal/schedules/tick", bearer(rig.tasks_token)
    responses = [
        rig.flow.client.post(url, headers=headers),  # no body: what the Scheduler sends
        rig.flow.client.post(url, headers=headers, json={}),
        rig.flow.client.post(url + "?force=true&schedule_id=sched_a", headers=headers),
    ]
    for response in responses:
        assert response.status_code in (403, 422), response.status_code
        assert "Traceback" not in response.text and TASKS_SA not in response.text
    assert rig.tasks.calls == [], "the Tasks identity caused a fan-out"
    assert_unchanged(rig, before)
    for schedule_id in ("sched_a", "sched_b"):
        assert_record_untouched(rig, schedule_id)
        assert _claimable(rig, schedule_id)


WRONG_TASK_CALLERS = [
    ("gmail scheduler", {"email": GMAIL_SA}),
    ("tilo-api itself", {"email": API_SA}),
    ("a person", {"email": "someone@example.com"}),
    ("same account name, another project", {"email": "tilo-tasks-invoker@other-project.iam.gserviceaccount.com"}),
    ("upper-cased address", {"email": TASKS_SA.upper()}),
    ("padded address", {"email": f" {TASKS_SA}"}),
    ("prefix of the address", {"email": TASKS_SA[:-5]}),
    ("no email claim", {"email": None, "drop": ("email",)}),
    ("email is a list", {"email": [TASKS_SA]}),
    ("email not verified", {"email_verified": False}),
    ("email_verified is the string true", {"email_verified": "true"}),
    ("email_verified is null", {"email_verified": None}),
    ("no email_verified claim", {"drop": ("email_verified",)}),
    ("another audience", {"aud": "https://tilo-harness-abc123-as.a.run.app"}),
    ("audience is a list", {"aud": [AUDIENCE]}),
    ("audience with a slash", {"aud": AUDIENCE + "/"}),
    ("no aud claim", {"drop": ("aud",)}),
    ("another issuer", {"iss": "https://evil.example.com"}),
    ("a look-alike issuer", {"iss": "https://accounts.google.com.evil.test"}),
    ("no iss claim", {"drop": ("iss",)}),
]


@pytest.mark.parametrize(("label", "claims"), WRONG_TASK_CALLERS, ids=[w[0] for w in WRONG_TASK_CALLERS])
def test_FR_AGT_14e_any_other_caller_of_a_task_shaped_request_is_refused(
    rig: SchedApi, label: str, claims: dict[str, Any]
) -> None:
    scheduled(rig)
    before = snapshot(rig)
    token = rig.verifier.register(**{"email": TASKS_SA, "iss": GOOGLE_ISSUER, **claims})
    response = rig.task_call(GOOD, token)
    assert response.status_code in (401, 403), (label, response.status_code)
    for secret in (token, TASKS_SA, "iam.gserviceaccount.com", "someone@example.com", "Traceback"):
        assert secret not in response.text, label
    assert rig.verifier.calls == [(token, AUDIENCE)]  # asked for the configured audience
    assert_unchanged(rig, before)
    assert rig.tasks.calls == []


def test_FR_AGT_14e_a_task_shaped_request_with_no_bearer_is_401(rig: SchedApi) -> None:
    scheduled(rig)
    before = snapshot(rig)
    for headers in ({}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}):
        assert rig.task_call(GOOD, headers=headers).status_code == 401
    assert rig.verifier.calls == []
    assert_unchanged(rig, before)


def test_FR_AGT_14e_one_identity_for_both_modes_fails_closed(rig: SchedApi, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the two callers were configured to the SAME account the identity could no longer decide the mode: the route
    must not guess (a Scheduler call would then run work, or a Tasks call would fan out)."""
    scheduled(rig)
    before = snapshot(rig)
    monkeypatch.setenv(ENV_TASKS_CALLER, SCHEDULE_SA)
    for response in (rig.tick(), rig.tick(rig.good_token, json=GOOD)):
        assert response.status_code in (403, 503), response.status_code
    assert rig.tasks.calls == []
    assert_unchanged(rig, before)
    assert _claimable(rig)


# --- the wait inside the request -------------------------------------------------------------------


def test_FR_AGT_14e_a_run_that_completes_without_a_person_answers_done(rig: SchedApi) -> None:
    source = scheduled(rig)
    gateless(rig)
    response = execute(rig)
    assert response.status_code == 200 and response.json() == {"ran": 1, "state": "done"}, response.text
    world_id = only_world(rig, source)
    assert rig.events(world_id, "world.completed"), "answered before the run was done"
    assert rig.events(world_id, "approval.requested") == []


def test_FR_AGT_14e_a_run_that_is_still_working_at_the_in_request_deadline_answers_200_and_goes_on(
    rig: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import schedules

    source = scheduled(rig)
    monkeypatch.setattr(schedules, "IN_REQUEST_DEADLINE_S", 0.3)  # the one tiny real wait of the suite
    rig.rf.runner.block_on = "U1"
    started = time.monotonic()
    response = execute(rig)
    elapsed = time.monotonic() - started
    assert response.status_code == 200 and response.json() == {"ran": 1, "state": "timeout"}, response.text
    assert 0.25 <= elapsed < 30, elapsed  # it waited for the deadline, not for the run
    assert rig.rf.runner.entered.wait(timeout=10)  # the run thread was only slower than the 0.3 s deadline to get here
    world_id = only_world(rig, source)
    assert not rig.events(world_id, "world.completed") and not rig.events(world_id, "approval.requested")
    rig.rf.runner.release.set()  # the unit finishes: the run (its own thread) carries on to its gate
    wait_for(lambda: rig.events(world_id, "approval.requested"), what="the run to reach its gate")


def test_FR_AGT_14e_the_default_in_request_deadline_is_under_the_dispatch_deadline_with_room_to_answer() -> None:
    from tilo_api import schedules

    assert 20 * 60 <= schedules.IN_REQUEST_DEADLINE_S <= schedules.DISPATCH_DEADLINE_S - 60


# --- fan-out then delivery, end to end -------------------------------------------------------------


def test_FR_AGT_14e_the_fan_out_then_the_delivery_runs_the_slot_once_and_records_its_world(rig: SchedApi) -> None:
    source = scheduled(rig)
    assert rig.tick().json() == {"fired": 1}
    assert rig.worlds_besides(source.world_id) == [], "the tick itself ran nothing"
    assert rig.deliver_new_tasks() == 1
    world_id = only_world(rig, source)
    record = rig.schedules.get("sched_a")
    assert (record.last_world_id, record.next_due, record.last_slot) == (
        world_id,
        MON_0330Z + WEEK,
        slot_key("sched_a", MON_0330Z),
    )
    assert rig.starter().start(run_start(rig, "sched_a")) == world_id  # one world per slot, whoever starts it
    assert rig.tick().json() == {"fired": 0} and len(rig.tasks.calls) == 1
    redelivered = rig.task_call(task_payload(rig.tasks.calls[0]))
    assert redelivered.status_code == 200
    assert rig.worlds_besides(source.world_id) == [world_id]  # still one
    stream_of(rig, world_id)


def test_FR_AGT_14e_missed_slots_run_once_and_the_new_world_still_starts_with_world_requested(rig: SchedApi) -> None:
    source = scheduled(rig)
    latest = MON_0330Z + 3 * WEEK
    rig.clock.set(latest + timedelta(days=2))
    assert rig.tick().json() == {"fired": 1}
    assert rig.deliver_new_tasks() == 1
    world_id = only_world(rig, source)
    stream = stream_of(rig, world_id)
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))
    assert stream[0]["type"] == "world.requested"  # nothing (not the missed-slots alert) came before it
    (alert,) = [e for e in stream if e["type"] == "alert.raised"]  # BQ-AGT14-5 R2: the delivery raises it, once
    assert alert["seq"] > 1 and alert["severity"] == "info" and "3" in alert["summary"]
    assert len(rig.worlds_besides(source.world_id)) == 1  # no backfill storm


def test_FR_AGT_14e_a_world_is_never_its_own_prior_world(rig: SchedApi) -> None:
    source = scheduled(rig)
    worlds: list[str] = []
    for week in (0, 1):
        rig.clock.set(MON_0330Z + week * WEEK)
        assert rig.tick().json() == {"fired": 1}
        assert rig.deliver_new_tasks() == 1
        (new,) = [w for w in rig.worlds_besides(source.world_id) if w not in worlds]
        worlds.append(new)
        stream_of(rig, new)
    assert worlds[0] != worlds[1]
    for world_id in worlds:
        assert rig.store.worlds[world_id].prior_world_id != world_id
    assert rig.schedules.get("sched_a").last_world_id == worlds[1]


# --- BQ-AGT14-5 R1: the two server-written fields, `skipped` and `prior_world_id`, are untrusted data -------


def test_FR_AGT_14e_skipped_and_the_prior_world_are_taken_as_data_within_their_bounds(rig: SchedApi) -> None:
    source = scheduled(rig)
    response = rig.task_call(task_body("sched_a", MON_0330Z, skipped=99_999, prior_world_id=source.world_id))
    assert response.status_code == 200 and response.json() == {"ran": 1, "state": "parked"}, response.text
    world_id = only_world(rig, source)
    assert rig.store.worlds[world_id].prior_world_id == source.world_id  # offered to the new world, never reused
    assert rig.store.worlds[world_id].owner == FLOW_USER  # and nothing in the body made it anyone else's


def test_FR_AGT_14e_a_body_without_the_two_fields_means_none_skipped_and_no_prior_world(rig: SchedApi) -> None:
    source = scheduled(rig)
    assert rig.task_call(task_body("sched_a", MON_0330Z, skipped=0, prior_world_id=None)).json()["ran"] == 1
    world_id = only_world(rig, source)
    assert rig.store.worlds[world_id].prior_world_id is None
    assert "alert.raised" not in types(rig, world_id)


BAD_SKIPPED = [-1, 100_001, 10**12, True, 2.5, "3", None, [3], {"n": 3}]
BAD_PRIOR = [
    "", "w_", "x_abc", "sched_a", "w_" + "x" * 49, "w_a/b", "w_a b", "W_abc", "w_é", " w_abc", "w_abc\n",
    5, True, ["w_a"], {"id": "w_a"},
]  # fmt: skip


@pytest.mark.parametrize("skipped", BAD_SKIPPED, ids=[repr(v)[:20] for v in BAD_SKIPPED])
def test_FR_AGT_14e_a_skipped_count_out_of_bounds_or_of_the_wrong_type_is_422(rig: SchedApi, skipped: Any) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.task_call(task_body("sched_a", MON_0330Z, skipped=skipped))
    assert response.status_code == 422, (skipped, response.status_code, response.text)
    assert_unchanged(rig, before)
    assert_record_untouched(rig, "sched_a")


@pytest.mark.parametrize("prior", BAD_PRIOR, ids=[repr(v)[:20] for v in BAD_PRIOR])
def test_FR_AGT_14e_a_prior_world_that_is_not_a_world_id_is_422(rig: SchedApi, prior: Any) -> None:
    scheduled(rig)
    before = snapshot(rig)
    response = rig.task_call(task_body("sched_a", MON_0330Z, prior_world_id=prior))
    assert response.status_code == 422, (prior, response.status_code, response.text)
    assert_unchanged(rig, before)
    assert_record_untouched(rig, "sched_a")


@pytest.mark.parametrize("prior", ["w_theirs", "w_nothing_like_it"], ids=["another owner's world", "no such world"])
def test_FR_AGT_14e_a_prior_world_that_is_not_the_owners_own_is_never_recorded(rig: SchedApi, prior: str) -> None:
    """The body can name any well-formed world id (only a forged Tasks token could). The new world still starts, but a
    world the owner does not have is not offered to it: the field is data, never a way to point at someone else's."""
    from tilo_api import deps

    source = scheduled(rig)
    rig.store.worlds["w_theirs"] = deps.WorldRecord(owner="u_other", districts={}, run_id="r_theirs")
    response = rig.task_call(task_body("sched_a", MON_0330Z, prior_world_id=prior))
    assert response.status_code == 200 and response.json()["ran"] == 1, response.text
    (world_id,) = rig.worlds_besides(source.world_id, "w_theirs")
    assert rig.store.worlds[world_id].prior_world_id is None


# --- BQ-AGT14-5 R2: the collapsed-missed-slots alert is raised by the delivery --------------------------


def test_FR_AGT_14e_a_task_that_collapsed_missed_slots_raises_one_info_alert_after_world_requested(
    rig: SchedApi, registry: Any
) -> None:
    source = scheduled(rig)
    body = task_body("sched_a", MON_0330Z, skipped=3)
    assert rig.task_call(body).json()["ran"] == 1
    world_id = only_world(rig, source)
    stream = stream_of(rig, world_id)
    (alert,) = [e for e in stream if e["type"] == "alert.raised"]
    assert stream[0]["type"] == "world.requested" and alert["seq"] > 1
    assert (alert["actor"], alert["severity"], alert["target"], alert["vis"]) == ("system", "info", world_id, "all")
    assert alert["data"]["card_id"] is None and "3" in alert["summary"]
    assert_valid_event(REPO_ROOT, registry, alert)
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))
    assert rig.task_call(body).status_code == 200  # a duplicate delivery of the same task
    assert [e["type"] for e in stream_of(rig, world_id)].count("alert.raised") == 1  # raises no second alert


def test_FR_AGT_14e_an_on_time_task_raises_no_alert(rig: SchedApi) -> None:
    source = scheduled(rig)
    assert execute(rig).json()["ran"] == 1
    assert "alert.raised" not in [e["type"] for e in stream_of(rig, only_world(rig, source))]


def test_FR_AGT_14e_a_refused_task_that_names_skipped_slots_writes_no_alert_and_no_world(rig: SchedApi) -> None:
    scheduled(rig)
    _no_policy(rig)
    before = snapshot(rig)
    response = rig.task_call(task_body("sched_a", MON_0330Z, skipped=2))
    assert response.json() == {"ran": 0, "skipped": "budget_not_granted"}
    assert_unchanged(rig, before)


# --- BQ-AGT14-5 R3: a permanent refusal is recorded on the schedule as `last_error`, and only that ----------


def _swap_owner_of_the_slots_world(rig: SchedApi) -> None:
    known = set(rig.store.worlds)
    assert execute(rig).json()["ran"] == 1
    (world_id,) = set(rig.store.worlds) - known
    stream_of(rig, world_id)
    rig.store.worlds[world_id] = dataclasses.replace(rig.store.worlds[world_id], owner="u_other")


RECORDED = [
    pytest.param(_no_policy, "budget_not_granted", id="no budget policy"),
    pytest.param(_other_owners_policy, "budget_not_granted", id="only another owner's policy"),
    pytest.param(_swap_owner_of_the_slots_world, "owner_mismatch", id="the slot's world is someone else's"),
]


@pytest.mark.parametrize(("break_it", "code"), RECORDED)
def test_FR_AGT_14e_a_refusal_sets_last_error_and_nothing_else_on_the_schedule(
    rig: SchedApi, break_it: Any, code: str
) -> None:
    """Not a failure (not retried, the slot is spent): no `failures`, no backoff, and `next_due` stays."""
    scheduled(rig)
    break_it(rig)
    for _ in range(2):  # the same answer on a repeat; nothing counts up
        assert execute(rig).json() == {"ran": 0, "skipped": code}
        record = rig.schedules.get("sched_a")
        assert (record.last_error, record.failures, record.backoff_until) == (code, 0, None)
        assert (record.next_due, record.enabled, record.last_slot) == (MON_0330Z, True, None)


def test_FR_AGT_14e_a_record_with_no_snapshot_records_snapshot_missing(rig: SchedApi) -> None:
    source = armed(rig)
    rig.insert(source, "sched_a", brief=None)
    assert execute(rig).json() == {"ran": 0, "skipped": "snapshot_missing"}
    record = rig.schedules.get("sched_a")
    assert (record.last_error, record.failures, record.backoff_until, record.next_due) == (
        "snapshot_missing",
        0,
        None,
        MON_0330Z,
    )


def test_FR_AGT_14e_a_missing_or_disabled_schedule_records_nothing(rig: SchedApi) -> None:
    scheduled(rig)
    _disable(rig)
    assert execute(rig).json() == {"ran": 0, "skipped": "schedule_disabled"}
    assert rig.schedules.get("sched_a").last_error is None  # the schedule is off: the owner turned it off
    _gone(rig)
    assert execute(rig).json() == {"ran": 0, "skipped": "schedule_missing"}
    assert rig.schedules.get("sched_a") is None  # and nothing was created to hold an error


def test_FR_AGT_14e_the_next_slots_completion_clears_a_recorded_refusal(rig: SchedApi) -> None:
    """The recorded code is for the slot the task was for; the next fan-out's `complete` clears it again."""
    scheduled(rig)
    _no_policy(rig)
    assert rig.tick().json() == {"fired": 1}
    assert rig.deliver_new_tasks() == 0
    assert rig.schedules.get("sched_a").last_error == "budget_not_granted"
    rig.store.policies[POLICY_ID] = l3_budget_policy()
    rig.clock.set(MON_0330Z + WEEK)
    assert rig.tick().json() == {"fired": 1} and rig.deliver_new_tasks() == 1
    assert rig.schedules.get("sched_a").last_error is None


# --- configuration: the Tasks mode is closed too -------------------------------------------------------


def test_FR_AGT_14e_without_a_queue_the_tasks_mode_is_503_and_touches_nothing(
    rig: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled(rig)
    before = snapshot(rig)
    monkeypatch.delenv(ENV_QUEUE)
    response = execute(rig)
    assert response.status_code == 503 and "Traceback" not in response.text
    assert_unchanged(rig, before)
    assert_record_untouched(rig, "sched_a")
    monkeypatch.setenv(ENV_QUEUE, "projects/demo-tilo/locations/asia-southeast1/queues/runs")
    assert execute(rig).json()["ran"] == 1  # configured again: the same task runs
