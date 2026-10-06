"""FR-AGT-14e (Cloud Tasks hand-off; PRD 6.3, 8.6, EFF rules; design decision 1, first caller): the Scheduler's call.

`POST /internal/schedules/tick` from the Scheduler identity with NO body no longer starts anything. It claims each due
slot, hands it to Cloud Tasks (one task per slot, name = `task_name(slot_key)`, OIDC for `TILO_TASKS_CALLER`, audience =
the tick audience, a body of `schedule_id` / `slot` / `due` only, dispatch deadline 1800 s) and completes the slot as
before, so the run executes inside the task's own request (CPU allocated) and not in the tick's. API_FR_AGT_14e.md.

Fakes: `_fr_agt_14_lib.py` (`FakeTasksClient` records what it is handed; no network, enforced below).
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

import pytest
from _fr_agt_14_lib import (
    AUDIENCE,
    ENV_QUEUE,
    ENV_TASKS_CALLER,
    FLOW_USER,
    MON_0330Z,
    QUEUE,
    TASKS_SA,
    TICK,
    TITLE,
    WEEK,
    SchedApi,
    bearer,
    task_payload,
)
from _fr_agt_14e_lib import CODE, block_network, snapshot
from tilo_harness.schedule import MAX_FIRES_PER_TICK, slot_key, task_name


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    return block_network(monkeypatch)


@pytest.fixture
def sched(clear_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(clear_flow, monkeypatch)
    rig.clock.set(MON_0330Z)
    return rig


def name_of(schedule_id: str, due: Any = MON_0330Z) -> str:
    return f"{QUEUE}/tasks/{task_name(slot_key(schedule_id, due))}"


def due_schedules(rig: SchedApi, *ids: str) -> None:
    task = rig.approved_task()
    for schedule_id in ids:
        rig.insert(task, schedule_id)


# --- the interface names ---------------------------------------------------------------------------


def test_FR_AGT_14e_the_interface_names_exist() -> None:
    from tilo_api import runs, schedules

    assert schedules.ENV_QUEUE == "TILO_RUNS_QUEUE" == ENV_QUEUE
    assert schedules.ENV_TASKS_CALLER == "TILO_TASKS_CALLER" == ENV_TASKS_CALLER
    assert schedules.DISPATCH_DEADLINE_S == 1800
    assert 0 < schedules.IN_REQUEST_DEADLINE_S < schedules.DISPATCH_DEADLINE_S  # answers before Cloud Tasks gives up
    assert schedules.IN_REQUEST_DEADLINE_S == 25 * 60
    for name in ("TasksClient", "AlreadyExists", "TaskEnqueuer", "get_tasks_client_factory"):
        assert hasattr(schedules, name), name
    assert callable(getattr(runs.Run, "wait_until_parked_or_done", None))


# --- one task per due slot -------------------------------------------------------------------------


def test_FR_AGT_14e_fan_out_creates_exactly_one_task_per_due_slot(sched: SchedApi) -> None:
    due_schedules(sched, "sched_a", "sched_b")
    sched.insert(sched.approved_task(), "sched_later", next_due=MON_0330Z + 10 * WEEK)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 2})
    assert sorted(t["name"] for t in sched.tasks.calls) == sorted([name_of("sched_a"), name_of("sched_b")])
    for task in sched.tasks.calls:
        schedule_id = "sched_a" if task["name"] == name_of("sched_a") else "sched_b"
        assert task["name"].startswith(QUEUE + "/tasks/sched-")  # the queue, and the harness's stable task id
        assert set(task) <= {"name", "httpRequest", "dispatchDeadline"}  # retry policy stays with the queue
        assert task["dispatchDeadline"] == "1800s"
        request = task["httpRequest"]
        assert set(request) <= {"httpMethod", "url", "headers", "body", "oidcToken"}
        assert request["httpMethod"] == "POST"
        assert request["url"] == AUDIENCE + TICK  # the tick route of the audience itself: no new route, no other host
        assert request["oidcToken"] == {"serviceAccountEmail": TASKS_SA, "audience": AUDIENCE}
        headers = {k.lower(): v for k, v in request.get("headers", {}).items()}
        assert headers.get("content-type") == "application/json" and "authorization" not in headers
        body = task_payload(task)
        assert set(body) == {"schedule_id", "slot", "due"}
        assert body["schedule_id"] == schedule_id and body["slot"] == slot_key(schedule_id, MON_0330Z)
        assert body["slot"] == f"{schedule_id}:{body['due']}"  # `due` is the instant inside the slot key
    for schedule_id in ("sched_a", "sched_b"):  # the slot is completed as before: it is not offered again
        record = sched.schedules.get(schedule_id)
        assert (record.next_due, record.last_slot) == (MON_0330Z + WEEK, slot_key(schedule_id, MON_0330Z))
        assert (record.failures, record.last_error, record.backoff_until) == (0, None, None)
    assert sched.schedules.get("sched_later").next_due == MON_0330Z + 10 * WEEK


def test_FR_AGT_14e_a_second_tick_for_the_same_slot_enqueues_nothing(sched: SchedApi) -> None:
    due_schedules(sched, "sched_a")
    assert sched.tick().json() == {"fired": 1}
    assert sched.tick().json() == {"fired": 0}
    sched.clock.advance(timedelta(minutes=3))
    assert sched.tick().json() == {"fired": 0}
    assert len(sched.tasks.calls) == 1


def test_FR_AGT_14e_the_task_carries_no_secret_and_none_of_the_owners_data(sched: SchedApi) -> None:
    task = sched.approved_task()
    record = sched.insert(task, "sched_a")
    assert sched.tick().json() == {"fired": 1}
    (enqueued,) = sched.tasks.calls
    text = json.dumps(enqueued) + json.dumps(task_payload(enqueued))  # the body is base64 on the wire: read it too

    def strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if len(value) >= 4 else []
        if isinstance(value, dict):
            return [s for v in value.values() for s in strings(v)]
        if isinstance(value, list):
            return [s for v in value for s in strings(v)]
        return []

    assert record.brief and record.approach
    for text_of_owner in (*strings(record.brief), *strings(record.approach), FLOW_USER, TITLE):
        assert text_of_owner not in text, text_of_owner
    for secret in (sched.good_token, sched.tasks_token, "Bearer", "budget_cap", "owner_user_id", "brief", "approach"):
        assert secret not in text, secret
    assert set(task_payload(enqueued)) == {"schedule_id", "slot", "due"}


def test_FR_AGT_14e_missed_slots_collapse_into_one_task_for_the_latest_slot(sched: SchedApi) -> None:
    due_schedules(sched, "sched_a")
    before = snapshot(sched)
    latest = MON_0330Z + 3 * WEEK
    sched.clock.set(latest + timedelta(days=2))
    assert sched.tick().json() == {"fired": 1}
    (task,) = sched.tasks.calls
    assert task["name"] == name_of("sched_a", latest)
    assert task_payload(task) == {
        "schedule_id": "sched_a", "slot": slot_key("sched_a", latest), "due": latest.isoformat(),
    }  # fmt: skip
    assert sched.schedules.get("sched_a").next_due == latest + WEEK
    after = snapshot(sched)  # the slot's world does not exist yet: nothing (not even an alert) was written to it
    assert (after["worlds"], after["events"]) == (before["worlds"], before["events"])


# --- the Scheduler path never runs anything --------------------------------------------------------


def test_FR_AGT_14e_the_scheduler_path_never_calls_the_starter_or_starts_a_run(
    sched: SchedApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import runs, schedules

    starts: list[Any] = []
    run_starts: list[Any] = []
    monkeypatch.setattr(schedules.ScheduleStarter, "start", lambda self, run: starts.append(run) or "w_never")
    monkeypatch.setattr(runs, "start_run", lambda *args, **kwargs: run_starts.append(args))
    due_schedules(sched, "sched_a", "sched_b")
    before = snapshot(sched)
    assert sched.tick().json() == {"fired": 2}
    assert len(sched.tasks.calls) == 2
    assert (starts, run_starts) == ([], [])
    after = snapshot(sched)
    assert after == before, "the tick made a world, wrote an event or started a run"


def test_FR_AGT_14e_the_tick_enqueues_even_when_the_run_seams_are_unwired(sched: SchedApi) -> None:
    """Nothing runs in the tick, so what the run needs (seams, plan, artifact store) is not the tick's business."""
    from tilo_api import schedules

    sched.app.dependency_overrides[schedules.get_seams_factory] = lambda: lambda: None
    due_schedules(sched, "sched_a")
    assert sched.tick().json() == {"fired": 1}
    assert [t["name"] for t in sched.tasks.calls] == [name_of("sched_a")]


# --- enqueue failures ------------------------------------------------------------------------------


def test_FR_AGT_14e_an_enqueue_failure_releases_the_claim_and_counts_a_failure_with_backoff(
    sched: SchedApi, caplog: pytest.LogCaptureFixture
) -> None:
    due_schedules(sched, "sched_a")
    sched.tasks.error = RuntimeError("cloudtasks says: token s3cret-value for alice@example.com is expired")
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    for leaked in ("s3cret", "alice", "cloudtasks says", "Traceback"):
        assert leaked not in response.text
    record = sched.schedules.get("sched_a")
    assert (record.failures, record.next_due, record.last_slot) == (1, MON_0330Z, None)
    assert record.last_error is not None and re.match(CODE, record.last_error) and "s3cret" not in record.last_error
    assert record.backoff_until is not None and record.backoff_until > MON_0330Z
    assert len(sched.tasks.calls) == 1

    sched.clock.set(MON_0330Z + timedelta(seconds=10))
    assert sched.tick().json() == {"fired": 0}  # backed off: no new attempt
    assert len(sched.tasks.calls) == 1

    sched.tasks.error = None  # Cloud Tasks recovers
    sched.clock.set(record.backoff_until)
    assert sched.tick().json() == {"fired": 1}  # the claim was released, so the SAME slot is handed over now
    assert sched.tasks.calls[-1]["name"] == name_of("sched_a")
    assert sched.schedules.get("sched_a").next_due == MON_0330Z + WEEK
    assert len(sched.tasks.created) == 1


def test_FR_AGT_14e_one_failing_enqueue_does_not_stop_the_others(sched: SchedApi) -> None:
    due_schedules(sched, "sched_a", "sched_b", "sched_c")
    sched.tasks.fail_when = lambda task: RuntimeError("down") if task["name"] == name_of("sched_b") else None
    assert sched.tick().json() == {"fired": 2}
    assert sched.schedules.get("sched_a").next_due == MON_0330Z + WEEK
    assert sched.schedules.get("sched_c").next_due == MON_0330Z + WEEK
    failed = sched.schedules.get("sched_b")
    assert (failed.next_due, failed.failures) == (MON_0330Z, 1)


def test_FR_AGT_14e_already_exists_counts_as_success(sched: SchedApi) -> None:
    """Cloud Tasks answers ALREADY_EXISTS for a name used within its reuse window (a retried tick whose first attempt
    did enqueue): the slot was handed over, so it completes and nothing is counted against the schedule."""
    due_schedules(sched, "sched_a")
    sched.tasks.created[name_of("sched_a")] = {"name": name_of("sched_a")}
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 1})
    record = sched.schedules.get("sched_a")
    assert (record.next_due, record.failures, record.last_error, record.backoff_until) == (
        MON_0330Z + WEEK,
        0,
        None,
        None,
    )
    assert record.last_slot == slot_key("sched_a", MON_0330Z)
    assert len(sched.tasks.calls) == 1 and len(sched.tasks.created) == 1  # still one task, not two


def test_FR_AGT_14e_a_slot_someone_else_holds_is_not_enqueued(sched: SchedApi) -> None:
    due_schedules(sched, "sched_a")
    assert sched.schedules.claim("sched_a", MON_0330Z) is True  # another tick's live claim
    assert sched.tick().json() == {"fired": 0}
    assert sched.tasks.calls == []


# --- unconfigured, replay-only, the rate limit -----------------------------------------------------


@pytest.mark.parametrize("unset", [(ENV_QUEUE,), (ENV_TASKS_CALLER,), (ENV_QUEUE, ENV_TASKS_CALLER)])
@pytest.mark.parametrize("blank", [False, True], ids=["unset", "empty"])
def test_FR_AGT_14e_without_a_queue_or_a_tasks_caller_the_scheduler_gets_503_before_anything_is_claimed(
    sched: SchedApi, monkeypatch: pytest.MonkeyPatch, unset: tuple[str, ...], blank: bool
) -> None:
    due_schedules(sched, "sched_a", "sched_b")
    before = snapshot(sched)
    for name in unset:
        if blank:
            monkeypatch.setenv(name, "")
        else:
            monkeypatch.delenv(name)
    response = sched.tick()
    assert response.status_code == 503, response.text
    assert "Traceback" not in response.text and TASKS_SA not in response.text and QUEUE not in response.text
    assert sched.tasks.calls == []
    assert snapshot(sched) == before  # nothing runs inline any more, so there is no fallback
    for schedule_id in ("sched_a", "sched_b"):  # nothing was claimed: the slot is claimable the moment it is configured
        record = sched.schedules.get(schedule_id)
        assert (record.next_due, record.failures, record.last_error) == (MON_0330Z, 0, None)
        assert sched.schedules.claim(schedule_id, MON_0330Z) is True
        sched.schedules.release(schedule_id, MON_0330Z)
    monkeypatch.setenv(ENV_QUEUE, QUEUE)
    monkeypatch.setenv(ENV_TASKS_CALLER, TASKS_SA)
    assert sched.tick().json() == {"fired": 2}


def test_FR_AGT_14e_replay_only_enqueues_nothing_and_moves_nothing(sched: SchedApi) -> None:
    due_schedules(sched, "sched_a")
    sched.flags.set("replay_only", True, reason="NFR-24 test")
    for _ in range(3):
        response = sched.tick()
        assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert sched.tasks.calls == []
    record = sched.schedules.get("sched_a")
    assert (record.next_due, record.failures, record.last_slot) == (MON_0330Z, 0, None)
    sched.flags.set("replay_only", False, reason="cleared")
    assert sched.tick().json() == {"fired": 1}  # the slot fires once the flag clears


def test_FR_AGT_14e_one_tick_enqueues_at_most_twenty_slots(sched: SchedApi) -> None:
    ids = [f"sched_r{n:02d}" for n in range(25)]
    due_schedules(sched, *ids)
    assert MAX_FIRES_PER_TICK == 20
    assert sched.tick().json() == {"fired": 20}
    assert len(sched.tasks.calls) == 20
    assert sched.tick().json() == {"fired": 5}  # the rest stay due and go on the next tick
    assert len({c["name"] for c in sched.tasks.calls}) == 25  # one task per slot, never two


# --- what the route builds, and when ---------------------------------------------------------------


class Counting:
    def __init__(self, value: Any) -> None:
        self.value, self.calls = value, 0

    def __call__(self) -> Any:
        self.calls += 1
        return self.value


def test_FR_AGT_14e_the_tasks_client_is_built_only_after_the_token_passed_once_per_request(sched: SchedApi) -> None:
    from tilo_api import schedules

    counting = Counting(sched.tasks)
    sched.app.dependency_overrides[schedules.get_tasks_client_factory] = lambda: counting
    due_schedules(sched, "sched_a")
    for headers in ({}, bearer("tok-forged"), bearer(sched.verifier.register(TASKS_SA + "x"))):
        assert sched.tick(headers=headers).status_code in (401, 403)
    assert counting.calls == 0  # an anonymous or wrong call costs no client (and no credential lookup)
    assert sched.tick().json() == {"fired": 1}
    assert counting.calls == 1


def test_FR_AGT_14e_a_tasks_client_that_cannot_be_built_fails_closed_with_a_fixed_body(sched: SchedApi) -> None:
    from tilo_api import schedules

    def broken() -> Any:
        raise RuntimeError("no credentials for alice@example.com: password hunter2")

    sched.app.dependency_overrides[schedules.get_tasks_client_factory] = lambda: broken
    due_schedules(sched, "sched_a")
    response = sched.tick()
    assert 500 <= response.status_code < 600
    for leaked in ("hunter2", "alice", "no credentials", "Traceback"):
        assert leaked not in response.text
    assert sched.schedules.get("sched_a").next_due == MON_0330Z  # claimed or not, the slot is still due


# --- the enqueuer on its own -----------------------------------------------------------------------


def _enqueuer(sched: SchedApi, **over: Any) -> Any:
    from tilo_api import schedules

    kwargs = {"client": sched.tasks, "queue": QUEUE, "audience": AUDIENCE, "caller": TASKS_SA}
    return schedules.TaskEnqueuer(**{**kwargs, **over})


def test_FR_AGT_14e_the_enqueuer_is_a_run_starter_that_hands_over_one_task(sched: SchedApi) -> None:
    from _fr_agt_14e_lib import run_start

    due_schedules(sched, "sched_a")
    world = _enqueuer(sched).start(run_start(sched, "sched_a"))
    assert isinstance(world, str) and world
    assert [t["name"] for t in sched.tasks.calls] == [name_of("sched_a")]
    assert world not in sched.store.worlds  # it makes no world: the task's own request does


def test_FR_AGT_14e_the_enqueuer_raises_when_the_client_fails_and_not_on_already_exists(sched: SchedApi) -> None:
    from _fr_agt_14e_lib import run_start

    due_schedules(sched, "sched_a")
    start = run_start(sched, "sched_a")
    _enqueuer(sched).start(start)
    _enqueuer(sched).start(start)  # the same name again: ALREADY_EXISTS, a success
    assert len(sched.tasks.created) == 1
    sched.tasks.error = RuntimeError("down")
    with pytest.raises(Exception):  # noqa: B017 - the type is the client's own
        _enqueuer(sched).start(run_start(sched, "sched_a", slot=MON_0330Z + WEEK))
