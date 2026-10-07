"""FR-AGT-14g (issue #502, the security reviewer's follow-up on PR #579; PRD 6.3, 8.6, NFR-23, NFR-26): a credential or
network outage of Cloud Tasks stops the tick the way 14f's `tasks_unavailable` does. API_FR_AGT_14g.md; BQ-AGT14-7.

Today a revoked or broken metadata credential surfaces as `google.auth.exceptions.RefreshError` (not as a 401), and a
network failure as `google.auth.exceptions.TransportError` or `requests` `Timeout` / `ConnectionError`. Each is counted
against every due schedule (`start_failed`), so an outage disables every schedule after MAX_FAILURES = 8 ticks, each
answering 200. Pinned here, through the Scheduler's call of the tick route:

1. Those errors are service-wide: the first one stops the tick, the slot and every later one stay due (no failure, no
   backoff, `next_due` unmoved, claim released), and the tick answers 503 with a fixed body:
   `{"detail": "tasks_credential"}` for RefreshError, `{"detail": "tasks_transport"}` for TransportError, Timeout and
   ConnectionError (BQ-AGT14-7 a). One ERROR line per tick, the exception's type name at most.
2. 429 RESOURCE_EXHAUSTED, 5xx and any other exception still count per schedule and the tick goes on (BQ-AGT14-7 b).
3. After recovery every due slot is handed over once: deterministic task names and ALREADY_EXISTS dedupe, also for a
   task whose creation reply was lost to a read timeout.
4. 14e and 14f are unchanged (their tests are not edited).
5. Fakes only: a `requests.Session`-shaped session for the real `CloudTasksRestClient`, google-auth's real
   `AuthorizedSession` over a fake credential and a fake transport adapter, and `FakeTasksClient`; every fake raises the
   real exception classes. No network, no paid call.
"""

from __future__ import annotations

import json as jsonlib
import logging
import re
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from _fr_agt_14_lib import AUDIENCE, MON_0330Z, QUEUE, TASKS_SA, WEEK, FakeTasksClient, SchedApi
from _fr_agt_14e_lib import block_network
from google.auth import credentials as google_credentials
from google.auth import exceptions as google_exceptions
from google.auth.transport.requests import AuthorizedSession
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from requests.adapters import BaseAdapter
from tilo_harness.schedule import MAX_FIRES_PER_TICK, slot_key, task_name
from tilo_harness.schedule_store import MAX_BACKOFF, MAX_FAILURES, InMemoryScheduleStore

UNAVAILABLE = 503
CREDENTIAL = "tasks_credential"  # BQ-AGT14-7 (a): a failed credential refresh
TRANSPORT = "tasks_transport"  # BQ-AGT14-7 (a): the network between tilo-api and Google
SECRET = "tok-" + "s3cret" + "-value"  # assembled at runtime: never a literal secret in the repo
EMAIL = "alice" + "@" + "example.com"
TASKS_HOST = "cloudtasks.googleapis.com"


def _text(kind: str) -> str:
    return f"{kind}: token {SECRET} for {EMAIL} at https://{TASKS_HOST}/v2/{QUEUE}/tasks"


# kind -> (a factory of the real exception, the code and 503 detail it must produce)
OUTAGES: dict[str, tuple[Callable[[], BaseException], str]] = {
    "refresh": (lambda: google_exceptions.RefreshError(_text("metadata server says")), CREDENTIAL),
    "transport": (lambda: google_exceptions.TransportError(_text("metadata unreachable")), TRANSPORT),
    "timeout": (lambda: requests.exceptions.Timeout(_text("timed out")), TRANSPORT),
    "read_timeout": (lambda: requests.exceptions.ReadTimeout(_text("read timed out")), TRANSPORT),
    "connect_timeout": (lambda: requests.exceptions.ConnectTimeout(_text("connect timed out")), TRANSPORT),
    "connection": (lambda: requests.exceptions.ConnectionError(_text("connection refused")), TRANSPORT),
}
KINDS = sorted(OUTAGES)


def outage(kind: str) -> BaseException:
    return OUTAGES[kind][0]()


def body_of(kind: str) -> dict[str, str]:
    return {"detail": OUTAGES[kind][1]}


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
    """Refused or never tried: nothing recorded, nothing moved, the schedule on."""
    record = rig.schedules.get(schedule_id)
    got = (record.enabled, record.failures, record.next_due, record.last_error, record.backoff_until, record.last_slot)
    assert got == (True, 0, MON_0330Z, None, None, None), (schedule_id, got)


def assert_never_counted(rig: SchedApi, schedule_id: str) -> None:
    """Whatever slot it is on: no failure, no backoff, no error code, still enabled."""
    record = rig.schedules.get(schedule_id)
    got = (record.enabled, record.failures, record.last_error, record.backoff_until)
    assert got == (True, 0, None, None), (schedule_id, got)


def assert_handed_over(rig: SchedApi, schedule_id: str, due: Any = MON_0330Z) -> None:
    record = rig.schedules.get(schedule_id)
    got = (record.next_due, record.last_slot, record.failures)
    assert got == (due + WEEK, slot_key(schedule_id, due), 0), (schedule_id, got)


def use_rest_client(rig: SchedApi, session: Any) -> None:
    """The real `CloudTasksRestClient` over `session` (the `requests.Session` shape it takes)."""
    from tilo_api import schedules

    rig.app.dependency_overrides[schedules.get_tasks_client_factory] = lambda: (
        lambda: schedules.CloudTasksRestClient(session=session)
    )


def tilo_api_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR and r.name.startswith("tilo_api.")]


class RaisingSession:
    """The `requests.Session` shape: every POST raises the outage `kind` (as `AuthorizedSession.post` does when the
    credential refresh or the connection fails)."""

    def __init__(self, kind: str) -> None:
        self.kind, self.posts = kind, []

    def post(self, url: str, *, json: Any = None, timeout: Any = None, max_allowed_time: Any = None) -> Any:
        self.posts.append(url)
        raise outage(self.kind)


class FakeTasksSession:
    """Cloud Tasks' create-task endpoint in the `requests.Session` shape, with no network. A new task name is created
    (200); a name already created answers 409 ALREADY_EXISTS. `outage` (a kind) makes every POST raise before anything
    is created; `lose_reply` names tasks that are created and THEN answered with a read timeout (once each);
    `status_for(name)` may answer an HTTP error status instead (nothing created)."""

    def __init__(self) -> None:
        self.posts: list[str] = []
        self.creations: Counter[str] = Counter()
        self.outage: str | None = None
        self.lose_reply: set[str] = set()
        self.status_for: Callable[[str], int | None] = lambda _name: None

    def post(self, url: str, *, json: Any = None, timeout: Any = None, max_allowed_time: Any = None) -> Any:
        name = json["task"]["name"]
        self.posts.append(name)
        if self.outage is not None:
            raise outage(self.outage)
        status = self.status_for(name)
        if status is not None:
            return _answer(status, _STATUS_NAMES.get(status, "UNKNOWN"))
        if self.creations[name]:
            return _answer(409, "ALREADY_EXISTS")
        self.creations[name] += 1
        if name in self.lose_reply:
            self.lose_reply.discard(name)
            raise requests.exceptions.ReadTimeout(_text("read timed out"))
        return _answer(200, None)


_STATUS_NAMES = {429: "RESOURCE_EXHAUSTED", 500: "INTERNAL", 502: "UNAVAILABLE", 503: "UNAVAILABLE", 504: "DEADLINE"}


def _answer(status: int, rpc_status: str | None) -> Any:
    def body() -> Any:
        if rpc_status is None:
            return {"name": "created"}
        return {"error": {"code": status, "status": rpc_status, "message": f"token {SECRET} for {EMAIL}"}}

    return SimpleNamespace(status_code=status, text=f"provider says: token {SECRET} ({status})", json=body)


class FakeCredentials(google_credentials.Credentials):
    """A google-auth credential that never touches a metadata server: `token` set means valid; `refresh` raises
    `refresh_error` when given (a revoked service account, a broken metadata credential) and is counted."""

    def __init__(self, *, token: str | None = None, refresh_error: Callable[[], BaseException] | None = None) -> None:
        super().__init__()
        self.token, self.refresh_error, self.refreshes = token, refresh_error, 0

    def refresh(self, request: Any) -> None:
        self.refreshes += 1
        if self.refresh_error is not None:
            raise self.refresh_error()
        self.token = "fake-" + "access-token"


class FakeAdapter(BaseAdapter):
    """A `requests` transport adapter mounted on the real `AuthorizedSession`: raises `error()` when given, else answers
    `status` with an empty JSON body. Records each URL sent."""

    def __init__(self, *, status: int = 200, error: Callable[[], BaseException] | None = None) -> None:
        super().__init__()
        self.status, self.error, self.sent = status, error, []

    def send(self, request: Any, **kwargs: Any) -> requests.Response:
        self.sent.append(request.url)
        if self.error is not None:
            raise self.error()
        response = requests.Response()
        response.status_code, response.request, response.url = self.status, request, request.url
        response._content = jsonlib.dumps({}).encode()
        response.headers["Content-Type"] = "application/json"
        return response

    def close(self) -> None:
        pass


class NoAuthRequest:
    """google-auth's refresh transport: a fake credential never calls it; if anything does, the test fails."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a credential refresh tried to reach the network")


def authorized(credentials: FakeCredentials, adapter: FakeAdapter) -> AuthorizedSession:
    session = AuthorizedSession(credentials, auth_request=NoAuthRequest())
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# --- 1. a credential or network error stops the tick ---------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_FR_AGT_14g_a_credential_or_network_error_stops_the_tick_and_leaves_every_slot_due(
    sched: SchedApi, kind: str
) -> None:
    due_schedules(sched, ids(4))
    session = RaisingSession(kind)
    use_rest_client(sched, session)
    response = sched.tick()
    assert len(session.posts) == 1, f"{len(session.posts)} enqueue calls after a service-wide {kind}"
    for schedule_id in ids(4):
        assert_still_due(sched, schedule_id)
    assert (response.status_code, response.json()) == (UNAVAILABLE, body_of(kind))


@pytest.mark.parametrize("kind", KINDS)
def test_FR_AGT_14g_any_tasks_client_raising_these_errors_stops_the_tick(sched: SchedApi, kind: str) -> None:
    """The rule is the fan-out's, whichever `TasksClient` raised the error (API_FR_AGT_14g.md item 1)."""
    due_schedules(sched, ids(3))
    sched.tasks.error = outage(kind)
    response = sched.tick()
    assert len(sched.tasks.calls) == 1
    assert sched.tasks.calls[0]["name"] == name_of("sched_00")  # the oldest due slot is the one tried
    for schedule_id in ids(3):
        assert_still_due(sched, schedule_id)
    assert (response.status_code, response.json()) == (UNAVAILABLE, body_of(kind))


def test_FR_AGT_14g_a_failed_refresh_in_the_real_authorized_session_is_a_credential_outage(sched: SchedApi) -> None:
    """google-auth refreshes a credential with no token before the first request: a revoked or broken metadata
    credential raises RefreshError there, and nothing is sent."""
    due_schedules(sched, ids(3))
    credentials = FakeCredentials(refresh_error=lambda: google_exceptions.RefreshError(_text("metadata says")))
    adapter = FakeAdapter(status=200)
    use_rest_client(sched, authorized(credentials, adapter))
    response = sched.tick()
    assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": CREDENTIAL})
    assert adapter.sent == [] and credentials.refreshes == 1  # one refresh attempt for the whole tick
    for schedule_id in ids(3):
        assert_still_due(sched, schedule_id)


def test_FR_AGT_14g_a_401_whose_token_refresh_fails_is_a_credential_outage(sched: SchedApi) -> None:
    """A revoked token: Cloud Tasks answers 401, `AuthorizedSession` refreshes and retries, and the refresh raises."""
    due_schedules(sched, ids(3))
    credentials = FakeCredentials(
        token="fake-" + "stale-token", refresh_error=lambda: google_exceptions.RefreshError(_text("revoked"))
    )
    adapter = FakeAdapter(status=401)
    use_rest_client(sched, authorized(credentials, adapter))
    response = sched.tick()
    assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": CREDENTIAL})
    assert len(adapter.sent) == 1 and credentials.refreshes == 1
    for schedule_id in ids(3):
        assert_still_due(sched, schedule_id)


@pytest.mark.parametrize(
    "error",
    [requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout],
    ids=["connection", "connect_timeout", "read_timeout"],
)
def test_FR_AGT_14g_a_network_failure_in_the_real_authorized_session_is_a_transport_outage(
    sched: SchedApi, error: type[BaseException]
) -> None:
    due_schedules(sched, ids(3))
    credentials = FakeCredentials(token="fake-" + "valid-token")
    adapter = FakeAdapter(error=lambda: error(_text("network")))
    use_rest_client(sched, authorized(credentials, adapter))
    response = sched.tick()
    assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": TRANSPORT})
    assert len(adapter.sent) == 1, "the tick kept calling Cloud Tasks through a network outage"
    for schedule_id in ids(3):
        assert_still_due(sched, schedule_id)


def test_FR_AGT_14g_an_outage_mid_tick_keeps_what_was_handed_over_and_leaves_the_rest_due(sched: SchedApi) -> None:
    due_schedules(sched, ids(4))
    broken = name_of("sched_01")
    sched.tasks.fail_when = lambda task: outage("transport") if task["name"] == broken else None
    response = sched.tick()
    assert [t["name"] for t in sched.tasks.calls] == [name_of("sched_00"), broken]  # nothing after the outage
    assert_handed_over(sched, "sched_00")
    for schedule_id in ("sched_01", "sched_02", "sched_03"):
        assert_still_due(sched, schedule_id)
    assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": TRANSPORT})

    sched.tasks.fail_when = None
    sched.clock.set(MON_0330Z + timedelta(minutes=1))  # inside the 5-minute lease: only a released claim is retried
    again = sched.tick()
    assert (again.status_code, again.json()) == (200, {"fired": 3})
    assert len(sched.tasks.created) == 4  # sched_00 was not handed over twice


@pytest.mark.parametrize("kind", ["refresh", "connection"])
def test_FR_AGT_14g_an_outage_longer_than_max_failures_disables_nothing_and_every_tick_answers_503(
    sched: SchedApi, kind: str
) -> None:
    """The reviewer's case: ticks spaced past the longest backoff, more of them than MAX_FAILURES. Today each one counts
    against every schedule (200 each time) until all are disabled; under 14g none counts and each tick is a 503."""
    schedule_ids = ids(3)
    due_schedules(sched, schedule_ids)
    sched.tasks.error = outage(kind)
    spacing = MAX_BACKOFF + timedelta(hours=1)
    for n in range(MAX_FAILURES + 1):
        sched.clock.set(MON_0330Z + n * spacing)
        response = sched.tick()
        assert (response.status_code, response.json()) == (UNAVAILABLE, body_of(kind)), n
        for schedule_id in schedule_ids:
            assert_never_counted(sched, schedule_id)
    assert len(sched.tasks.calls) == MAX_FAILURES + 1  # one call per refused tick

    sched.tasks.error = None
    sched.clock.set(MON_0330Z + (MAX_FAILURES + 1) * spacing)  # past MON_0330Z + WEEK: the latest slot fires
    recovered = sched.tick()
    assert (recovered.status_code, recovered.json()) == (200, {"fired": 3})
    assert sorted(sched.tasks.created) == sorted(name_of(s, MON_0330Z + WEEK) for s in schedule_ids)
    for schedule_id in schedule_ids:
        # Test fixed: the store contract sets last_slot = slot_key(id, due) for the CLAIMED due (MON_0330Z), not the
        # caught-up slot that fired (ScheduleStore.complete, harness API_FR_AGT_14.md); next_due moves past it.
        record = sched.schedules.get(schedule_id)
        got = (record.next_due, record.last_slot, record.failures)
        assert got == (MON_0330Z + 2 * WEEK, slot_key(schedule_id, MON_0330Z), 0), (schedule_id, got)


# --- 2. the 503 body is fixed ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_FR_AGT_14g_the_503_body_is_fixed_and_carries_no_exception_text(sched: SchedApi, kind: str) -> None:
    due_schedules(sched, ids(2))
    use_rest_client(sched, RaisingSession(kind))
    response = sched.tick()
    assert response.status_code == UNAVAILABLE
    assert response.json() == body_of(kind)
    leaks = [SECRET, "alice", TASKS_HOST, QUEUE, TASKS_SA, AUDIENCE, "sched-"]
    leaks += ["Traceback", type(outage(kind)).__name__]
    for leaked in leaks:
        assert leaked not in response.text, leaked


# --- 3. one ERROR line per tick, the type name at most ---------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_FR_AGT_14g_the_outage_is_logged_once_per_tick_at_error_with_its_code(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    caplog.set_level(logging.DEBUG)
    code = OUTAGES[kind][1]
    due_schedules(sched, ids(4))
    use_rest_client(sched, RaisingSession(kind))
    sched.tick()
    errors = tilo_api_errors(caplog)
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert code in errors[0].getMessage()
    sched.clock.set(MON_0330Z + timedelta(minutes=1))
    sched.tick()
    errors = tilo_api_errors(caplog)
    assert len(errors) == 2 and all(code in r.getMessage() for r in errors)  # once per tick, not once per process


@pytest.mark.parametrize("kind", KINDS)
def test_FR_AGT_14g_the_error_line_carries_the_code_and_the_type_name_at_most(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    caplog.set_level(logging.DEBUG)
    schedule_ids = ids(3)
    due_schedules(sched, schedule_ids)
    owner = sched.schedules.get("sched_00").owner_user_id
    use_rest_client(sched, RaisingSession(kind))
    sched.tick()
    errors = tilo_api_errors(caplog)
    assert len(errors) == 1, "no single ERROR line for the outage on a tilo_api.* logger"
    record = errors[0]
    assert record.exc_info is None and record.exc_text is None  # never a traceback
    for arg in record.args if isinstance(record.args, tuple) else ():
        assert isinstance(arg, int) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", str(arg)), arg
    message = record.getMessage()
    leaks = [SECRET, EMAIL, TASKS_HOST, QUEUE, TASKS_SA, AUDIENCE, "sched-", owner]  # exception text, ids
    for leaked in [*leaks, *schedule_ids]:
        assert leaked not in message, leaked
    for leaked in (SECRET, EMAIL, "Traceback", TASKS_HOST):  # nor in any other line of the tick
        assert leaked not in caplog.text, leaked


# --- 4. what still counts per schedule -------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_FR_AGT_14g_quota_and_server_errors_still_count_per_schedule_and_the_tick_goes_on(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    """BQ-AGT14-7 (b): Cloud Tasks answered, so the credential and the network work; the answer may be one call's, and
    the per-schedule backoff spaces the retries. Counted, the tick goes on, 200, no `tasks_` ERROR line."""
    caplog.set_level(logging.DEBUG)
    due_schedules(sched, ids(3))
    session = FakeTasksSession()
    # changed deliberately: BQ-AGT14-8: the first two calls answering the same 429/5xx are the service's (FR-AGT-14h),
    # so the first slot succeeds and the alike answers come after it, where each is still counted per schedule.
    first = name_of("sched_00")
    session.status_for = lambda name: None if name == first else status
    use_rest_client(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 1})  # changed deliberately: BQ-AGT14-8
    assert len(session.posts) == 3  # every due slot tried
    assert_handed_over(sched, "sched_00")  # changed deliberately: BQ-AGT14-8
    for schedule_id in ids(3)[1:]:  # changed deliberately: BQ-AGT14-8
        record = sched.schedules.get(schedule_id)
        assert (record.failures, record.next_due, record.enabled) == (1, MON_0330Z, True), schedule_id
        assert record.backoff_until is not None and record.last_error is not None, schedule_id
    assert [r for r in tilo_api_errors(caplog) if "tasks_" in r.getMessage()] == []
    assert SECRET not in response.text and SECRET not in caplog.text


def test_FR_AGT_14g_a_quota_error_for_one_slot_does_not_stop_the_others(sched: SchedApi) -> None:
    due_schedules(sched, ids(3))
    session = FakeTasksSession()
    throttled = name_of("sched_01")
    session.status_for = lambda name: 429 if name == throttled else None
    use_rest_client(sched, session)
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 2})
    assert_handed_over(sched, "sched_00")
    assert_handed_over(sched, "sched_02")
    assert sched.schedules.get("sched_01").failures == 1


@pytest.mark.parametrize("error", [RuntimeError, ValueError, KeyError])
def test_FR_AGT_14g_an_unclassified_exception_still_counts_per_schedule(
    sched: SchedApi, error: type[BaseException]
) -> None:
    due_schedules(sched, ids(3))
    sched.tasks.error = error(_text("down"))
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert len(sched.tasks.calls) == 3
    for schedule_id in ids(3):
        assert sched.schedules.get(schedule_id).failures == 1, schedule_id


# --- 5. no double start after recovery ------------------------------------------------------------------------------


def test_FR_AGT_14g_a_task_created_before_its_reply_was_lost_is_handed_over_once(sched: SchedApi) -> None:
    """A read timeout can come after Cloud Tasks created the task. The slot stays due; the retry meets ALREADY_EXISTS,
    which is a success, so the slot is handed over once and its task exists once."""
    due_schedules(sched, ids(3))
    session = FakeTasksSession()
    session.lose_reply = {name_of("sched_00")}
    use_rest_client(sched, session)
    first = sched.tick()
    assert (first.status_code, first.json()) == (UNAVAILABLE, {"detail": TRANSPORT})
    assert session.posts == [name_of("sched_00")]
    for schedule_id in ids(3):
        assert_still_due(sched, schedule_id)

    sched.clock.set(MON_0330Z + timedelta(minutes=1))
    second = sched.tick()
    assert (second.status_code, second.json()) == (200, {"fired": 3})
    assert session.creations == Counter({name_of(s): 1 for s in ids(3)})
    for schedule_id in ids(3):
        assert_handed_over(sched, schedule_id)


@pytest.mark.parametrize("kind", ["refresh", "transport", "timeout"])
def test_FR_AGT_14g_after_recovery_every_due_slot_fires_exactly_once(sched: SchedApi, kind: str) -> None:
    schedule_ids = ids(4)
    due_schedules(sched, schedule_ids)
    session = FakeTasksSession()
    session.outage = kind
    use_rest_client(sched, session)
    for minute in range(3):
        sched.clock.set(MON_0330Z + timedelta(minutes=minute))
        assert sched.tick().status_code == UNAVAILABLE
    session.outage = None
    fired = []
    for minute in range(3, 7):  # the recovery tick, then ticks with nothing left due
        sched.clock.set(MON_0330Z + timedelta(minutes=minute))
        response = sched.tick()
        assert response.status_code == 200, response.text
        fired.append(response.json()["fired"])
    assert fired == [4, 0, 0, 0]
    assert session.creations == Counter({name_of(s): 1 for s in schedule_ids})
    assert len(session.posts) == 3 + 4  # one refused call per outage tick, then one per slot
    for schedule_id in schedule_ids:
        assert_handed_over(sched, schedule_id)


# --- properties ----------------------------------------------------------------------------------------------------


def _fresh(rig: SchedApi, n: int) -> list[str]:
    """A new store and Tasks fake per Hypothesis example, with one approved task shared by every example."""
    task = getattr(rig, "_14g_task", None) or rig.approved_task()
    rig._14g_task = task  # type: ignore[attr-defined]
    rig.schedules = InMemoryScheduleStore(clock=rig.clock)  # the rig's overrides read these at call time
    rig.tasks = FakeTasksClient()
    rig.clock.set(MON_0330Z)
    schedule_ids = ids(n)
    for schedule_id in schedule_ids:
        rig.insert(task, schedule_id)
    return schedule_ids


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    n=st.integers(min_value=1, max_value=5),
    ticks=st.lists(st.one_of(st.none(), st.sampled_from(KINDS)), min_size=1, max_size=10),
)
def test_FR_AGT_14g_property_an_outage_never_counts_and_every_slot_fires_once(
    sched: SchedApi, n: int, ticks: list[str | None]
) -> None:
    """For any run of one-minute ticks, each either healthy or failing with one of the outage kinds, then a healthy
    tick: no schedule ever gains a failure, backoff or error code; an outage tick with something due makes one call and
    answers 503 with its code; a tick with nothing due makes no call and answers 200; every slot is created once."""
    schedule_ids = _fresh(sched, n)
    for minute, kind in enumerate([*ticks, None]):
        sched.clock.set(MON_0330Z + timedelta(minutes=minute))
        sched.tasks.error = outage(kind) if kind is not None else None
        pending = [s for s in schedule_ids if sched.schedules.get(s).next_due == MON_0330Z]
        before = len(sched.tasks.calls)
        response = sched.tick()
        if kind is not None and pending:
            assert len(sched.tasks.calls) - before == 1
            assert (response.status_code, response.json()) == (UNAVAILABLE, body_of(kind))
        elif not pending:
            assert len(sched.tasks.calls) == before
            assert (response.status_code, response.json()) == (200, {"fired": 0})
        else:
            assert (response.status_code, response.json()) == (200, {"fired": len(pending)})
        for schedule_id in schedule_ids:
            assert_never_counted(sched, schedule_id)
    assert sorted(sched.tasks.created) == sorted(name_of(s) for s in schedule_ids)
    for schedule_id in schedule_ids:
        assert_handed_over(sched, schedule_id)


SLOT_OUTCOMES = st.sampled_from(["ok", "exists", "fail", "unavailable", *KINDS])


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(outcomes=st.lists(SLOT_OUTCOMES, min_size=1, max_size=MAX_FIRES_PER_TICK + 3))
def test_FR_AGT_14g_property_calls_stop_at_the_first_service_wide_error_and_its_code_is_the_answer(
    sched: SchedApi, outcomes: list[str]
) -> None:
    """For any due slots answering ok / ALREADY_EXISTS / a per-schedule failure / a 14f refusal / a 14g outage, in the
    store's order: calls stop right after the first service-wide error (or at MAX_FIRES_PER_TICK); slots before it keep
    their behaviour; it and every later slot stay due; the answer is 503 with the FIRST stopping error's code, else
    200."""
    from tilo_api import schedules

    schedule_ids = _fresh(sched, len(outcomes))
    by_name = {name_of(s): o for s, o in zip(schedule_ids, outcomes, strict=True)}
    for name, outcome in by_name.items():
        if outcome == "exists":
            sched.tasks.created[name] = {"name": name}

    def fail_when(t: dict[str, Any]) -> BaseException | None:
        outcome = by_name[t["name"]]
        if outcome == "unavailable":
            return schedules.TasksUnavailable("cloud tasks answered 403", status=403)
        if outcome in OUTAGES:
            return outage(outcome)
        return RuntimeError("down") if outcome == "fail" else None

    sched.tasks.fail_when = fail_when
    response = sched.tick()

    stopping = {"unavailable", *KINDS}
    tried = outcomes[:MAX_FIRES_PER_TICK]
    first = next((i for i, o in enumerate(tried) if o in stopping), None)
    stop = first + 1 if first is not None else len(tried)
    assert [t["name"] for t in sched.tasks.calls] == [name_of(s) for s in schedule_ids[:stop]]
    for schedule_id, outcome in zip(schedule_ids[:stop], tried[:stop], strict=True):
        if outcome in ("ok", "exists"):
            assert_handed_over(sched, schedule_id)
        elif outcome == "fail":
            assert sched.schedules.get(schedule_id).failures == 1, schedule_id
    for index, schedule_id in enumerate(schedule_ids):
        if index >= stop or (first is not None and index == first):
            assert_still_due(sched, schedule_id)
    if first is None:
        fired = sum(o in ("ok", "exists") for o in tried)
        assert (response.status_code, response.json()) == (200, {"fired": fired})
    else:
        code = "tasks_unavailable" if tried[first] == "unavailable" else OUTAGES[tried[first]][1]
        assert (response.status_code, response.json()) == (UNAVAILABLE, {"detail": code})
