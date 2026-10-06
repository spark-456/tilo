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
  ID token for `TILO_SCHEDULE_TICK_AUDIENCE` from the one service account in `TILO_SCHEDULE_TICK_CALLER`.
  Unconfigured: 503.
"""

from __future__ import annotations

import base64
import binascii
import copy
import dataclasses
import functools
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

import tilo_planning.budget as budget
import tilo_policy
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from tilo_harness.schedule import (
    GOOGLE_ISSUERS,
    Cadence,
    OidcVerifier,
    RunStart,
    Schedule,
    StartSkipped,
    Ticker,
    next_slot,
    tick_caller_ok,
    world_requested_kwargs,
)
from tilo_harness.schedule_store import ScheduleRepository, ScheduleStoreNotConfigured, open_schedule_store
from tilo_metering.flags import FlagStore
from tilo_planning.events import build_event

from tilo_api import deps, dev, events, runs
from tilo_api.access import Mode
from tilo_api.tasks import _json_body

logger = logging.getLogger("tilo_api.schedules")
router = APIRouter()

MAX_SCHEDULES_PER_OWNER = 10
ENV_AUDIENCE, ENV_CALLER = "TILO_SCHEDULE_TICK_AUDIENCE", "TILO_SCHEDULE_TICK_CALLER"
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
) -> Callable[[], runs.Seams | None]:
    """Builds nothing (about 80 ms when called): `runs.run_seams`, overrides included, for the tick to call after it."""
    return lambda: runs.run_seams(request, mode)


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
_REFETCH_MIN_S = 30.0  # an unknown key id inside the TTL refetches at most this often (junk tokens cannot force more)


class GoogleOidcVerifier:
    """google-auth's ID-token check behind the `OidcVerifier` Protocol, with a bounded and cached certificate fetch.

    A token that is not a JWT with a Google RS256 key id, issuer and our audience is refused from its own header and
    claims BEFORE any certificate fetch. The certificates are fetched with a timeout of `CERT_FETCH_TIMEOUT_S` and
    reused for `CERT_TTL_S` from the fetch. A failed fetch stores nothing and a failed refresh never serves older
    certificates past the TTL. `transport` has google-auth's `Request` shape; `clock` (seconds) only ages the cache."""

    def __init__(
        self, *, transport: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._transport, self._clock = transport, clock
        self._lock = threading.Lock()  # one fetch at a time; a caller that waited re-reads the cache first
        self._certs: dict[str, str] = {}
        self._fetched_at: float | None = None
        self._tried_at = float("-inf")  # the last refresh attempt for an unknown kid inside the TTL

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

    def _certificates(self, kid: str) -> dict[str, str]:
        with self._lock:
            now, fetched = self._clock(), self._fetched_at
            fresh = fetched is not None and 0 <= now - fetched < CERT_TTL_S
            if fresh and fetched is not None:
                if kid in self._certs or now - max(fetched, self._tried_at) < _REFETCH_MIN_S:
                    return self._certs  # an unknown kid this soon after an attempt is refused, not fetched for
                self._tried_at = now
            try:
                certs = self._fetch()
            except Exception:
                if not fresh:  # past the TTL a failed refresh never serves the old set
                    self._certs, self._fetched_at = {}, None
                raise
            self._certs, self._fetched_at = certs, now
            return certs

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        header, claims = _unverified(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("not a Google-signed token")
        if claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != audience:
            raise ValueError("not a token for this service")
        from google.auth import jwt

        verified = jwt.decode(
            token, certs=self._certificates(header["kid"]), verify=True, audience=audience, clock_skew_in_seconds=10
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
    task = store.tasks.get(body.task_id)
    if task is None or task.owner != principal.user_id:  # unknown and another user's task answer alike
        raise HTTPException(status_code=404, detail="No such task.")
    deps.refuse_if_replay_only(flags)  # NFR-24: after sign-in and the owner check
    with task.lock:
        approach = next((a for a in task.approaches or [] if a["id"] == body.approach_id), None)
        grants = [e for e in store.events.get(task.world_id, []) if e["type"] == "budget.granted"]
        if not task.granted or not grants:
            raise HTTPException(status_code=409, detail="Approve this task's budget first.")
        if approach is None:
            raise HTTPException(status_code=422, detail="Pick one of the approaches this task was offered.")
        brief, approach, cap = copy.deepcopy(task.brief), copy.deepcopy(approach), grants[0]["data"]["cap"]
    cadence, now = body.cadence.build(), clock()
    try:
        record = Schedule(
            schedule_id="sched_" + secrets.token_hex(12), owner_user_id=principal.user_id, title=body.title,
            cadence=cadence, approved_brief_ref=task.world_id, budget_cap=float(cap), next_due=next_slot(cadence, now),
            brief=brief, approach=approach, created_at=now,
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


@router.patch("/schedules/{schedule_id}")
def update_schedule(
    schedule_id: str,
    principal: Principal,
    body: Annotated[PatchIn, Depends(_json_body(PatchIn))],
    schedules: Schedules,
    clock: Clock,
    flags: Flags,
) -> dict[str, Any]:
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


@router.delete("/schedules/{schedule_id}", status_code=204)
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


class ScheduleStarter:
    """The tick's `RunStarter`: reads the stored snapshot, never what it is handed over it (design decisions 3, 4)."""

    def __init__(
        self,
        *,
        store: deps.Store,
        schedules: ScheduleRepository,
        seams: runs.Seams | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._schedules, self._seams, self._clock = store, schedules, seams, clock

    def start(self, run: RunStart) -> str:
        record = self._schedules.get(run.schedule_id)
        if record is None:
            raise StartSkipped("schedule_missing")
        if run.owner_user_id != record.owner_user_id:
            raise StartSkipped("owner_mismatch")
        if record.brief is None or record.approach is None:
            raise StartSkipped("snapshot_missing")
        if self._seams is None:
            raise StartSkipped("run_seams_unwired", count=False)  # the whole service, not this schedule: not counted
        digest = _digest(run.idempotency_key)
        world_id, run_id, owner, store = f"w_s{digest}", f"r_s{digest}", record.owner_user_id, self._store
        with store.grant_lock(owner):  # one owner's grants at a time: daily limits count every earlier grant
            existing = store.worlds.get(world_id)
            if existing is None:
                self._create_world(run, record, world_id, run_id)
            elif existing.owner != owner:
                raise StartSkipped("owner_mismatch")
        task = deps.TaskRecord(
            owner, world_id, run_id, copy.deepcopy(record.brief), copy.deepcopy(record.brief), [], 3,
            approaches=[copy.deepcopy(record.approach)], granted=True,
        )  # fmt: skip
        # start_run keeps one run per world, so a repeat (or a retry after a failed start) starts nothing twice
        runs.start_run(store, task, approach=record.approach, budget_cap=record.budget_cap, seams=self._seams)
        return world_id

    def _create_world(self, run: RunStart, record: Schedule, world_id: str, run_id: str) -> None:
        """world.requested, then the budget grant by the owner's own policy; stored only if the grant ran."""
        store, owner, stamp = self._store, record.owner_user_id, _stamp(self._clock())
        base = {"v": "1.0", "ts": stamp, "world_id": world_id, "run_id": run_id, "actor": owner}
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
        store.events.setdefault(world_id, []).extend([requested, outcome.granted_event])
        store.worlds[world_id] = deps.WorldRecord(
            owner=owner, districts={}, run_id=run_id, prior_world_id=run.prior_world_id
        )


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]


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


@router.post("/internal/schedules/tick")
def tick(
    request: Request,
    config: Annotated[tuple[str, str], Depends(_tick_config)],
    schedule_store: Annotated[Callable[[], ScheduleRepository], Depends(get_schedule_store_factory)],
    seams_factory: Annotated[Callable[[], runs.Seams | None], Depends(get_seams_factory)],
    verifier: Annotated[OidcVerifier, Depends(get_oidc_verifier)],
    clock: Clock,
    flags: Flags,
    store: StoreDep,
) -> Any:
    """No body and no query are read: nothing a caller sends selects a schedule or sets the time. The schedule store and
    the run seams are built only after the token passed (an anonymous call costs neither), once per request."""
    audience, caller = config
    token = _bearer(request)
    if token is None:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = verifier.verify(token, audience)
        allowed = isinstance(claims, Mapping) and tick_caller_ok(claims, audience=audience, caller=caller)
    except Exception as exc:  # bad signature, expiry, audience or a verifier outage: not an accepted caller
        logger.warning("schedule tick token refused (%s)", type(exc).__name__)  # the type only: no text, no traceback
        return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    if not allowed:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    try:
        schedules = schedule_store()
        seams = seams_factory()
    except HTTPException as exc:  # no store configured: closed, with the fixed code the routes use
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    except Exception as exc:
        logger.error("schedule tick could not be set up (%s)", type(exc).__name__)
        return JSONResponse({"detail": "tick failed"}, status_code=500)

    def alert(world_id: str, fields: dict[str, Any]) -> None:
        assert seams is not None  # an alert follows a fired run, which needs the seams
        part = {"id": events.new_part_id(), "level": None, "district": None, "item": None, "credits": 0}
        seams.writer.append(world_id, {**part, "cause": None, "vis": "all", "authz": None, **fields})

    starter = ScheduleStarter(store=store, schedules=schedules, seams=seams, clock=clock)
    try:
        fired = Ticker(store=schedules, starter=starter, flags=flags, clock=clock, alerts=alert).tick().fired
    except Exception as exc:  # fail closed with a fixed body; Scheduler retries and the next tick re-reads the store
        logger.error("schedule tick failed (%s)", type(exc).__name__)
        return JSONResponse({"detail": "tick failed"}, status_code=500)
    return {"fired": fired}
