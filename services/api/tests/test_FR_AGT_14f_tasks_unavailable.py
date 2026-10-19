"""FR-AGT-14f (issue #502, 7 Oct delta-review follow-up; PRD 6.3, 8.6, NFR-23, NFR-26): a service-wide Cloud Tasks
refusal is loud and cheap. API_FR_AGT_14f.md; BQ-AGT14-6.

Today a 401/403/404 from Cloud Tasks (a revoked actAs or enqueuer role, a deleted queue) is an uncounted
`StartSkipped("tasks_unavailable", count=False)`: logged once per tick as a WARNING, and the tick answers
200 `{"fired": 0}`, so every scheduled run silently stops while each tick still tries every due slot (up to
`MAX_FIRES_PER_TICK` calls that cannot succeed). Pinned here, through the Scheduler's call of the tick route:

1. The FIRST service-wide refusal stops the tick: no further enqueue call that tick. The refused slot and every slot
   after it stay due (no failure, no backoff, no `next_due` move, claim released), so they fire once Tasks works.
2. A tick whose outcome includes `tasks_unavailable` answers 503 with the fixed body `{"detail": "tasks_unavailable"}`
   (Cloud Scheduler records a failed attempt; NFR-23 alerts on the error rate). BQ-AGT14-6 (a): this holds even when a
   slot was handed over before the refusal, because the queue is broken; the slots handed over stay completed.
3. The refusal is logged ONCE per tick at ERROR on a `tilo_api.*` logger, naming the code and the status, with no token,
   no task name, no queue, no schedule or owner id, no exception text and no traceback (NFR-26, SEC-01).
4. Nothing else changes: per-schedule failures are counted and do not stop the tick (200), ALREADY_EXISTS is a success,
   replay-only is 200 `{"fired": 0}`, and a tick with nothing due answers 200 `{"fired": 0}` whatever Tasks would say.
5. No network, no paid call: `FakeTasksClient` (from `_fr_agt_14_lib.py`) and a recording session of the
   `requests.Session` shape for the real `CloudTasksRestClient` (the same shape as 14e's `FakeSession`).

Conflict (reported, not edited): `test_FR_AGT_14e_fanout.py::test_FR_AGT_14e_a_service_wide_tasks_failure_counts_
against_no_schedule` asserts `tick().json() == {"fired": 0}` for a refused tick; under item 2 that body is
`{"detail": "tasks_unavailable"}` with status 503.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

import pytest
from _fr_agt_14_lib import (
    AUDIENCE,
    MON_0330Z,
    QUEUE,
    TASKS_SA,
    WEEK,
    FakeTasksClient,
    SchedApi,
)
from _fr_agt_14e_lib import block_network
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_harness.schedule import MAX_FIRES_PER_TICK, slot_key, task_name
from tilo_harness.schedule_store import InMemoryScheduleStore

UNAVAILABLE = 503
UNAVAILABLE_BODY = {"detail": "tasks_unavailable"}  # BQ-AGT14-6 (b): fixed, the same for 401, 403 and 404
CODE = "tasks_unavailable"
SECRET = "tok-" + "s3cret" + "-value"  # assembled at runtime: never a literal secret in the repo


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    return block_network(monkeypatch)


@pytest.fixture
def sched(clear_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(clear_flow, monkeypatch)
    rig.clock.set(MON_0330Z)
    return rig


# --- helpers -----------------------------------------------------------------------------------------------------


def ids(n: int) -> list[str]:
    """Zero-padded, so the store's oldest-first, ties-by-id order (BQ-AGT14-2 i) is the order of this list."""
    return [f"sched_{i:02d}" for i in range(n)]


def due_schedules(rig: SchedApi, schedule_ids: list[str]) -> None:
    task = rig.approved_task()
    for schedule_id in schedule_ids:
        rig.insert(task, schedule_id)


def name_of(schedule_id: str) -> str:
    return f"{QUEUE}/tasks/{task_name(slot_key(schedule_id, MON_0330Z))}"


def unavailable(status: int = 403, extra: str = "") -> Exception:
    from tilo_api import schedules

    return schedules.TasksUnavailable(f"cloud tasks answered {status}{extra}")


def assert_still_due(rig: SchedApi, schedule_id: str) -> None:
    """Refused or never tried: nothing recorded, nothing moved, the schedule on."""
    record = rig.schedules.get(schedule_id)
    got = (record.enabled, record.failures, record.next_due, record.last_error, record.backoff_until, record.last_slot)
    assert got == (True, 0, MON_0330Z, None, None, None), schedule_id


def assert_handed_over(rig: SchedApi, schedule_id: str) -> None:
    record = rig.schedules.get(schedule_id)
    assert (record.next_due, record.last_slot, record.failures) == (
        MON_0330Z + WEEK,
        slot_key(schedule_id, MON_0330Z),
        0,
    ), schedule_id


class RecordingSession:
    """The `requests.Session` shape `CloudTasksRestClient` takes (as 14e's `FakeSession`): answers `status` to every
    POST, records each, and carries a would-be secret in its text and JSON so a leak shows."""

    def __init__(self, status: int) -> None:
        self.status, self.posts = status, []

    def post(self, url: str, *, json: Any = None, timeout: Any = None, max_allowed_time: Any = None) -> Any:
        from types import SimpleNamespace

        self.posts.append(url)

        def body() -> Any:
            return {"error": {"code": self.status, "status": "PERMISSION_DENIED", "message": f"token {SECRET}"}}

        return SimpleNamespace(status_code=self.status, text=f"provider says: token {SECRET} is bad", json=body)


def use_rest_client(rig: SchedApi, session: RecordingSession) -> None:
    from tilo_api import schedules

    rig.app.dependency_overrides[schedules.get_tasks_client_factory] = lambda: (
        lambda: schedules.CloudTasksRestClient(session=session)
    )


def unavailable_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """ERROR records on a `tilo_api.*` logger that report the service-wide refusal."""
    return [
        r
        for r in caplog.records
        if r.levelno >= logging.ERROR and r.name.startswith("tilo_api.") and CODE in r.getMessage()
    ]


# --- 1. the first service-wide refusal stops the tick --------------------------------------------------------------


def test_FR_AGT_14f_the_first_tasks_unavailable_stops_the_tick(sched: SchedApi) -> None:
    due_schedules(sched, ids(5))
    sched.tasks.error = unavailable(403)
    sched.tick()
    assert len(sched.tasks.calls) == 1, "the tick kept enqueueing after a service-wide refusal"
    assert sched.tasks.calls[0]["name"] == name_of("sched_00")  # the oldest due slot is the one tried
    for schedule_id in ids(5):
        assert_still_due(sched, schedule_id)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_FR_AGT_14f_a_real_client_refusal_costs_one_call_per_tick(sched: SchedApi, status: int) -> None:
    """Through the real REST client: a 401 (wrong caller), 403 (revoked actAs or enqueuer role) or 404 (deleted queue)
    is ONE call per tick, not one per due slot."""
    due_schedules(sched, ids(4))
    session = RecordingSession(status)
    use_rest_client(sched, session)
    for minute in range(3):
        sched.clock.set(MON_0330Z + timedelta(minutes=minute))
        sched.tick()
    assert len(session.posts) == 3, f"{len(session.posts)} calls for 3 refused ticks"
    for schedule_id in ids(4):
        assert_still_due(sched, schedule_id)


def test_FR_AGT_14f_a_full_tick_of_due_slots_costs_one_refused_call_and_all_fire_on_recovery(sched: SchedApi) -> None:
    """The issue's case: MAX_FIRES_PER_TICK (20) due slots used to cost 20 calls a minute that cannot succeed."""
    schedule_ids = ids(MAX_FIRES_PER_TICK)
    due_schedules(sched, schedule_ids)
    sched.tasks.error = unavailable(403)
    for minute in range(10):
        sched.clock.set(MON_0330Z + timedelta(minutes=minute))
        sched.tick()
    assert len(sched.tasks.calls) == 10  # one per tick
    for schedule_id in schedule_ids:
        assert_still_due(sched, schedule_id)

    sched.tasks.error = None  # the user restores the role or the queue
    sched.clock.set(MON_0330Z + timedelta(minutes=10))  # inside a 5-minute claim lease of the last refused tick
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": MAX_FIRES_PER_TICK})
    assert sorted(sched.tasks.created) == sorted(name_of(s) for s in schedule_ids)
    for schedule_id in schedule_ids:
        assert_handed_over(sched, schedule_id)


def test_FR_AGT_14f_a_refusal_mid_tick_keeps_what_was_handed_over_and_leaves_the_rest_due(sched: SchedApi) -> None:
    due_schedules(sched, ids(4))
    refused = name_of("sched_01")
    sched.tasks.fail_when = lambda task: unavailable(404) if task["name"] == refused else None
    response = sched.tick()
    assert [t["name"] for t in sched.tasks.calls] == [name_of("sched_00"), refused]  # nothing after the refusal
    assert_handed_over(sched, "sched_00")
    for schedule_id in ("sched_01", "sched_02", "sched_03"):
        assert_still_due(sched, schedule_id)
    assert response.status_code == UNAVAILABLE  # BQ-AGT14-6 (a): the queue is broken, whatever fired before

    sched.tasks.fail_when = None
    sched.clock.set(MON_0330Z + timedelta(minutes=1))  # Cloud Scheduler's retry of the failed attempt, or the next tick
    again = sched.tick()
    assert (again.status_code, again.json()) == (200, {"fired": 3})
    assert [t["name"] for t in sched.tasks.calls[2:]] == [name_of(s) for s in ("sched_01", "sched_02", "sched_03")]
    assert len(sched.tasks.created) == 4  # sched_00 was not handed over twice


# --- 2. a refused tick answers 503 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404])
def test_FR_AGT_14f_a_tick_that_fired_nothing_answers_503_with_a_fixed_body(sched: SchedApi, status: int) -> None:
    due_schedules(sched, ids(2))
    session = RecordingSession(status)
    use_rest_client(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (UNAVAILABLE, UNAVAILABLE_BODY)
    for leaked in (SECRET, "provider says", "PERMISSION_DENIED", QUEUE, TASKS_SA, AUDIENCE, "sched-", "Traceback"):
        assert leaked not in response.text


def test_FR_AGT_14f_the_503_body_carries_no_exception_text(sched: SchedApi) -> None:
    due_schedules(sched, ids(1))
    sched.tasks.error = unavailable(403, f"; token {SECRET} for alice@example.com")
    response = sched.tick()
    assert (response.status_code, response.json()) == (UNAVAILABLE, UNAVAILABLE_BODY)
    for leaked in (SECRET, "alice", "cloud tasks answered"):
        assert leaked not in response.text


def test_FR_AGT_14f_a_tick_that_fired_before_the_refusal_still_answers_503(sched: SchedApi) -> None:
    """BQ-AGT14-6 (a), the PRD's silence resolved to the issue's default: any `tasks_unavailable` in a tick is 503, so
    Cloud Scheduler records the attempt as failed. The slot handed over (here by ALREADY_EXISTS, a success) stays
    completed and is not offered again."""
    due_schedules(sched, ids(3))
    sched.tasks.created[name_of("sched_00")] = {"name": name_of("sched_00")}  # ALREADY_EXISTS: a success
    sched.tasks.fail_when = lambda task: unavailable(403) if task["name"] == name_of("sched_01") else None
    response = sched.tick()
    assert (response.status_code, response.json()) == (UNAVAILABLE, UNAVAILABLE_BODY)
    assert_handed_over(sched, "sched_00")
    assert_still_due(sched, "sched_01")
    assert_still_due(sched, "sched_02")
    assert len(sched.tasks.calls) == 2


def test_FR_AGT_14f_every_refused_tick_answers_503_until_tasks_works_again(sched: SchedApi) -> None:
    due_schedules(sched, ids(2))
    sched.tasks.error = unavailable(403)
    for minute in range(9):  # past MAX_FAILURES = 8: nothing is disabled, and every attempt is a visible failure
        sched.clock.set(MON_0330Z + timedelta(minutes=minute))
        response = sched.tick()
        assert (response.status_code, response.json()) == (UNAVAILABLE, UNAVAILABLE_BODY), minute
    sched.tasks.error = None
    sched.clock.set(MON_0330Z + timedelta(minutes=9))
    recovered = sched.tick()
    assert (recovered.status_code, recovered.json()) == (200, {"fired": 2})  # the same slots, at once
    assert len(sched.tasks.created) == 2


# --- 3. logged once per tick at ERROR, with nothing secret ---------------------------------------------------------


def test_FR_AGT_14f_the_refusal_is_logged_once_per_tick_at_error_on_a_tilo_api_logger(
    sched: SchedApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(5))
    session = RecordingSession(403)
    use_rest_client(sched, session)
    sched.tick()
    errors = unavailable_errors(caplog)
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert "403" in errors[0].getMessage()  # the status code, so the owner of the setting knows which one
    sched.clock.set(MON_0330Z + timedelta(minutes=1))
    sched.tick()
    assert len(unavailable_errors(caplog)) == 2  # once per tick, not once per process


def test_FR_AGT_14f_the_error_log_has_the_code_status_and_counts_only(
    sched: SchedApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    schedule_ids = ids(3)
    due_schedules(sched, schedule_ids)
    owner = sched.schedules.get("sched_00").owner_user_id
    session = RecordingSession(404)
    use_rest_client(sched, session)
    sched.tick()
    errors = unavailable_errors(caplog)
    assert len(errors) == 1, "no single ERROR line for the refusal on a tilo_api.* logger"
    record = errors[0]
    assert record.exc_info is None and record.exc_text is None  # the exception's type at most, never a traceback
    for arg in record.args if isinstance(record.args, tuple) else ():
        assert isinstance(arg, int) or re.fullmatch(r"[a-z0-9_]{1,64}", str(arg)), arg  # codes and counts only
    message = record.getMessage()
    leaks = [SECRET, "provider says", "PERMISSION_DENIED", QUEUE, TASKS_SA, AUDIENCE, "sched-", owner, *schedule_ids]
    for leaked in leaks:
        assert leaked not in message, leaked
    for leaked in (SECRET, "provider says", "Traceback"):  # nor in any other line of the tick
        assert leaked not in caplog.text, leaked


def test_FR_AGT_14f_no_exception_text_reaches_any_log(sched: SchedApi, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(2))
    sched.tasks.error = unavailable(403, f"; token {SECRET} for alice@example.com")
    sched.tick()
    assert len(unavailable_errors(caplog)) == 1
    for leaked in (SECRET, "alice@example.com", "Traceback"):
        assert leaked not in caplog.text, leaked


# --- 4. nothing else changes ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_FR_AGT_14f_a_per_schedule_tasks_error_is_counted_and_does_not_stop_the_tick(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(3))
    session = RecordingSession(status)
    use_rest_client(sched, session)
    response = sched.tick()
    if status != 400:  # changed deliberately: BQ-AGT14-8: the first two calls answering the same 429/5xx are the
        # service's (FR-AGT-14h): two calls, nothing counted, 503. Per-schedule counting of a 429/5xx after a success is
        # pinned in 14g and 14h.
        detail = "tasks_quota" if status == 429 else "tasks_server"
        assert (response.status_code, response.json()) == (503, {"detail": detail})
        assert len(session.posts) == 2
        assert [sched.schedules.get(s).failures for s in ids(3)] == [0, 0, 0]
        assert unavailable_errors(caplog) == []
        return
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert len(session.posts) == 3  # every due slot tried
    for schedule_id in ids(3):
        record = sched.schedules.get(schedule_id)
        assert (record.failures, record.next_due) == (1, MON_0330Z), schedule_id
    assert unavailable_errors(caplog) == []


def test_FR_AGT_14f_a_failing_enqueue_amid_successes_keeps_its_200(sched: SchedApi) -> None:
    due_schedules(sched, ids(3))
    sched.tasks.created[name_of("sched_02")] = {"name": name_of("sched_02")}  # ALREADY_EXISTS: a success
    sched.tasks.fail_when = lambda task: RuntimeError("down") if task["name"] == name_of("sched_01") else None
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 2})
    assert_handed_over(sched, "sched_00")
    assert_handed_over(sched, "sched_02")
    failed = sched.schedules.get("sched_01")
    assert (failed.failures, failed.next_due) == (1, MON_0330Z)


def test_FR_AGT_14f_replay_only_still_answers_200_and_calls_nothing(sched: SchedApi) -> None:
    due_schedules(sched, ids(2))
    sched.tasks.error = unavailable(403)
    sched.flags.set("replay_only", True, reason="NFR-24 test")
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert sched.tasks.calls == []


def test_FR_AGT_14f_a_tick_with_nothing_due_answers_200_whatever_tasks_would_say(sched: SchedApi) -> None:
    """A 503 comes only from a refusal the tick actually met: with nothing due no call is made."""
    sched.insert(sched.approved_task(), "sched_later", next_due=MON_0330Z + 3 * WEEK)
    sched.tasks.error = unavailable(403)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert sched.tasks.calls == []


# --- property: the outcome of any mix of per-slot answers ------------------------------------------------------------

OUTCOMES = st.sampled_from(["ok", "exists", "fail", "unavailable"])


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(outcomes=st.lists(OUTCOMES, min_size=1, max_size=MAX_FIRES_PER_TICK + 3))
def test_FR_AGT_14f_property_no_call_after_the_first_refusal_and_503_iff_one_was_met(
    sched: SchedApi, outcomes: list[str]
) -> None:
    """For any due slots answering ok / ALREADY_EXISTS / a per-schedule failure / a service-wide refusal, in the
    store's order: calls stop right after the first refusal (or at MAX_FIRES_PER_TICK); slots before it keep their
    current behaviour; it and every later slot stay due; the answer is 503 iff a refusal was met, else 200 fired."""
    task = getattr(sched, "_14f_task", None) or sched.approved_task()
    sched._14f_task = task  # type: ignore[attr-defined]  # one approved task for every example
    sched.schedules = InMemoryScheduleStore(clock=sched.clock)  # the rig's override reads these at call time
    sched.tasks = FakeTasksClient()
    sched.clock.set(MON_0330Z)
    schedule_ids = ids(len(outcomes))
    for schedule_id in schedule_ids:
        sched.insert(task, schedule_id)
    by_name = {name_of(s): o for s, o in zip(schedule_ids, outcomes, strict=True)}
    for name, outcome in by_name.items():
        if outcome == "exists":
            sched.tasks.created[name] = {"name": name}

    def fail_when(t: dict[str, Any]) -> Exception | None:
        outcome = by_name[t["name"]]
        return unavailable(403) if outcome == "unavailable" else RuntimeError("down") if outcome == "fail" else None

    sched.tasks.fail_when = fail_when
    response = sched.tick()

    tried = outcomes[:MAX_FIRES_PER_TICK]
    stop = tried.index("unavailable") + 1 if "unavailable" in tried else len(tried)
    assert [t["name"] for t in sched.tasks.calls] == [name_of(s) for s in schedule_ids[:stop]]
    fired = sum(o in ("ok", "exists") for o in tried[:stop])
    for schedule_id, outcome in zip(schedule_ids[:stop], tried[:stop], strict=True):
        if outcome in ("ok", "exists"):
            assert_handed_over(sched, schedule_id)
        elif outcome == "fail":
            assert sched.schedules.get(schedule_id).failures == 1, schedule_id
    for schedule_id, outcome in zip(schedule_ids, outcomes, strict=True):
        if schedule_id not in schedule_ids[:stop] or outcome == "unavailable":
            assert_still_due(sched, schedule_id)
    if "unavailable" in tried:
        assert (response.status_code, response.json()) == (UNAVAILABLE, UNAVAILABLE_BODY)
    else:
        assert (response.status_code, response.json()) == (200, {"fired": fired})
