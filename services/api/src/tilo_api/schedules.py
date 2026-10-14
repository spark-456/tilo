"""Scheduled runs on tilo-api (FR-AGT-14b; PRD 6.3, 8.6; services/api/tests/API_FR_AGT_14b.md; ADR-0023, BQ-AGT14-3).

Owner-scoped schedule routes, the scheduled-run start and the tick Cloud Scheduler calls.

- `POST /schedules` snapshots what the owner ALREADY approved: the brief, the chosen approach and the cap of the task's
  `budget.granted` event are copied from a task the principal owns; the body never carries an owner, brief, cap or
  time. Another user's schedule is the same 404 as an unknown one.
- `ScheduleStarter` is the tick's `RunStarter`. The fired run takes the normal `runs.start_run` path in a new world
  whose id and run id are a function of the slot alone (a repeated start meets the same world). Its budget comes only
  from `budget.request_budget_grant`, i.e. the owner's own L3 `grant_budget` policy: no policy, no firing (the slot is
  skipped, recorded under a fixed code, and retried next week). A person's earlier approval is never reused, so every
  T3 step of a fired run still waits for a person.
- `POST /internal/schedules/tick` is a public route of the access gate and checks its caller itself: a Google-signed
  ID token for `TILO_SCHEDULE_TICK_AUDIENCE`. Unconfigured: 503. FR-AGT-14e (BQ-AGT14-5): the caller's identity picks
  one of two modes and neither identity ever gets the other's. The Scheduler (`TILO_SCHEDULE_TICK_CALLER`, no body)
  FANS OUT: it claims each due slot and hands it to Cloud Tasks (`TILO_RUNS_QUEUE`), starting nothing, so no run
  thread lives on a request that has already returned. Cloud Tasks (`TILO_TASKS_CALLER`, the task's JSON body)
  EXECUTES ONE RUN inside its own request, where CPU is allocated, and answers once the run is done or parked at a
  person (or after `IN_REQUEST_DEADLINE_S`).
"""

from __future__ import annotations

import base64
import binascii
import copy
import dataclasses
import functools
import hashlib
import inspect
import json
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Protocol

import anyio.from_thread
import requests.exceptions as requests_errors
import tilo_planning.budget as budget
import tilo_policy
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from google.auth import exceptions as google_auth_errors
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from tilo_harness.schedule import (
    GOOGLE_ISSUERS,
    Cadence,
    OidcVerifier,
    RunStart,
    Schedule,
    StartFailed,
    StartSkipped,
    Ticker,
    next_slot,
    skipped_alert_kwargs,
    task_name,
    tick_caller_ok,
    world_requested_kwargs,
)
from tilo_harness.schedule_store import (
    SCHEDULE_ID,
    ScheduleRepository,
    ScheduleStoreNotConfigured,
    open_schedule_store,
)
from tilo_harness.writer import new_ulid
from tilo_metering.flags import FlagStore
from tilo_planning.events import build_event

from tilo_api import (
    deps,
    dev,
    ephemeral,
    events,
    followup_cleanup,
    nudge_sweep,
    plate_links,
    runs,
    store_door,
    team_access,
    team_store,
)
from tilo_api.access import Mode, enforced
from tilo_api.durable_store import DurableStore
from tilo_api.people_limits import write_limit
from tilo_api.tasks import _json_body

logger = logging.getLogger("tilo_api.schedules")
router = APIRouter()

MAX_SCHEDULES_PER_OWNER = 10
ENV_AUDIENCE, ENV_CALLER = "TILO_SCHEDULE_TICK_AUDIENCE", "TILO_SCHEDULE_TICK_CALLER"
ENV_QUEUE = "TILO_RUNS_QUEUE"  # projects/<p>/locations/<region>/queues/runs
ENV_TASKS_CALLER = "TILO_TASKS_CALLER"  # the Cloud Tasks OIDC identity (tilo-tasks-invoker@...), an exact email
# X-SCHED-1: match tilo-api's 1500 s Cloud Run timeout and leave time to answer.
DISPATCH_DEADLINE_S = 1500
IN_REQUEST_DEADLINE_S = DISPATCH_DEADLINE_S - 60
_GRANT_CONNECTOR, _GRANT_DISTRICT = "internal", "world"  # a grant uses no connector and sits in no district
_MAX_TOKEN = 8192


# --- seams ----------------------------------------------------------------------------------------------------------


@functools.cache
def _open(kind: str, project: str) -> ScheduleRepository:
    return open_schedule_store({"TILO_SCHEDULES_STORE": kind, "TILO_FIRESTORE_PROJECT": project})


def get_schedule_store() -> ScheduleRepository:
    """Memory by name, or in dev mode by default (never deployed or live); Firestore only by explicit config. Read on
    every call; a success is cached per config, a refusal never is (503 `not_configured`)."""
    kind = os.environ.get("TILO_SCHEDULES_STORE") or ""
    if not kind and dev.dev_enabled():
        try:
            dev.refuse_if_unsafe()
            kind = "memory"
        except dev.DevModeRefused:
            pass
    if kind == "memory" and enforced():  # deployed: a restart would lose every routine, so never in memory
        raise HTTPException(status_code=503, detail="not_configured")
    try:
        return _open(kind, os.environ.get("TILO_FIRESTORE_PROJECT") or "")
    except ScheduleStoreNotConfigured as exc:
        raise HTTPException(status_code=503, detail="not_configured") from exc
    except Exception as exc:  # a client that cannot be built (no credentials, no network): closed, never the text
        logger.warning("schedule store unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="not_configured") from exc


get_schedule_store.cache_clear = _open.cache_clear  # type: ignore[attr-defined]


def get_clock() -> Callable[[], datetime]:
    return lambda: datetime.now(UTC)


def get_schedule_store_factory(request: Request) -> Callable[[], ScheduleRepository]:
    """Builds nothing: the tick calls the factory only after its token passed. Honours an override of
    `get_schedule_store` the way FastAPI would (the rigs install one)."""
    return lambda: request.app.dependency_overrides.get(get_schedule_store, get_schedule_store)()


def get_seams_factory(
    request: Request, mode: Annotated[Mode, Depends(deps.get_mode)]
) -> Callable[..., runs.Seams | None]:
    """Builds nothing (about 80 ms when called): `runs.run_seams`, overrides included, for the tick to call after it.
    `demo=True` builds them for a demo session's schedule: replay, whatever the request's own mode is (BQ-SIGNIN-10)."""

    def build(demo: bool = False) -> runs.Seams | None:
        ephemeral.mark_no_person(request)  # only the tick calls this, after its OIDC check: no Firebase token to verify
        seams = runs.run_seams(request, "replay" if demo else mode)
        # a demo's schedule sends nothing (ADR-0035 L6): the tick has no person, so the seam would hand it live stubs
        return dataclasses.replace(seams, adapters={}) if demo and seams is not None else seams

    return build


def _unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The header and claims of a JWT, NOT verified: only to refuse what is plainly not a Google token."""
    parts = token.split(".")
    if len(token) > _MAX_TOKEN or len(parts) != 3:
        raise ValueError("not a JWT")
    try:
        header, claims = (json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))) for p in parts[:2])
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not a JWT") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("not a JWT")
    return header, claims


CERT_URL = "https://www.googleapis.com/oauth2/v1/certs"  # Google's public signing certificates, `{kid: x509 PEM}`
CERT_TTL_S = 900.0  # a fetched set is trusted this long, counted from the fetch (never from the last use)
CERT_FETCH_TIMEOUT_S = 3.0  # google-auth's own default is 120 s, which would hold a request thread for two minutes
CERT_RETRY_COOLDOWN_S = 10.0  # after ANY fetch attempt (cold, expired, unknown kid, failed) no other starts this soon
_REFETCH_MIN_S = 30.0  # an unknown key id inside the TTL refetches at most this often, whatever the cooldown says


class GoogleOidcVerifier:
    """google-auth's ID-token check behind the `OidcVerifier` Protocol, with a bounded and cached certificate fetch.

    A token that is not a JWT with a Google RS256 key id, issuer and our audience is refused from its own header and
    claims BEFORE any certificate fetch. Those checks only use public values, so anyone can pass them: the fetch is
    therefore single-flight and rate limited. The certificates live in one immutable snapshot, swapped whole after a
    successful fetch and read without any lock, so a known key id on a fresh snapshot never waits for a refresh. A
    refresh takes a lock with a NON-blocking acquire: a caller that finds a fetch in flight is refused at once, so at
    most one thread is ever inside a fetch. Every attempt, failed ones too, starts a cooldown of
    `CERT_RETRY_COOLDOWN_S`; an unknown key id inside the TTL also waits `_REFETCH_MIN_S` since the last fetch or
    attempt. A failed fetch stores nothing, and a snapshot older than `CERT_TTL_S` (counted from the fetch) is never
    served: a failed refresh past the TTL clears it. `transport` has google-auth's `Request` shape; `clock` (seconds)
    only ages the cache."""

    def __init__(
        self, *, transport: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._transport, self._clock = transport, clock
        self._lock = threading.Lock()  # held by the one thread inside a fetch; never waited for
        self._snapshot: tuple[dict[str, str], float] | None = None  # (certificates, fetched_at); never mutated in place
        self._tried_at = float("-inf")  # when the last fetch attempt started, whatever became of it

    def _fetch(self) -> dict[str, str]:
        if self._transport is None:
            from google.auth.transport import requests as grequests

            self._transport = grequests.Request()
        response = self._transport(CERT_URL, method="GET", timeout=CERT_FETCH_TIMEOUT_S)
        if response.status != 200:
            raise ValueError("certificate fetch failed")
        certs = json.loads(response.data)
        if (
            not isinstance(certs, dict)
            or not certs
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in certs.items())
        ):
            raise ValueError("certificate fetch returned no certificates")
        return certs

    def _usable(self, kid: str, now: float) -> dict[str, str] | None:
        """The certificates to verify with, or None when a fetch is due. Raises when the set is stale and a fetch may
        not start yet. Reads the snapshot and the attempt time once each, without the lock."""
        snapshot, tried = self._snapshot, self._tried_at
        if snapshot is not None and 0 <= now - snapshot[1] < CERT_TTL_S:
            certs, fetched = snapshot
            if kid in certs or now - max(fetched, tried) < _REFETCH_MIN_S:
                return certs  # an unknown kid this soon after an attempt is refused (by the decode), not fetched for
        if 0 <= now - tried < CERT_RETRY_COOLDOWN_S:
            raise ValueError("certificates unavailable")  # stale, cold or an unknown kid: refused, no fetch
        return None

    def _certificates(self, kid: str) -> dict[str, str]:
        now = self._clock()
        certs = self._usable(kid, now)
        if certs is not None:
            return certs
        if not self._lock.acquire(blocking=False):
            raise ValueError("certificate refresh in flight")  # fail fast: never queue behind a fetch
        try:
            now = self._clock()
            certs = self._usable(kid, now)  # a fetch that finished since the first look may have settled it
            if certs is not None:
                return certs
            self._tried_at = now
            try:
                fetched = self._fetch()
            except Exception:
                snapshot = self._snapshot
                if snapshot is None or not 0 <= now - snapshot[1] < CERT_TTL_S:
                    self._snapshot = None  # past the TTL a failed refresh never serves the old set
                raise
            self._snapshot = (fetched, now)
            return fetched
        finally:
            self._lock.release()

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        header, claims = _unverified(token)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise ValueError("not a Google-signed token")
        if claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != audience:
            raise ValueError("not a token for this service")
        from google.auth import jwt

        verified = jwt.decode(
            token, certs=self._certificates(kid), verify=True, audience=audience, clock_skew_in_seconds=10
        )
        if verified.get("iss") not in GOOGLE_ISSUERS:
            raise ValueError("not a Google-signed token")
        return verified


_verifier: GoogleOidcVerifier | None = None
_verifier_lock = threading.Lock()


def get_oidc_verifier() -> OidcVerifier:
    """ONE shared verifier, so its certificate cache lives across requests."""
    global _verifier
    with _verifier_lock:
        if _verifier is None:
            _verifier = GoogleOidcVerifier()
        return _verifier


Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Schedules = Annotated[ScheduleRepository, Depends(get_schedule_store)]
Clock = Annotated[Callable[[], datetime], Depends(get_clock)]
Flags = Annotated[FlagStore, Depends(deps.get_flag_store)]
StoreDep = Annotated[deps.Store, Depends(deps.get_store)]


def get_store_factory(request: Request) -> Callable[[], deps.Store]:
    """The request's store as the app is wired (overrides included), built only when called: the tick calls it after
    its token check, so an anonymous call opens no Firestore client and reads nothing."""

    def build() -> deps.Store:
        ephemeral.mark_no_person(request)  # called only after the tick's token check; see `ephemeral.mark_no_person`
        seam = request.app.dependency_overrides.get(deps.get_store, deps.get_store)
        return seam(request) if inspect.signature(seam).parameters else seam()

    return build


# --- the routes -----------------------------------------------------------------------------------------------------


class CadenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekday: Annotated[int, Field(strict=True, ge=0, le=6)]
    hour: Annotated[int, Field(strict=True, ge=0, le=23)]
    minute: Annotated[int, Field(strict=True, ge=0, le=59)]
    tz: Annotated[str, Field(strict=True, min_length=1, max_length=64)]

    def build(self) -> Cadence:
        try:
            return Cadence(weekday=self.weekday, hour=self.hour, minute=self.minute, tz=self.tz)
        except ValueError as exc:  # an unknown zone name
            raise HTTPException(status_code=422, detail="Pick a weekday, a time and a time zone that exists.") from exc


def _title(value: str | None) -> str | None:
    if value is not None and any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in value):
        raise ValueError("a title has no control characters")
    return value


Title = Annotated[str, Field(strict=True, min_length=1, max_length=140)]


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: Annotated[str, Field(strict=True, max_length=128)]
    approach_id: Annotated[str, Field(strict=True, max_length=128)]
    title: Title
    cadence: CadenceIn
    _plain = field_validator("title")(_title)


class PatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Annotated[bool | None, Field(strict=True)] = None
    title: Title | None = None
    cadence: CadenceIn | None = None
    _plain = field_validator("title")(_title)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else None


def _view(s: Schedule) -> dict[str, Any]:
    c = s.cadence
    return {
        "schedule_id": s.schedule_id, "title": s.title, "cadence": dataclasses.asdict(c), "enabled": s.enabled,
        "next_due": _iso(s.next_due), "budget_cap": s.budget_cap, "last_world_id": s.last_world_id,
        "last_slot": s.last_slot, "failures": s.failures, "last_error": s.last_error,
        "approved_brief_ref": s.approved_brief_ref, "created_at": _iso(s.created_at),
    }  # fmt: skip


MIN_APPROACHES, MAX_APPROACHES, MAX_APPROACH_BYTES = 2, 3, 16_384  # plan.schema.json `approaches`; one item's JSON size


def _plannable(offered: object, chosen: dict[str, Any] | None) -> bool:
    """The list a plan is compiled against: 2 to 3 bounded dicts with unique str ids, and the entry for the chosen
    approach EQUAL to it (the planner plans from the list entry). Anything odd, even a nesting too deep, is False."""
    if not isinstance(offered, list) or not MIN_APPROACHES <= len(offered) <= MAX_APPROACHES or not chosen:
        return False
    try:
        if not all(isinstance(a, dict) and isinstance(a.get("id"), str) for a in offered):
            return False
        ids = [a["id"] for a in offered]
        if len(set(ids)) != len(ids) or chosen.get("id") not in ids:
            return False
        if offered[ids.index(chosen["id"])] != chosen:
            return False
        return all(
            len(json.dumps(a, default=str, ensure_ascii=False).encode("utf-8")) <= MAX_APPROACH_BYTES for a in offered
        )
    except (RecursionError, TypeError, ValueError):
        return False


def _mine(schedules: ScheduleRepository, schedule_id: str, principal: deps.Principal) -> Schedule:
    found = schedules.get(schedule_id)
    if found is None or found.owner_user_id != principal.user_id:  # no oracle for another user's schedule
        raise HTTPException(status_code=404, detail="No such schedule.")
    return found


@router.post("/schedules", status_code=201)
def create_schedule(
    principal: Principal,
    body: Annotated[CreateIn, Depends(_json_body(CreateIn))],
    store: StoreDep,
    schedules: Schedules,
    clock: Clock,
    flags: Flags,
) -> dict[str, Any]:
    if principal.demo_session:  # DEMO-EPHEMERAL-1: a demo stores nothing durable, and a schedule outlives the session
        raise HTTPException(status_code=403, detail="demo_schedules_unavailable")
    task = store.load_task(body.task_id, settle=False)  # not yet known to be this owner's
    if task is None or task.owner != principal.user_id:  # unknown and another user's task answer alike
        raise HTTPException(status_code=404, detail="No such task.")
    deps.refuse_if_replay_only(flags)  # NFR-24: after sign-in and the owner check
    with task.lock:
        approach = next(
            (a for a in task.approaches or [] if isinstance(a, dict) and a.get("id") == body.approach_id), None
        )
        grants = [e for e in store.events.get(task.world_id, []) if e["type"] == "budget.granted"]
        if not task.granted or not grants:
            raise HTTPException(status_code=409, detail="Approve this task's budget first.")
        if approach is None:
            raise HTTPException(status_code=422, detail="Pick one of the approaches this task was offered.")
        if not _plannable(task.approaches, approach):  # before any copy: a hostile nesting must not reach deepcopy
            raise HTTPException(status_code=409, detail="This task's approaches cannot be scheduled.")
        offered = copy.deepcopy(task.approaches)
        brief, approach, cap = copy.deepcopy(task.brief), copy.deepcopy(approach), grants[0]["data"]["cap"]
    cadence, now = body.cadence.build(), clock()
    try:
        record = Schedule(
            schedule_id="sched_" + secrets.token_hex(12), owner_user_id=principal.user_id, title=body.title,
            cadence=cadence, approved_brief_ref=task.world_id, budget_cap=float(cap), next_due=next_slot(cadence, now),
            brief=brief, approach=approach, approaches=offered, created_at=now, demo=principal.demo_session,
        )  # fmt: skip
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="This task's budget cannot be scheduled.") from exc
    if not schedules.create(record, max_per_owner=MAX_SCHEDULES_PER_OWNER):
        raise HTTPException(status_code=409, detail="You already have the most schedules allowed.")
    return _view(record)


@router.get("/schedules")
def list_schedules(principal: Principal, schedules: Schedules) -> dict[str, Any]:
    return {"schedules": [_view(s) for s in schedules.list_for_owner(principal.user_id)]}


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: str, principal: Principal, schedules: Schedules) -> dict[str, Any]:
    return _view(_mine(schedules, schedule_id, principal))


@router.patch("/schedules/{schedule_id}", dependencies=[Depends(write_limit)])
def update_schedule(
    schedule_id: str,
    principal: Principal,
    body: Annotated[PatchIn, Depends(_json_body(PatchIn))],
    schedules: Schedules,
    clock: Clock,
    flags: Flags,
) -> dict[str, Any]:
    if principal.demo_session:  # DEMO-EPHEMERAL-1: a demo's schedule is never edited or re-enabled
        raise HTTPException(status_code=403, detail="demo_schedules_unavailable")
    current = _mine(schedules, schedule_id, principal)
    deps.refuse_if_replay_only(flags)
    cadence = body.cadence.build() if body.cadence is not None else None
    moved = cadence is not None and cadence != current.cadence  # the next slot follows a changed cadence only
    next_due = next_slot(cadence, clock()) if cadence is not None and moved else None
    updated = schedules.update(
        schedule_id, enabled=body.enabled, title=body.title, cadence=cadence if moved else None, next_due=next_due
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="No such schedule.")
    return _view(updated)


@router.delete("/schedules/{schedule_id}", status_code=204, dependencies=[Depends(write_limit)])
def delete_schedule(schedule_id: str, principal: Principal, schedules: Schedules, flags: Flags) -> Response:
    _mine(schedules, schedule_id, principal)
    deps.refuse_if_replay_only(flags)
    if not schedules.delete(schedule_id):
        raise HTTPException(status_code=404, detail="No such schedule.")
    return Response(status_code=204)


# --- the scheduled-run start ------------------------------------------------------------------------------------------


def _stamp(at: datetime) -> str:
    """common.schema.json's timestamp: UTC, exactly three fractional digits, from the injected clock."""
    at = at.astimezone(UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class _Reader:
    read: Callable[[], Any]


class ScheduleStarter:
    """The tick's `RunStarter`: reads the stored snapshot, never what it is handed over it (design decisions 3, 4)."""

    def __init__(
        self,
        *,
        store: deps.Store,
        schedules: ScheduleRepository,
        seams: runs.Seams | None,
        clock: Callable[[], datetime],
        team: Any = None,  # anything with `read() -> TeamState | None`
    ) -> None:
        self._store, self._schedules, self._seams, self._clock = store, schedules, seams, clock
        self._team = team  # FR-TEAM-04's weekend switch; None: no team store wired, as before

    def start(self, run: RunStart) -> str:
        record = self._schedules.get(run.schedule_id)
        if record is None:
            raise StartSkipped("schedule_missing")
        if run.owner_user_id != record.owner_user_id:
            raise StartSkipped("owner_mismatch")
        if record.brief is None or record.approach is None:
            raise StartSkipped("snapshot_missing")
        if not _plannable(record.approaches, record.approach):  # before any world or grant: nothing to orphan
            raise StartSkipped("snapshot_incomplete")
        if not record.enabled:  # claimed just before `disable_for_owner` or a pause: read again here, after the claim
            raise StartSkipped("schedule_disabled", count=False)
        team = self._team.read() if self._team is not None else None  # unreadable raises: no start (fail closed)
        if team_access.weekend_hold(team, self._clock(), record.cadence.tz):
            raise StartSkipped("weekend_hold", count=False)  # held, never counted against the schedule (BQ-TEAMRT-3)
        if self._seams is None:
            raise StartSkipped("run_seams_unwired", count=False)  # the whole service, not this schedule: not counted
        world_id, run_id = slot_ids(run.idempotency_key)
        owner, store = record.owner_user_id, self._store
        with store.grant_lock(owner):  # one owner's grants at a time: daily limits count every earlier grant
            # the earlier grants, the policies and the history a run reads: all of the owner's
            store.load_owner(owner, settle=True)
            existing = store.load_world(world_id, settle=False)  # its owner is checked below; :442 settled theirs
            if existing is None:
                self._create_world(run, record, world_id, run_id)
            elif existing.owner != owner:
                raise StartSkipped("owner_mismatch")
            elif isinstance(store, DurableStore):  # a retry: the events an earlier attempt queued go first, by id
                store.drain(world_id, self._seams.writer)
        task = deps.TaskRecord(
            owner, world_id, run_id, copy.deepcopy(record.brief), copy.deepcopy(record.brief), [], 3,
            approaches=copy.deepcopy(record.approaches), granted=True,
        )  # fmt: skip
        # start_run keeps one run per world, so a repeat (or a retry after a failed start) starts nothing twice
        runs.start_run(store, task, approach=record.approach, budget_cap=record.budget_cap, seams=self._seams)
        return world_id

    def _create_world(self, run: RunStart, record: Schedule, world_id: str, run_id: str) -> None:
        """world.requested, then the budget grant by the owner's own policy; stored only if the grant ran."""
        store, owner, stamp = self._store, record.owner_user_id, _stamp(self._clock())
        base = {"v": "1.0", "ts": stamp, "world_id": world_id, "run_id": run_id, "actor": owner}
        # the earlier grants and the policies are read across all of the owner's worlds
        store.load_owner(owner, settle=True)
        owned = {w for w, r in store.worlds.items() if r.owner == owner}
        earlier = [e for w in owned for e in store.events.get(w, []) if e.get("type") == "budget.granted"]
        outcome = budget.request_budget_grant(
            record.budget_cap, table=tilo_policy.load_risk_table(), policies=list(store.policies.values()),
            world_owner=owner, earlier_grants=earlier, now=stamp, base=base, seq=2, connector=_GRANT_CONNECTOR,
            district=_GRANT_DISTRICT,
        )  # fmt: skip
        if outcome.granted_event is None:  # no covering L3 policy: never a person's earlier approval, never a model
            raise StartSkipped("budget_not_granted", advance=True)
        fields = world_requested_kwargs(dataclasses.replace(run, title=record.title), world_id)
        requested = build_event(base, seq=1, item=None, severity="info", tool=None, cause=None, **fields)
        assert self._seams is not None  # `start` returned before this without the run seams
        world = deps.WorldRecord(owner=owner, districts={}, run_id=run_id, prior_world_id=run.prior_world_id)
        try:  # the world and its two events in one save, through the single writer (ADR-0026 decisions 3, 4)
            store.save(
                self._seams.writer, worlds={world_id: world}, parts={world_id: [requested, outcome.granted_event]},
                create=[("worlds", world_id)],
            )  # fmt: skip
        except HTTPException as exc:
            if (
                exc.status_code == 409 and exc.detail == "the event was refused"
            ):  # a fixed code, never the validator's text
                raise StartSkipped("event_refused") from None
            raise


def slot_ids(key: str) -> tuple[str, str]:
    """The world id and run id of a slot: a function of its key alone, so the tick's hand-over (`TaskEnqueuer`) and the
    start (`ScheduleStarter`) name the same world, and a repeated start meets it."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
    return f"w_s{digest}", f"r_s{digest}"


# --- Cloud Tasks: the fan-out's side ----------------------------------------------------------------------------------

TASKS_API = "https://cloudtasks.googleapis.com/v2"
TASKS_TIMEOUT_S = 10.0  # one enqueue call; google-auth's own default is 120 s, which would hold a tick that long
TICK_PATH = "/internal/schedules/tick"
MAX_SKIPPED = 99_999  # a task's `skipped`: bounds-checked, only a count in an info alert (not the SEC-16 cap literal)
_MAX_BODY = 4096  # bytes of request body read (a task's body is about 300)
_QUEUE = re.compile(r"^projects/[^/\s]+/locations/[^/\s]+/queues/[^/\s]+$")
_WORLD_ID = re.compile(r"^w_[0-9A-Za-z_]{1,48}$")  # contracts/common.schema.json world_id; use with fullmatch
_TASKS_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True)
class AlreadyExists:
    """What a `TasksClient` returns for Cloud Tasks' ALREADY_EXISTS (a task name used within its reuse window)."""


class TasksClient(Protocol):
    def enqueue(self, task: Mapping[str, Any]) -> None | AlreadyExists:
        """Creates the task in the queue its name carries. Raises on any failure other than ALREADY_EXISTS."""
        ...


class TasksError(StartFailed):
    """Cloud Tasks refused an enqueue. Carries the status only (`status`, an int when Cloud Tasks answered): never the
    request, the response or a credential. A 429 or a 5xx may be the whole service's: two alike as the first two calls
    of a tick stop it as `tasks_quota` or `tasks_server` (BQ-AGT14-8)."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message, status=status, pair=_pair(status))


def _pair(status: int | None) -> str | None:
    if type(status) is not int:
        return None
    return "tasks_quota" if status == 429 else "tasks_server" if 500 <= status <= 599 else None


class TasksUnavailable(TasksError):
    """A refusal that is the service's, not one schedule's (401, 403, 404: wrong caller, missing actAs, no queue): the
    fan-out records nothing against any schedule for it, and the first one ends the tick with a 503 (BQ-AGT14-6)."""


_SERVICE_WIDE = frozenset({401, 403, 404})
# FR-AGT-14g (BQ-AGT14-7): raised by any TasksClient's enqueue, these are outages of the whole service, stopped like
# `tasks_unavailable`. The raised type decides, in this order: a RefreshError wrapping a transport error is credential.
_TRANSPORT_ERRORS = (google_auth_errors.TransportError, requests_errors.Timeout, requests_errors.ConnectionError)
_OUTAGES: tuple[tuple[tuple[type[Exception], ...], str], ...] = (
    ((google_auth_errors.RefreshError,), "tasks_credential"),
    (_TRANSPORT_ERRORS, "tasks_transport"),
)


def _error_status(response: Any) -> str | None:
    """The google.rpc status name of an error answer ("ALREADY_EXISTS"), or None; never raises, never the text."""
    try:
        status = response.json()["error"]["status"]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return status if isinstance(status, str) else None


class CloudTasksRestClient:
    """The Cloud Tasks REST API (`POST /v2/{queue}/tasks`) through google-auth's `AuthorizedSession`: no extra client
    library. Built only after a caller's token passed (credentials are looked up here, once per request). The body of
    the task and the token are never logged. `session` has the `requests.Session` shape (tests inject one)."""

    def __init__(self, *, session: Any = None, timeout_s: float = TASKS_TIMEOUT_S) -> None:
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _project = google.auth.default(scopes=[_TASKS_SCOPE])
            session = AuthorizedSession(credentials)
        self._session, self._timeout_s = session, timeout_s

    def enqueue(self, task: Mapping[str, Any]) -> None | AlreadyExists:
        queue = str(task["name"]).rpartition("/tasks/")[0]
        response = self._session.post(
            f"{TASKS_API}/{queue}/tasks", json={"task": dict(task)}, timeout=self._timeout_s,
            max_allowed_time=self._timeout_s,
        )  # fmt: skip
        status = response.status_code
        if status == 409 and _error_status(response) == "ALREADY_EXISTS":  # ABORTED is a 409 too: that one is a failure
            return AlreadyExists()
        if status in _SERVICE_WIDE:
            raise TasksUnavailable(f"cloud tasks answered {status}", status=status)
        if not 200 <= status < 300:
            raise TasksError(f"cloud tasks answered {status}", status=status)
        return None


def get_tasks_client_factory() -> Callable[[], TasksClient]:
    """Builds nothing: the fan-out calls the factory only after its token passed, once per request."""
    return CloudTasksRestClient


class TaskEnqueuer:
    """The tick's `RunStarter` in fan-out: hands ONE slot to Cloud Tasks and returns the slot's world id (the same
    derivation `ScheduleStarter` uses, so the schedule records the world the delivery will make). It makes no world and
    no event. The task carries the slot and two facts of this firing, never a brief, owner, cap or secret: the delivery
    reads those from the schedule's own record. ALREADY_EXISTS is a success; any other failure raises, as a
    stopping `StartSkipped` when the whole service's (`tasks_unavailable`, `tasks_credential`, `tasks_transport`)."""

    def __init__(self, *, client: TasksClient, queue: str, audience: str, caller: str) -> None:
        self._client, self._queue, self._audience, self._caller = client, queue, audience, caller

    def start(self, run: RunStart) -> str:
        world_id, _run_id = slot_ids(run.idempotency_key)
        prior = run.prior_world_id if run.prior_world_id and _WORLD_ID.fullmatch(run.prior_world_id) else None
        body = {
            "schedule_id": run.schedule_id, "slot": run.idempotency_key, "due": run.slot.astimezone(UTC).isoformat(),
            "skipped": max(0, min(run.skipped, MAX_SKIPPED)), "prior_world_id": prior,
        }  # fmt: skip
        task = {
            "name": f"{self._queue}/tasks/{task_name(run.idempotency_key)}",
            "dispatchDeadline": f"{DISPATCH_DEADLINE_S}s",
            "httpRequest": {
                "httpMethod": "POST",
                "url": self._audience.rstrip("/") + TICK_PATH,
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8")).decode("ascii"),
                "oidcToken": {"serviceAccountEmail": self._caller, "audience": self._audience},
            },
        }  # no retry config (the queue owns it) and no Authorization header (the OIDC token is Cloud Tasks' own)
        try:
            self._client.enqueue(task)  # None or AlreadyExists: handed over either way
        except TasksUnavailable as exc:  # the whole service's setting: nothing is recorded, and the tick stops here
            status = exc.status if type(exc.status) is int else None
            raise StartSkipped("tasks_unavailable", count=False, stop=True, status=status) from exc
        except Exception as exc:
            code = next((code for kinds, code in _OUTAGES if isinstance(exc, kinds)), None)
            if code is None:  # this schedule's failure, counted; the Ticker pairs two alike first 429/5xx (BQ-AGT14-8)
                raise
            raise StartSkipped(code, count=False, stop=True) from exc
        return world_id


# --- Cloud Tasks: a delivery's side -----------------------------------------------------------------------------------


class TaskRunIn(BaseModel):
    """What the fan-out wrote into a task. Closed and strict, and untrusted: the owner, brief, approach, cap and world
    always come from the schedule's own record. `skipped` and `prior_world_id` are server-written facts of the firing,
    taken as data within their bounds: a count for an info alert, and a world offered only if the owner has it."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schedule_id: str
    slot: str
    due: str
    skipped: Annotated[int, Field(strict=True, ge=0, le=MAX_SKIPPED)] = 0
    prior_world_id: str | None = None

    @field_validator("schedule_id")
    @classmethod
    def _schedule_id(cls, value: str) -> str:
        if not SCHEDULE_ID.fullmatch(value):
            raise ValueError("not a schedule id")
        return value

    @field_validator("prior_world_id")
    @classmethod
    def _prior(cls, value: str | None) -> str | None:
        if value is not None and not _WORLD_ID.fullmatch(value):
            raise ValueError("not a world id")
        return value

    @model_validator(mode="after")
    def _the_slot_is_this_schedules_own(self) -> TaskRunIn:
        """`due` is one UTC-aware instant spelled as `slot_key` spells it, and `slot` is exactly that schedule's key."""
        try:
            due = datetime.fromisoformat(self.due)
            if due.tzinfo is None or due.utcoffset() is None:
                raise ValueError("due is not timezone-aware")
            spelled = due.astimezone(UTC).isoformat()
        except (ValueError, OverflowError) as exc:  # OverflowError: an offset pushes the instant out of range
            raise ValueError("due is not an instant") from exc
        if self.due != spelled or self.slot != f"{self.schedule_id}:{spelled}":
            raise ValueError("the slot is not this schedule's slot key")
        return self

    def due_at(self) -> datetime:
        return datetime.fromisoformat(self.due)


# the starter's own codes that no retry can change: a 2xx, so Cloud Tasks does not retry (run_seams_unwired is a 5xx)
_REFUSALS = frozenset(
    {
        "schedule_missing",
        "schedule_disabled",
        "owner_mismatch",
        "budget_not_granted",
        "snapshot_missing",
        "snapshot_incomplete",
    }
)
_RECORDED = frozenset(
    {"owner_mismatch", "budget_not_granted", "snapshot_missing", "snapshot_incomplete"}
)  # not a missing or disabled one
_CLOCK_SLACK = timedelta(seconds=60)  # a slot this far ahead is the clocks of two instances, not a forged future
_ALERTS = threading.Lock()  # one instance's duplicate deliveries raise the missed-slots alert once


def _tasks_config() -> tuple[str, str]:
    """(`TILO_TASKS_CALLER`, `TILO_RUNS_QUEUE`), read per request; an empty string is unset."""
    return os.environ.get(ENV_TASKS_CALLER) or "", os.environ.get(ENV_QUEUE) or ""


def _raise_skipped_alert(seams: runs.Seams, store: deps.Store, world_id: str, skipped: int, now: datetime) -> None:
    """BQ-AGT14-5 R2: the info `alert.raised` that tells the owner how many missed runs were collapsed, after
    `world.requested`, once per world (a duplicate delivery finds it). Its failure never undoes the run."""
    fields = skipped_alert_kwargs(world_id, skipped, new_ulid(now))
    try:
        with _ALERTS:
            stream = store.events.get(world_id, [])
            if any(e.get("type") == "alert.raised" and e.get("summary") == fields["summary"] for e in stream):
                return
            part = {"id": events.new_part_id(), "level": None, "district": None, "item": None, "credits": 0}
            seams.writer.append(world_id, {**part, "cause": None, "vis": "all", "authz": None, **fields})
    except Exception as exc:
        logger.warning("skipped-run alert failed (%s)", type(exc).__name__)


# --- the tick -------------------------------------------------------------------------------------------------------


def _tick_config() -> tuple[str, str]:
    audience, caller = os.environ.get(ENV_AUDIENCE) or "", os.environ.get(ENV_CALLER) or ""
    if not audience or not caller:
        raise HTTPException(
            status_code=503, detail="not_configured"
        )  # the production default, before any token is read
    return audience, caller


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token and not any(c.isspace() for c in token) else None


async def _read_body(request: Request) -> bytes | None:
    """The request body, or None when it is longer than `_MAX_BODY` (never read past that)."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _closed(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


@router.post("/internal/schedules/tick")
def tick(
    request: Request,
    config: Annotated[tuple[str, str], Depends(_tick_config)],
    tasks_config: Annotated[tuple[str, str], Depends(_tasks_config)],
    schedule_store: Annotated[Callable[[], ScheduleRepository], Depends(get_schedule_store_factory)],
    seams_factory: Annotated[Callable[..., runs.Seams | None], Depends(get_seams_factory)],
    tasks_client: Annotated[Callable[[], TasksClient], Depends(get_tasks_client_factory)],
    verifier: Annotated[OidcVerifier, Depends(get_oidc_verifier)],
    clock: Clock,
    flags: Flags,
    store_factory: Annotated[Callable[[], deps.Store], Depends(get_store_factory)],
) -> Any:
    """ONE route for two callers (BQ-AGT14-5): the verified identity picks the mode, and an identity never gets the
    other's. The schedule store, the Tasks client and the run seams are built only after the token passed (an anonymous
    call costs none), once per request, and only by the mode that needs them."""
    audience, scheduler = config
    tasks_caller, queue = tasks_config
    token = _bearer(request)
    if token is None:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = verifier.verify(token, audience)
        valid = isinstance(claims, Mapping)
        as_scheduler = valid and tick_caller_ok(claims, audience=audience, caller=scheduler)
        as_tasks = valid and bool(tasks_caller) and tick_caller_ok(claims, audience=audience, caller=tasks_caller)
    except Exception as exc:  # bad signature, expiry, audience or a verifier outage: not an accepted caller
        logger.warning("schedule tick token refused (%s)", type(exc).__name__)  # the type only: no text, no traceback
        return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    if not (as_scheduler or as_tasks):
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    if as_scheduler and as_tasks:  # one account for both modes: the identity cannot pick one, so it gets neither
        return _closed(503, "not_configured")
    if not tasks_caller or not _QUEUE.fullmatch(queue):  # nothing runs inline any more: fail closed, nothing claimed
        return _closed(503, "not_configured")
    raw = anyio.from_thread.run(_read_body, request)
    if raw is None:
        return _closed(413, "Too large.")
    if as_scheduler:
        if raw:  # the Scheduler sends no body: a task's body from it is the other mode's, refused with no side effect
            return _closed(422, "This caller sends no body.")
        answer = _fan_out(
            schedule_store, tasks_client, clock, flags, audience=audience, caller=tasks_caller, queue=queue
        )
        nudge_sweep.sweep(request, _stamp(clock()))  # FR-PA-15b: off unless TILO_NUDGES=1; the answer never changes
        followup_cleanup.sweep(clock)
        _sweep_outbox(request, clock, store_factory)
        _sweep_push(request, clock, store_factory)
        _sweep_spend(request, clock)
        plate_links.sweep(
            request, _stamp(clock())
        )  # FR-PA-06b: off unless TILO_PLATE_DIGEST=1; never changes the answer
        return answer
    return _run_task(request, raw, schedule_store, seams_factory, clock, flags, store_factory)


def _sweep_outbox(request: Request, clock: Callable[[], datetime], store_factory: Callable[[], deps.Store]) -> None:
    """ADR-0035 LC-12: the Scheduler's tick also dispatches the durable outbox's due entries, so a dead instance's entry
    goes out within one tick. Only for `TILO_OUTBOX_STORE=firestore`; best effort: whatever fails is logged by type and
    the tick's own answer is unchanged. A world that cannot be read is treated as paused."""
    if os.environ.get("TILO_OUTBOX_STORE") != "firestore":
        return
    from tilo_api.outbox_firestore import sweep_due  # noqa: PLC0415

    overrides = request.app.dependency_overrides

    opened: list[deps.Store] = []

    def paused(world_id: str) -> bool:
        try:
            if not opened:
                opened.append(store_factory())
            world = opened[0].load_world(world_id)
        except Exception:
            return True
        return world is None or world.paused

    def source_valid(entry: dict) -> bool:
        from tilo_api.followup_outbox_sources import source_valid as valid  # noqa: PLC0415

        if not opened:
            opened.append(store_factory())
        world = opened[0].load_world(entry["world_id"], settle=False)
        if not entry["idempotency_key"].startswith("autopilot:"):
            return world is not None
        people = overrides.get(deps.get_people_stores, deps.get_people_stores)()
        client = store_door.open_api_store().client
        return valid(entry, world, people, client, deps.ORG_ID, clock().timestamp())

    try:
        store = overrides.get(deps.get_outbox_store, deps.get_outbox_store)()
        adapters = overrides.get(deps.get_connector_adapters, deps.get_connector_adapters)()
        sweep_due(store, adapters, lambda: _stamp(clock()), paused, source_valid=source_valid)
    except Exception as exc:
        logger.error("outbox sweep failed (%s)", type(exc).__name__)


_sweep_spend_503_logged = False


def _sweep_spend(request: Request, clock: Callable[[], datetime]) -> None:
    """ADR-0042 MV-17(b): the Scheduler's tick also settles the SEC-16 ledger's expired `held` holds at their own amount
    (the count is unchanged, only the status closes). Best effort like the sweeps around it: a ledger with no such
    method (the in-memory one) or any failure is logged by type and never changes the tick's own answer."""
    try:
        ledger = request.app.dependency_overrides.get(deps.get_spend_cap_ledger, deps.get_spend_cap_ledger)()
        if (settle_expired := getattr(ledger, "settle_expired", None)) is not None:
            settle_expired(clock())
    except HTTPException as exc:
        # no ledger wired (503): nothing to sweep, so one line for the process, not one per tick
        global _sweep_spend_503_logged
        if not _sweep_spend_503_logged:
            _sweep_spend_503_logged = True
            logger.warning("spend hold sweep skipped: no spend ledger (%s), logged once", exc.status_code)
    except Exception as exc:
        logger.warning("spend hold sweep failed (%s)", type(exc).__name__)


def _sweep_push(request: Request, clock: Callable[[], datetime], store_factory: Callable[[], deps.Store]) -> None:
    """FR-CHN-17f: the Scheduler's tick also pushes new gate cards to the people who turned push on (`push_feed`),
    best effort like the outbox sweep: whatever fails is logged by type and the tick's own answer is unchanged.
    Nothing happens while `TILO_CHANNELS_URL` is unset, or while the outbox store is a process's own in-memory one
    (the feed's "nothing twice" is the stored idempotency key; a restart or a second instance would send again)."""
    overrides = request.app.dependency_overrides

    def get(dep: Callable[..., Any]) -> Any:
        return overrides.get(dep, dep)()

    try:
        rpc = get(deps.get_push_rpc)
        if rpc is None:
            return
        from tilo_connectors import InMemoryOutboxStore  # noqa: PLC0415
        from tilo_connectors.errors import SideEffectRefused  # noqa: PLC0415

        from tilo_api import push_feed  # noqa: PLC0415
        from tilo_api.push_send import PushRpcAdapter  # noqa: PLC0415

        outbox_store = get(deps.get_outbox_store)  # the one the outbox sweep and the service configure
        if isinstance(outbox_store, InMemoryOutboxStore):
            return  # fail closed: not durable
        subs = get(deps.get_push_store)
        store = store_factory()

        def paused(world_id: str) -> bool:
            try:
                world = store.load_world(world_id)
            except Exception:
                return True
            return world is None or world.paused

        push_feed.sweep(
            subs=subs, store=store, outbox_store=outbox_store,
            adapter=PushRpcAdapter(subscriptions=subs, rpc=rpc, final_error=SideEffectRefused),
            people=get(deps.get_people_stores), writer=get(deps.get_event_writer), clock=clock, paused=paused,
        )  # fmt: skip
    except Exception as exc:
        logger.error("push sweep failed (%s)", type(exc).__name__)


def _fan_out(
    schedule_store: Callable[[], ScheduleRepository],
    tasks_client: Callable[[], TasksClient],
    clock: Callable[[], datetime],
    flags: FlagStore,
    *,
    audience: str,
    caller: str,
    queue: str,
) -> Any:
    """The Scheduler's call: claim each due slot and hand it to Cloud Tasks. Starts nothing and writes to no world."""
    try:
        schedules = schedule_store()
        client = tasks_client()
    except HTTPException as exc:  # no store configured: closed, with the fixed code the routes use
        return _closed(exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.error("schedule tick could not be set up (%s)", type(exc).__name__)
        return _closed(500, "tick failed")
    enqueuer = TaskEnqueuer(client=client, queue=queue, audience=audience, caller=caller)
    try:
        ticker = Ticker(
            store=schedules, starter=enqueuer, flags=flags, clock=clock, alerts=lambda _world, _fields: None
        )
        result = ticker.tick()
    except Exception as exc:  # fail closed with a fixed body; Scheduler retries and the next tick re-reads the store
        logger.error("schedule tick failed (%s)", type(exc).__name__)
        return _closed(500, "tick failed")
    if result.stopped is not None:  # BQ-AGT14-6: a service-wide refusal is a failed attempt, whatever fired before it
        extra = {"event": "schedule_tick_stopped", "status": result.status, "code": result.stopped}  # BQ-AGT14-8 (b)
        if result.status is None:
            logger.error(
                "schedule tick stopped (%s); %d fired, the rest stay due", result.stopped, result.fired, extra=extra
            )
        else:
            logger.error(
                "schedule tick stopped (%s, status %d); %d fired, the rest stay due",
                result.stopped, result.status, result.fired, extra=extra,
            )  # fmt: skip
        return _closed(503, result.stopped)
    return {"fired": result.fired}


def _run_task(
    request: Request,
    raw: bytes,
    schedule_store: Callable[[], ScheduleRepository],
    seams_factory: Callable[..., runs.Seams | None],
    clock: Callable[[], datetime],
    flags: FlagStore,
    store_factory: Callable[[], deps.Store],
) -> Any:
    """Cloud Tasks' call: execute ONE run for the slot the body names, inside this request, then answer once the run is
    done or parked at a person (or at the deadline). The record, never the body, says whose run it is."""
    if not raw:
        return _closed(422, "A task body is required.")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return _closed(415, "Send application/json.")
    try:
        body = TaskRunIn.model_validate_json(raw)
    except ValidationError:  # never the input, never its errors: the body is untrusted
        return _closed(422, "Invalid task.")
    deps.refuse_if_replay_only(flags)  # NFR-24: 503, so Cloud Tasks retries once the flag is clear
    try:
        schedules = schedule_store()
        store = store_factory()  # the durable store opens here, after the token: an anonymous call costs no client
    except HTTPException as exc:
        return _closed(exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.error("schedule task could not be set up (%s)", type(exc).__name__)
        return _closed(500, "tick failed")

    def refused(code: str) -> dict[str, Any]:  # a 2xx, so Cloud Tasks does not retry it
        return {"ran": 0, "skipped": code}

    due, record = body.due_at(), schedules.get(body.schedule_id)
    demo = record is not None and record.demo  # the tick has no signed-in person: the record says if it was a demo's
    try:  # built once, after the record (BQ-SIGNIN-10: a demo's replays)
        seams = seams_factory(demo=True) if demo else seams_factory()
    except HTTPException as exc:
        return _closed(exc.status_code, str(exc.detail))
    except Exception as exc:
        logger.error("schedule task could not be set up (%s)", type(exc).__name__)
        return _closed(500, "tick failed")
    if record is None:
        return refused("schedule_missing")
    if due > clock() + _CLOCK_SLACK:
        return refused("slot_not_due")
    try:
        on_cadence = next_slot(record.cadence, due - timedelta(microseconds=1)) == due
    except OverflowError:  # an instant at the edge of the calendar is no slot of any cadence
        on_cadence = False
    if not on_cadence:
        return refused("slot_off_cadence")
    world_id, _run_id = slot_ids(body.slot)
    prior = store.worlds.get(body.prior_world_id) if body.prior_world_id else None
    offered = body.prior_world_id if prior is not None and prior.owner == record.owner_user_id else None
    run = RunStart(
        idempotency_key=body.slot, schedule_id=record.schedule_id, owner_user_id=record.owner_user_id,
        title=record.title, approved_brief_ref=record.approved_brief_ref,
        prior_world_id=offered if offered != world_id else None, budget_cap=record.budget_cap, slot=due,
        skipped=body.skipped, cache_namespace=record.schedule_id,
    )  # fmt: skip
    team = team_store.team_reader(request.app.dependency_overrides)
    starter = ScheduleStarter(store=store, schedules=schedules, seams=seams, clock=clock, team=_Reader(team))
    try:
        started = starter.start(run)
    except StartSkipped as skip:
        if skip.code not in _REFUSALS:  # e.g. the run seams are unwired: the whole service, so Cloud Tasks retries
            logger.warning("schedule task not started (%s)", skip.code)
            return _closed(503, "run could not start")
        if skip.code in _RECORDED:
            try:
                schedules.record_refusal(record.schedule_id, skip.code)
            except Exception as exc:  # the answer stands; the code is only the owner's hint
                logger.warning("schedule refusal not recorded (%s)", type(exc).__name__)
        return refused(skip.code)
    except (
        Exception
    ) as exc:  # anything from the start: a fixed 5xx; the ids are deterministic, so a retry meets this world
        logger.warning("schedule task failed to start (%s)", type(exc).__name__)
        return _closed(500, "run could not start")
    if body.skipped > 0 and seams is not None:
        _raise_skipped_alert(seams, store, started, body.skipped, clock())
    run_of = store.runs.get(started)
    state = run_of.wait_until_parked_or_done(IN_REQUEST_DEADLINE_S) if run_of is not None else "done"
    return {"ran": 1, "state": state}
