"""Helpers for the FR-AGT-14b acceptance tests: schedule routes, scheduled-run start and the tick route on tilo-api
(interface: API_FR_AGT_14b.md; PRD 6.3, 8.6; design fr-agt-14b-design.md).

Package-unique name, like `_clint2_lib.py`. Nothing here is business logic. `SchedApi` wraps a CL-INT-1 `Flow` (or a
CL-INT-2 `RunFlow`, whose run seams make a fired run really run to its gate) and installs the schedule seams of
API_FR_AGT_14b.md: an in-memory schedule store on a fake clock, a fake OIDC verifier and a flag store. The tick route is
configured through the two environment names the document pins, with `monkeypatch`.
"""

from __future__ import annotations

import base64
import copy
import json
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from _api_lib import make_writer
from _clint1_lib import FLOW_USER, OTHER_USER, Flow, seam
from tilo_harness.schedule import Cadence, Schedule
from tilo_harness.schedule_store import InMemoryScheduleStore
from tilo_metering.flags import InMemoryFlagStore

SUNDAY = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
MON_0330Z = datetime(2026, 10, 5, 3, 30, tzinfo=UTC)  # Monday 09:00 in Asia/Kolkata
WEEK = timedelta(days=7)
CADENCE = {"weekday": 0, "hour": 9, "minute": 0, "tz": "Asia/Kolkata"}
TITLE = "Weekly supplier digest"
CAP = 60  # the cap the owner confirms at approve (not equal to any scripted approach credit figure)

PROJECT = "demo-tilo"
AUDIENCE = "https://tilo-api-abc123-as.a.run.app"
SCHEDULE_SA = f"tilo-schedule-scheduler@{PROJECT}.iam.gserviceaccount.com"
GMAIL_SA = f"tilo-gmail-scheduler@{PROJECT}.iam.gserviceaccount.com"
TASKS_SA = f"tilo-tasks-invoker@{PROJECT}.iam.gserviceaccount.com"
API_SA = f"tilo-api@{PROJECT}.iam.gserviceaccount.com"
GOOGLE_ISSUER = "https://accounts.google.com"
TICK = "/internal/schedules/tick"
ENV_AUDIENCE = "TILO_SCHEDULE_TICK_AUDIENCE"
ENV_CALLER = "TILO_SCHEDULE_TICK_CALLER"
ENV_STORE = "TILO_SCHEDULES_STORE"
# FR-AGT-14e (API_FR_AGT_14e.md): the Cloud Tasks hand-off (the Scheduler fans out; Cloud Tasks calls the same route).
ENV_QUEUE = "TILO_RUNS_QUEUE"
ENV_TASKS_CALLER = "TILO_TASKS_CALLER"
QUEUE = f"projects/{PROJECT}/locations/asia-southeast1/queues/runs"


class FakeTasksClient:
    """The `TasksClient` Protocol of API_FR_AGT_14e.md, with no network: `enqueue(task) -> None | AlreadyExists`.

    Records a deep copy of every task it is handed (`calls`). A task NAME it has already accepted answers
    `AlreadyExists()` (Cloud Tasks' ALREADY_EXISTS inside the name-reuse window) and is not stored twice. `error` makes
    every call raise it (a transport or permission failure); `fail_when(task)` raises for chosen tasks only."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.created: dict[str, dict[str, Any]] = {}
        self.error: BaseException | None = None
        self.fail_when: Callable[[dict[str, Any]], BaseException | None] | None = None
        self._lock = threading.Lock()

    def enqueue(self, task: Mapping[str, Any]) -> Any:
        from tilo_api.schedules import AlreadyExists  # noqa: PLC0415 - a missing name fails the test that needs it

        snapshot = copy.deepcopy(dict(task))
        with self._lock:
            self.calls.append(snapshot)
            if self.error is not None:
                raise self.error
            if self.fail_when is not None and (failure := self.fail_when(snapshot)) is not None:
                raise failure
            if snapshot["name"] in self.created:
                return AlreadyExists()
            self.created[snapshot["name"]] = snapshot
            return None


def task_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON body of a Cloud Tasks HTTP task (the REST resource carries it base64-encoded)."""
    return json.loads(base64.b64decode(task["httpRequest"]["body"]))


def task_body(schedule_id: str, due: datetime, **extra: Any) -> dict[str, Any]:
    """The body Cloud Tasks delivers for one slot: `schedule_id`, `slot` (the slot key) and `due` (ISO, UTC), plus what
    the fan-out also writes (`skipped`, `prior_world_id`; BQ-AGT14-5 R1), which a test passes as `extra` (both are
    optional: a body without them means 0 and None)."""
    from tilo_harness.schedule import slot_key  # noqa: PLC0415

    return {
        "schedule_id": schedule_id, "slot": slot_key(schedule_id, due), "due": due.astimezone(UTC).isoformat(), **extra,
    }  # fmt: skip


class Clock:
    """The injected clock (`Callable[[], datetime]`, UTC-aware). Moves only when a test moves it."""

    def __init__(self, start: datetime = SUNDAY) -> None:
        self._now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, when: datetime) -> None:
        with self._lock:
            self._now = when

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self._now += delta


class FakeOidcVerifier:
    """`verify(token, audience) -> claims` (the OidcVerifier Protocol): knows only the tokens a test registered;
    anything else raises, as google-auth does for a bad signature, expiry or audience."""

    def __init__(self) -> None:
        self._claims: dict[str, Mapping[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []

    def register(
        self,
        email: Any,
        *,
        aud: Any = AUDIENCE,
        email_verified: Any = True,
        iss: Any = GOOGLE_ISSUER,
        drop: tuple[str, ...] = (),
    ) -> str:
        token = "tok-" + secrets.token_urlsafe(24)  # assembled at runtime, never a real credential
        claims = {"aud": aud, "iss": iss, "email": email, "email_verified": email_verified}
        for name in drop:
            claims.pop(name, None)
        self._claims[token] = claims
        return token

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        self.calls.append((token, audience))
        if token not in self._claims:
            raise ValueError("token not accepted")
        return self._claims[token]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def l3_budget_policy(
    owner: str = FLOW_USER,
    *,
    id_: str = "pol_auto_budget",
    level: str = "L3",
    per_day: int | None = 50,
    credits: float | None = 1000.0,
) -> dict[str, Any]:
    """The owner's standing rule "auto-approve a run budget up to `credits` credits": an L3 `grant_budget` policy
    (the shape FR-INT-08's own tests use). Only a policy like this one can grant a budget without a person."""
    stamp = {"by": owner, "at": "2026-09-29T09:00:00.000Z"}
    return {
        "id": id_, "owner": owner, "action_type": "grant_budget",
        "scope": {"connectors": ["internal"], "recipients": [], "domains": [], "districts": []},
        "limits": {"per_day": per_day, "credits": credits},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": level, "undo_window_s": 60, "expiry": None, "notify_channel": "email", "team_lead_domains": [],
        "created_by": stamp, "changed_by": None, "history": [{**stamp, "change": "Created", "level": level}],
    }  # fmt: skip


@dataclass(frozen=True)
class ApprovedTask:
    task_id: str
    world_id: str
    approach_id: str
    cap: float


class SchedApi:
    """The real app with the schedule seams installed on top of whatever `flow` already wired."""

    def __init__(self, flow: Flow, monkeypatch: Any, *, rf: Any = None, configured: bool = True) -> None:
        from tilo_api import deps, schedules  # noqa: PLC0415

        self.flow, self.rf, self.app, self.store = flow, rf, flow.app, flow.store
        self.clock = Clock()
        self.schedules = InMemoryScheduleStore(clock=self.clock)
        self.verifier = FakeOidcVerifier()
        self.flags = InMemoryFlagStore()
        overrides = flow.app.dependency_overrides
        overrides[seam(schedules, "get_schedule_store")] = lambda: self.schedules
        overrides[seam(schedules, "get_clock")] = lambda: self.clock
        overrides[seam(schedules, "get_oidc_verifier")] = lambda: self.verifier
        overrides[seam(deps, "get_flag_store")] = lambda: self.flags
        if deps.get_event_writer not in overrides:  # the tick's alerts and a fired run write through the single writer
            writer = make_writer(flow.store)
            overrides[deps.get_event_writer] = lambda: writer
        self.tasks = FakeTasksClient()  # FR-AGT-14e: what the tick's fan-out enqueues into (never the network)
        if hasattr(schedules, "get_tasks_client_factory"):  # absent before the 14e builder: the old tests keep running
            overrides[schedules.get_tasks_client_factory] = lambda: lambda: self.tasks
        self._delivered = 0
        if configured:
            monkeypatch.setenv(ENV_AUDIENCE, AUDIENCE)
            monkeypatch.setenv(ENV_CALLER, SCHEDULE_SA)
            monkeypatch.setenv(ENV_QUEUE, QUEUE)
            monkeypatch.setenv(ENV_TASKS_CALLER, TASKS_SA)
        else:
            for name in (ENV_AUDIENCE, ENV_CALLER, ENV_QUEUE, ENV_TASKS_CALLER):
                monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(ENV_STORE, raising=False)
        self.good_token = self.verifier.register(SCHEDULE_SA)
        self.tasks_token = self.verifier.register(TASKS_SA)  # the identity Cloud Tasks signs its deliveries with

    # --- who is calling -------------------------------------------------------------------------

    def as_user(self, user_id: str) -> None:
        self.flow.as_user(user_id)

    def sign_out(self) -> None:
        self.flow.sign_out()

    def as_owner_of(self, world_id: str, user_id: str = FLOW_USER) -> None:
        from tilo_api import deps  # noqa: PLC0415

        self.flow._deny = False
        self.flow.principal = deps.Principal(user_id=user_id, role="owner", world_id=world_id)  # type: ignore[arg-type]

    # --- tasks the owner approved ---------------------------------------------------------------

    def approved_task(self, cap: float = CAP, approach_id: str = "quick") -> ApprovedTask:
        """An intake with nothing to ask, its approaches fetched and the budget granted by the signed-in person."""
        intake = self.flow.task_with_approaches()
        response = self.flow.approve(intake["task_id"], approach_id, cap)
        assert response.status_code == 200, response.text
        return ApprovedTask(intake["task_id"], intake["world_id"], approach_id, cap)

    def unapproved_task(self) -> ApprovedTask:
        """Approaches fetched, but no budget granted."""
        intake = self.flow.task_with_approaches()
        return ApprovedTask(intake["task_id"], intake["world_id"], "quick", 0)

    def source_run_task(self) -> ApprovedTask:
        """With a `RunFlow`: the source task approved by the owner, its run quiet at the gate from here on."""
        from _clint2_lib import wait_for  # noqa: PLC0415

        assert self.rf is not None
        self.rf.start()
        assert self.rf.approve().status_code == 200
        wait_for(lambda: self.rf.events("approval.requested"), what="the source run's gate")
        self.rf.quiet_stream()
        return ApprovedTask(self.rf.task_id, self.rf.world_id, "quick", CAP)

    # --- routes ---------------------------------------------------------------------------------

    def create(self, task: ApprovedTask, /, **body: Any):
        payload = {"task_id": task.task_id, "approach_id": task.approach_id, "title": TITLE, "cadence": dict(CADENCE)}
        payload.update(body)
        return self.flow.client.post("/schedules", json=payload)

    def created(self, task: ApprovedTask, **body: Any) -> dict[str, Any]:
        response = self.create(task, **body)
        assert response.status_code == 201, response.text
        return response.json()

    def get(self, schedule_id: str):
        return self.flow.client.get(f"/schedules/{schedule_id}")

    def patch(self, schedule_id: str, /, **body: Any):
        return self.flow.client.patch(f"/schedules/{schedule_id}", json=body)

    def delete(self, schedule_id: str):
        return self.flow.client.delete(f"/schedules/{schedule_id}")

    def listing(self):
        return self.flow.client.get("/schedules")

    def tick(self, token: str | None = None, **kwargs: Any):
        headers = kwargs.pop("headers", None)
        if headers is None:
            headers = bearer(token or self.good_token)
        return self.flow.client.post(TICK, headers=headers, **kwargs)

    def task_call(self, body: Any, token: str | None = None, **kwargs: Any):
        """What Cloud Tasks does: the same route, the Tasks identity's token and the task's JSON body."""
        headers = kwargs.pop("headers", None)
        if headers is None:
            headers = bearer(token or self.tasks_token)
        return self.flow.client.post(TICK, headers=headers, json=body, **kwargs)

    def deliver_new_tasks(self) -> int:
        """Delivers, in order, every task the fan-out enqueued since the last call, as Cloud Tasks would (each body
        POSTed once to the tick with the Tasks identity). Returns how many answered 200 with `{"ran": 1, ...}`.
        A refused or failed delivery is simply not counted (Cloud Tasks would retry a 5xx; a test does that itself)."""
        ran = 0
        for task in self.tasks.calls[self._delivered :]:
            self._delivered += 1
            response = self.task_call(task_payload(task))
            if response.status_code == 200 and response.json().get("ran") == 1:
                ran += 1
        return ran

    # --- records the tests put straight into the store ------------------------------------------

    def record(self, task: ApprovedTask, schedule_id: str, **over: Any) -> Schedule:
        """A schedule record snapshotting `task` as the routes would, with a chosen id (a store write, not a route)."""
        record = self.store.tasks[task.task_id]
        approach = next(a for a in record.approaches if a["id"] == task.approach_id)
        fields: dict[str, Any] = {
            "schedule_id": schedule_id, "owner_user_id": record.owner, "title": TITLE, "cadence": Cadence(**CADENCE),
            "approved_brief_ref": task.world_id, "budget_cap": float(task.cap), "enabled": True,
            "next_due": MON_0330Z, "brief": copy.deepcopy(record.brief), "approach": copy.deepcopy(approach),
            "created_at": SUNDAY,
        }  # fmt: skip
        fields.update(over)
        return Schedule(**fields)

    def insert(self, task: ApprovedTask, schedule_id: str, **over: Any) -> Schedule:
        schedule = self.record(task, schedule_id, **over)
        assert self.schedules.create(schedule, max_per_owner=1000) is True
        return schedule

    def seams(self) -> Any:
        """`runs.Seams` as the app wires them now (what the tick route hands the starter)."""
        from tilo_api import runs  # noqa: PLC0415

        seams = runs.run_seams(SimpleNamespace(app=self.app), "replay")  # type: ignore[arg-type]
        assert seams is not None, "the run seams are not wired in this rig"
        return seams

    def starter(self, **over: Any) -> Any:
        from tilo_api import schedules  # noqa: PLC0415

        kwargs = {"store": self.store, "schedules": self.schedules, "clock": self.clock}
        if "seams" not in over:  # `seams=None` is the unwired case: it must not need wired seams to be built
            kwargs["seams"] = self.seams()
        return schedules.ScheduleStarter(**{**kwargs, **over})

    # --- what a fired run left behind -----------------------------------------------------------

    def worlds_besides(self, *known: str) -> list[str]:
        return sorted(set(self.store.worlds) - set(known))

    def events(self, world_id: str, type_: str | None = None) -> list[dict[str, Any]]:
        return self.flow.events(world_id, type_)


__all__ = [
    "API_SA",
    "AUDIENCE",
    "CADENCE",
    "CAP",
    "ENV_AUDIENCE",
    "ENV_CALLER",
    "ENV_QUEUE",
    "ENV_STORE",
    "ENV_TASKS_CALLER",
    "FLOW_USER",
    "GMAIL_SA",
    "GOOGLE_ISSUER",
    "MON_0330Z",
    "OTHER_USER",
    "QUEUE",
    "SCHEDULE_SA",
    "SUNDAY",
    "TASKS_SA",
    "TICK",
    "TITLE",
    "WEEK",
    "ApprovedTask",
    "Clock",
    "FakeOidcVerifier",
    "FakeTasksClient",
    "SchedApi",
    "bearer",
    "l3_budget_policy",
    "task_body",
    "task_payload",
]
