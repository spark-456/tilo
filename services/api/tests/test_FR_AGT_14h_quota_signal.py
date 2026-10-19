"""FR-AGT-14h (issue #502; PRD 6.3, 8.6, NFR-23 alerts on quota errors, NFR-26 structured logs): Cloud Tasks quota and
server errors become a signal. API_FR_AGT_14h.md; BQ-AGT14-8.

Today (14g) a 429 RESOURCE_EXHAUSTED or a 5xx from Cloud Tasks is counted against each schedule, and the per-schedule
WARNING names only the type `TasksError`, so neither a log-based quota alert nor a person can see the status. A quota or
server outage that every due slot meets is counted against every schedule and disables them all after MAX_FAILURES.
Pinned here, through the Scheduler's call of the tick route:

1. A per-schedule enqueue failure that carries an HTTP status is logged at WARNING on `tilo_api.schedules` or
   `tilo_harness.schedule` with the int status and the recorded code as structured fields (the field names are the
   constants below, in one place: the cloud lane's NFR-23 quota alert filters on them). Ids only.
2. When the first two enqueue calls of a tick both fail with the SAME 429, or the SAME 5xx status, the outage is the
   service's: no further call, NEITHER slot is counted, both and every later slot stay due, 503
   `{"detail": "tasks_quota"}` (429) or `{"detail": "tasks_server"}` (5xx), one ERROR line (BQ-AGT14-8).
3. Anything else keeps today's behaviour: a lone due slot, a success or ALREADY_EXISTS first, mixed statuses, 400 and
   409 ABORTED, an unclassified exception: counted per schedule, 200.
4. Fakes only: a `requests.Session`-shaped Cloud Tasks session for the real `CloudTasksRestClient`. No network.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from _fr_agt_14_lib import AUDIENCE, MON_0330Z, QUEUE, TASKS_SA, WEEK, SchedApi
from _fr_agt_14e_lib import block_network
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_harness.schedule import MAX_FIRES_PER_TICK, slot_key, task_name
from tilo_harness.schedule_store import MAX_BACKOFF, MAX_FAILURES, InMemoryScheduleStore

# --- the structured log fields (BQ-AGT14-8 a). ONE place: the NFR-23 quota alert filters on these; rename here only. --
LOG_FIELD_EVENT = "event"
LOG_FIELD_STATUS = "status"
LOG_FIELD_CODE = "code"
ENQUEUE_FAILED = "schedule_enqueue_failed"  # the value of LOG_FIELD_EVENT on a per-schedule enqueue failure
LOGGERS = frozenset({"tilo_api.schedules", "tilo_harness.schedule"})  # where the per-schedule WARNING may come from
# ----------------------------------------------------------------------------------------------------------------------

UNAVAILABLE = 503
QUOTA = "tasks_quota"  # BQ-AGT14-8 (b): the first two calls of a tick both answered the same 429
SERVER = "tasks_server"  # BQ-AGT14-8 (b): the first two calls of a tick both answered the same 5xx
TRANSIENT = (429, 500, 502, 503, 504)
SECRET = "tok-" + "s3cret" + "-value"  # assembled at runtime: never a literal secret in the repo
EMAIL = "alice" + "@" + "example.com"
TASKS_HOST = "cloudtasks.googleapis.com"
LEAKS = (SECRET, EMAIL, TASKS_HOST, QUEUE, TASKS_SA, AUDIENCE, "sched-", "provider says", "Traceback")
_RPC = {
    400: "INVALID_ARGUMENT",
    409: "ABORTED",
    429: "RESOURCE_EXHAUSTED",
    500: "INTERNAL",
    502: "UNAVAILABLE",
    503: "UNAVAILABLE",
    504: "DEADLINE_EXCEEDED",
}
_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def code_for(status: int) -> str:
    return QUOTA if status == 429 else SERVER


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


def name_of(schedule_id: str, due: Any = MON_0330Z) -> str:
    return f"{QUEUE}/tasks/{task_name(slot_key(schedule_id, due))}"


def assert_still_due(rig: SchedApi, schedule_id: str) -> None:
    """Stopped or never tried: nothing recorded, nothing moved, the schedule on."""
    record = rig.schedules.get(schedule_id)
    got = (record.enabled, record.failures, record.next_due, record.last_error, record.backoff_until, record.last_slot)
    assert got == (True, 0, MON_0330Z, None, None, None), (schedule_id, got)


def assert_counted(rig: SchedApi, schedule_id: str) -> None:
    """Today's per-schedule failure: one failure, a backoff, a code, the slot unmoved."""
    record = rig.schedules.get(schedule_id)
    assert (record.failures, record.next_due, record.enabled) == (1, MON_0330Z, True), schedule_id
    assert record.backoff_until is not None and record.last_error is not None, schedule_id


def assert_handed_over(rig: SchedApi, schedule_id: str, due: Any = MON_0330Z) -> None:
    record = rig.schedules.get(schedule_id)
    got = (record.next_due, record.last_slot, record.failures)
    assert got == (due + WEEK, slot_key(schedule_id, due), 0), (schedule_id, got)


class TasksSession:
    """Cloud Tasks' create-task endpoint in the `requests.Session` shape, with no network. `answer(name)` returns an
    HTTP error status to answer (nothing created), "boom" to raise an unclassified exception, or None: a new name is
    created (200), a name already created answers 409 ALREADY_EXISTS. Error answers carry a would-be secret."""

    def __init__(self, answer: Callable[[str], int | str | None] = lambda _name: None) -> None:
        self.answer = answer
        self.posts: list[str] = []
        self.creations: Counter[str] = Counter()

    def post(self, url: str, *, json: Any = None, timeout: Any = None, max_allowed_time: Any = None) -> Any:
        name = json["task"]["name"]
        self.posts.append(name)
        outcome = self.answer(name)
        if outcome == "boom":
            raise RuntimeError(f"down: token {SECRET} for {EMAIL}")
        if isinstance(outcome, int):
            return _answer(outcome, _RPC.get(outcome, "UNKNOWN"))
        if self.creations[name]:
            return _answer(409, "ALREADY_EXISTS")
        self.creations[name] += 1
        return _answer(200, None)


def _answer(status: int, rpc_status: str | None) -> Any:
    def body() -> Any:
        if rpc_status is None:
            return {"name": "created"}
        return {"error": {"code": status, "status": rpc_status, "message": f"token {SECRET} for {EMAIL}"}}

    return SimpleNamespace(status_code=status, text=f"provider says: token {SECRET} ({status})", json=body)


def by_slot(answers: Mapping[str, int | str | None]) -> Callable[[str], int | str | None]:
    """An `answer` function from {schedule_id: outcome}; unnamed slots succeed."""
    names = {name_of(s): o for s, o in answers.items()}
    return lambda name: names.get(name)


def use_session(rig: SchedApi, session: TasksSession) -> None:
    """The real `CloudTasksRestClient` over `session`."""
    from tilo_api import schedules

    rig.app.dependency_overrides[schedules.get_tasks_client_factory] = lambda: (
        lambda: schedules.CloudTasksRestClient(session=session)
    )


def enqueue_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The structured per-schedule WARNINGs of BQ-AGT14-8 (a)."""
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name in LOGGERS and getattr(r, LOG_FIELD_EVENT, None) == ENQUEUE_FAILED
    ]


def tilo_api_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR and r.name.startswith("tilo_api.")]


def assert_ids_only(record: logging.LogRecord) -> None:
    """NFR-26 and API_FR_AGT_14h.md item 1: no task name, queue, URL, email, token, exception text or traceback, in the
    message, its arguments or any structured field."""
    assert record.exc_info is None and record.exc_text is None
    for arg in record.args if isinstance(record.args, tuple) else ():
        assert isinstance(arg, int) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", str(arg)), arg
    message = record.getMessage()
    for leaked in LEAKS:
        assert leaked not in message, leaked
    for key, value in record.__dict__.items():
        if key in _STANDARD:
            continue
        ok = value is None or isinstance(value, bool | int) or re.fullmatch(r"[A-Za-z0-9_]{1,64}", str(value))
        assert ok, (key, value)


# --- 1. the status is a structured field of the per-schedule WARNING ----------------------------------------------


@pytest.mark.parametrize("status", [400, 409, 429, 500, 502, 503, 504])
def test_FR_AGT_14h_a_per_schedule_enqueue_failure_logs_its_int_status_and_code_as_fields(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    """One due slot, so nothing pairs: counted as today, and its WARNING carries the status (an int) and the code the
    store recorded (`last_error`)."""
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(1))
    use_session(sched, TasksSession(lambda _name: status))
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert_counted(sched, "sched_00")
    warnings = enqueue_warnings(caplog)
    assert len(warnings) == 1, [(r.name, r.getMessage()) for r in caplog.records if r.levelno == logging.WARNING]
    record = warnings[0]
    got_status, got_code = getattr(record, LOG_FIELD_STATUS, None), getattr(record, LOG_FIELD_CODE, None)
    assert type(got_status) is int and got_status == status, got_status
    assert isinstance(got_code, str) and got_code == sched.schedules.get("sched_00").last_error, got_code


@pytest.mark.parametrize("status", [429, 503])
def test_FR_AGT_14h_the_structured_warning_carries_ids_only(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(1))
    use_session(sched, TasksSession(lambda _name: status))
    sched.tick()
    warnings = enqueue_warnings(caplog)
    assert len(warnings) == 1, "no structured enqueue-failure WARNING"
    assert_ids_only(warnings[0])
    for leaked in (SECRET, EMAIL, TASKS_HOST, "provider says", "Traceback"):  # nor in any other line of the tick
        assert leaked not in caplog.text, leaked


def test_FR_AGT_14h_a_one_off_429_between_successes_counts_against_that_schedule_only(
    sched: SchedApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(3))
    use_session(sched, TasksSession(by_slot({"sched_01": 429})))
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 2})
    assert_handed_over(sched, "sched_00")
    assert_counted(sched, "sched_01")
    assert_handed_over(sched, "sched_02")
    warnings = enqueue_warnings(caplog)
    assert [getattr(r, LOG_FIELD_STATUS, None) for r in warnings] == [429]


@pytest.mark.parametrize("first", ["ok", "exists"])
@pytest.mark.parametrize("status", [429, 503])
def test_FR_AGT_14h_a_first_slot_429_or_5xx_followed_by_a_success_counts_against_that_schedule_only(
    sched: SchedApi, status: int, first: str
) -> None:
    """The first call's failure cannot pair with a success: it is that schedule's, counted as today."""
    due_schedules(sched, ids(3))
    session = TasksSession(by_slot({"sched_00": status}))
    if first == "exists":
        session.creations[name_of("sched_01")] = 1  # ALREADY_EXISTS is a success
    use_session(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 2})
    assert session.posts == [name_of(s) for s in ids(3)]
    assert_counted(sched, "sched_00")
    assert_handed_over(sched, "sched_01")
    assert_handed_over(sched, "sched_02")


# --- 2. the first two calls failing alike is the service's -------------------------------------------------------


@pytest.mark.parametrize("n", [2, 4])
@pytest.mark.parametrize("status", TRANSIENT)
def test_FR_AGT_14h_the_first_two_calls_failing_with_the_same_429_or_5xx_stop_the_tick_and_count_nothing(
    sched: SchedApi, status: int, n: int
) -> None:
    due_schedules(sched, ids(n))
    session = TasksSession(lambda _name: status)
    use_session(sched, session)
    response = sched.tick()
    assert session.posts == [name_of("sched_00"), name_of("sched_01")], "calls went on after two alike failures"
    for schedule_id in ids(n):
        assert_still_due(sched, schedule_id)  # neither tried slot counted, the rest untried
    assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": code_for(status)})


@pytest.mark.parametrize("status", [429, 500, 503])
def test_FR_AGT_14h_the_503_body_is_fixed_and_carries_no_provider_text(sched: SchedApi, status: int) -> None:
    due_schedules(sched, ids(3))
    use_session(sched, TasksSession(lambda _name: status))
    response = sched.tick()
    assert response.status_code == UNAVAILABLE
    assert response.json() == {"detail": code_for(status)}
    for leaked in (*LEAKS, "TasksError", _RPC[status]):
        assert leaked not in response.text, leaked


@pytest.mark.parametrize("status", [429, 503])
def test_FR_AGT_14h_the_service_wide_stop_logs_one_error_line_with_its_status_and_code(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    """One ERROR line per stopped tick on a `tilo_api.*` logger: the code in its message, and the status and code as the
    same structured fields as the per-schedule WARNING, so the NFR-23 quota alert sees a service-wide stop too."""
    caplog.set_level(logging.DEBUG)
    code = code_for(status)
    due_schedules(sched, ids(4))
    owner = sched.schedules.get("sched_00").owner_user_id
    use_session(sched, TasksSession(lambda _name: status))
    sched.tick()
    errors = tilo_api_errors(caplog)
    assert len(errors) == 1, [r.getMessage() for r in errors]
    record = errors[0]
    assert code in record.getMessage()
    assert getattr(record, LOG_FIELD_CODE, None) == code
    got_status = getattr(record, LOG_FIELD_STATUS, None)
    assert type(got_status) is int and got_status == status, got_status
    assert_ids_only(record)
    for leaked in (owner, *ids(4)):  # the stop line names no schedule or owner (as 14f's)
        assert leaked not in record.getMessage(), leaked

    sched.clock.set(MON_0330Z + timedelta(minutes=1))
    sched.tick()
    errors = tilo_api_errors(caplog)
    assert len(errors) == 2 and all(code in r.getMessage() for r in errors)  # once per tick


@pytest.mark.parametrize("status", [429, 503])
def test_FR_AGT_14h_a_lone_due_slot_with_a_429_or_5xx_is_counted_as_today(sched: SchedApi, status: int) -> None:
    """One call cannot tell the service's outage from one schedule's: counted, 200 (BQ-AGT14-8 c)."""
    due_schedules(sched, ids(1))
    session = TasksSession(lambda _name: status)
    use_session(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert session.posts == [name_of("sched_00")]
    assert_counted(sched, "sched_00")


@pytest.mark.parametrize(
    ("first", "second"),
    [(429, 503), (502, 503), (500, 429), (429, 400), (503, 409), (429, "boom"), ("boom", 429)],
)
def test_FR_AGT_14h_mixed_first_failures_keep_todays_behaviour(
    sched: SchedApi, first: int | str, second: int | str
) -> None:
    """Different statuses (the exact status decides: 502 and 503 differ), or one side not an HTTP answer: every slot is
    tried and every failure counted, 200. The third slot repeats the first answer and is counted too."""
    due_schedules(sched, ids(3))
    session = TasksSession(by_slot({"sched_00": first, "sched_01": second, "sched_02": first}))
    use_session(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert session.posts == [name_of(s) for s in ids(3)]
    for schedule_id in ids(3):
        assert_counted(sched, schedule_id)


@pytest.mark.parametrize("first", ["ok", "exists"])
@pytest.mark.parametrize("status", [429, 503])
def test_FR_AGT_14h_a_success_before_alike_failures_keeps_todays_behaviour(
    sched: SchedApi, status: int, first: str
) -> None:
    """Only the first two calls of a tick can pair: after a success, alike failures are counted per schedule."""
    due_schedules(sched, ids(3))
    session = TasksSession(by_slot({"sched_01": status, "sched_02": status}))
    if first == "exists":
        session.creations[name_of("sched_00")] = 1
    use_session(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 1})
    assert session.posts == [name_of(s) for s in ids(3)]
    assert_handed_over(sched, "sched_00")
    assert_counted(sched, "sched_01")
    assert_counted(sched, "sched_02")


@pytest.mark.parametrize("status", [400, 409])
def test_FR_AGT_14h_400_and_409_aborted_are_never_service_wide(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(4))
    session = TasksSession(lambda _name: status)
    use_session(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert len(session.posts) == 4
    for schedule_id in ids(4):
        assert_counted(sched, schedule_id)
    assert [r for r in tilo_api_errors(caplog) if "tasks_" in r.getMessage()] == []
    assert [getattr(r, LOG_FIELD_STATUS, None) for r in enqueue_warnings(caplog)] == [status] * 4


@pytest.mark.parametrize("status", [429, 503])
def test_FR_AGT_14h_after_a_quota_or_server_stop_every_slot_fires_once_when_tasks_recovers(
    sched: SchedApi, status: int
) -> None:
    schedule_ids = ids(4)
    due_schedules(sched, schedule_ids)
    failing = {"on": True}
    session = TasksSession(lambda _name: status if failing["on"] else None)
    use_session(sched, session)
    assert sched.tick().status_code == UNAVAILABLE
    failing["on"] = False
    sched.clock.set(MON_0330Z + timedelta(minutes=1))  # inside the 5-minute lease: only released claims are retried
    again = sched.tick()
    assert (again.status_code, again.json()) == (200, {"fired": 4})
    assert session.creations == Counter({name_of(s): 1 for s in schedule_ids})
    for schedule_id in schedule_ids:
        assert_handed_over(sched, schedule_id)


@pytest.mark.parametrize("status", [429, 503])
def test_FR_AGT_14h_a_quota_or_server_outage_longer_than_max_failures_disables_nothing(
    sched: SchedApi, status: int
) -> None:
    """The case 14g left open (BQ-AGT14-7 Open): ticks spaced past the longest backoff, more of them than MAX_FAILURES,
    every call answering the same status. Today every schedule is counted each time until all are disabled; under 14h
    no schedule is ever counted, each tick makes two calls and answers 503, and recovery fires every slot."""
    schedule_ids = ids(3)
    due_schedules(sched, schedule_ids)
    failing = {"on": True}
    session = TasksSession(lambda _name: status if failing["on"] else None)
    use_session(sched, session)
    spacing = MAX_BACKOFF + timedelta(hours=1)
    for n in range(MAX_FAILURES + 1):
        sched.clock.set(MON_0330Z + n * spacing)
        response = sched.tick()
        assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": code_for(status)}), n
        for schedule_id in schedule_ids:
            record = sched.schedules.get(schedule_id)
            got = (record.enabled, record.failures, record.last_error, record.backoff_until)
            assert got == (True, 0, None, None), (n, schedule_id, got)
    assert len(session.posts) == 2 * (MAX_FAILURES + 1)

    failing["on"] = False
    sched.clock.set(MON_0330Z + (MAX_FAILURES + 1) * spacing)
    recovered = sched.tick()
    assert (recovered.status_code, recovered.json()) == (200, {"fired": 3})


# --- property: which slots are counted, for any mix of answers ---------------------------------------------------

OUTCOMES = st.sampled_from(["ok", "exists", "boom", 400, 409, *TRANSIENT])


def _fresh(rig: SchedApi, n: int) -> list[str]:
    """A new store per Hypothesis example, with one approved task shared by every example."""
    task = getattr(rig, "_14h_task", None) or rig.approved_task()
    rig._14h_task = task  # type: ignore[attr-defined]
    rig.schedules = InMemoryScheduleStore(clock=rig.clock)  # the rig's overrides read this at call time
    rig.clock.set(MON_0330Z)
    schedule_ids = ids(n)
    for schedule_id in schedule_ids:
        rig.insert(task, schedule_id)
    return schedule_ids


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(outcomes=st.lists(OUTCOMES, min_size=1, max_size=MAX_FIRES_PER_TICK + 3))
def test_FR_AGT_14h_property_only_two_alike_first_failures_stop_the_tick_and_nothing_else_changes(
    sched: SchedApi, outcomes: list[int | str]
) -> None:
    """For any due slots, in the store's order, answering ok / ALREADY_EXISTS / an unclassified exception / 400 / 409
    ABORTED / 429 / a 5xx: if the first two answers are the same 429 or the same 5xx, exactly those two calls are made,
    no slot is counted or moved, and the answer is 503 with its code. Otherwise today's behaviour holds: up to
    MAX_FIRES_PER_TICK calls, successes handed over, every failure counted once, later slots due, 200 fired."""
    schedule_ids = _fresh(sched, len(outcomes))
    answers = {s: o for s, o in zip(schedule_ids, outcomes, strict=True) if o not in ("ok", "exists")}
    session = TasksSession(by_slot(answers))
    for schedule_id, outcome in zip(schedule_ids, outcomes, strict=True):
        if outcome == "exists":
            session.creations[name_of(schedule_id)] = 1
    use_session(sched, session)
    response = sched.tick()

    paired = len(outcomes) >= 2 and outcomes[0] == outcomes[1] and outcomes[0] in TRANSIENT
    if paired:
        assert session.posts == [name_of(s) for s in schedule_ids[:2]]
        for schedule_id in schedule_ids:
            assert_still_due(sched, schedule_id)
        assert isinstance(outcomes[0], int)
        assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": code_for(outcomes[0])})
        return
    tried = outcomes[:MAX_FIRES_PER_TICK]
    assert session.posts == [name_of(s) for s in schedule_ids[: len(tried)]]
    for schedule_id, outcome in zip(schedule_ids, tried, strict=False):
        if outcome in ("ok", "exists"):
            assert_handed_over(sched, schedule_id)
        else:
            assert_counted(sched, schedule_id)
    for schedule_id in schedule_ids[len(tried) :]:
        assert_still_due(sched, schedule_id)
    fired = sum(o in ("ok", "exists") for o in tried)
    assert (response.status_code, response.json()) == (200, {"fired": fired})
