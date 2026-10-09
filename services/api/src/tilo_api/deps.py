"""Injected auth, storage and event-writer seams for tilo-api (FR-HIL-09/SEC-07 roles and
redaction, FR-HIL-07 kill switches, services/api/tests/API_ST3a.md). Real sign-in, Firestore and
the harness are later tickets (PRD 15.3); every route takes a `Principal`, a `Store` and, for the
three that emit events, an `EventWriter` via FastAPI dependency overrides. Production code raises
a refusal until those land (401 without a principal, 503 `not_configured` without a store or writer, issue
#410), so a route can never run unauthenticated or against no store or writer.

`Store.dispatch_state` is FR-HIL-07's own per-world lock and per-policy lock bookkeeping
(services/api/src/tilo_api/dispatch.py): it lives on the Store instance itself, never a
module-level dict keyed by world_id alone, so two Store instances that happen to use the same
world_id string never share lock state.
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, cast

from fastapi import Depends, HTTPException, Request
from starlette.requests import HTTPConnection
from tilo_archive import RunArchive
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.registry import ConnectorRegistry, load_registry
from tilo_harness.executor import DefaultUnitRunner
from tilo_harness.skills import SkillRegistry
from tilo_memory.artifacts import ArtifactStore
from tilo_metering import LedgerEntry
from tilo_metering.flags import FlagStore, process_flags
from tilo_people.stores import PeopleStores
from tilo_planning.compiler import PlanInputs, compile_plan
from tilo_planning.gaps import Gap
from tilo_planning.memory import InMemoryPreferenceStore, MemoryLookup
from tilo_planning.questions import Question
from tilo_providers.config import ProviderConfigError, ProvidersConfig, load_providers_config, resolve_models_path
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.router import Router, RouterExhaustedError
from tilo_providers.safety import build_safety_provider

from tilo_api import events, firebase_auth, spend
from tilo_api.access import AccessStore, Mode, enforced, provider_mode
from tilo_api.appcheck import AppCheckVerifier, default_verifier
from tilo_api.assistant.config import AssistantConfig, AssistantConfigError, load_assistant_config
from tilo_api.people_access import NoSourceOwners
from tilo_api.people_access import SourceOwners as PanelSourceOwners

if TYPE_CHECKING:
    from tilo_api.assistant.core import Decider
    from tilo_api.assistant.metering import DecisionCache, SpendLedger

Role = Literal["owner", "team_lead", "approver", "viewer"]
Channel = Literal["web", "mobile_web", "email"]  # WhatsApp removed: SD-01, ADR-0019

logger = logging.getLogger("tilo_api.deps")
_REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES_DIR = _REPO_ROOT / "fixtures"  # record-and-replay recordings (EFF-01)
_DEFAULT_PART_WRITE_DEADLINE_S = 0.5
_DEFAULT_ABANDON_AFTER_S = 3.0
_MAX_DISPATCH_S = 4.0  # below a kill-switch call's 4.5 s write budget (FR-HIL-07's 5 s)


@dataclass(frozen=True)
class Principal:
    """Test double for auth. One per request, via app.dependency_overrides[get_current_principal]."""

    user_id: str  # common.schema.json#/$defs/user_id
    role: Role
    world_id: str | None = None  # the one world this principal is a member of; a mismatch with
    # the path's world_id gets the same 404 as an unknown world (no membership oracle)
    channel: Channel = "web"  # the session channel sign-in resolved for this request (FR-HIL-07,
    # world.paused.data.channel is derived from here, never from a request body
    districts: tuple[str, ...] = ()  # visible beyond vis: "all"; ignored for role == "owner"
    demo_session: bool = False  # an anonymous demo session (SEC-15, BQ-SIGNIN-10): models are replay only, always
    full_session: bool = False  # a full web sign-in session (BQ-XWORLD-10): set only by the server that resolves the
    # session, never from anything in a request; needed to answer, or read in full, another owned world's cards


@dataclass
class DistrictRecord:
    name: str
    summary: str


@dataclass
class WorldRecord:
    owner: str  # common.schema.json#/$defs/user_id
    districts: dict[str, DistrictRecord | None]  # district_id -> record; a malformed/None value
    # is a test proving the read routes fail closed (hidden) rather than raising
    owner_channels: tuple[str, ...] = ("web", "email")  # kill-switch confirmations
    run_id: str = "r_village_basic_1"  # the world's current run; tilo-api reads this, never invents it
    paused: bool = False  # true once Pause all has actually paused this world (PRD 9.4 honesty:
    # only ever true together with a world.paused event queued or committed somewhere)
    prior_world_id: str | None = None  # a scheduled run's previous world (FR-AGT-14b): offered, never silently reused
    layout: dict | None = None  # the run's built layout (PRD 15.1 World), None until the run commits it (ADR-0026);
    # the event writer reads it, with `run_id`, from here, never from a part


@dataclass
class TaskRecord:
    """One intake's planning state (CL-INT-1, services/api/tests/API_CL_INT_1.md). `draft` is the brief
    as the questions left it; `brief` is the draft with the person's answers and chip edits applied."""

    owner: str  # the principal who created it: the world's owner (PRD 10.1)
    world_id: str
    run_id: str
    draft: dict
    brief: dict
    questions: list[Question]
    next_seq: int  # the next event seq in this world
    answers: dict[str, str | None] = field(default_factory=dict)  # field -> answer; None when skipped
    edits: dict[str, Any] = field(default_factory=dict)
    approaches: list[dict] | None = None  # proposed for the current brief
    granted: bool = False
    scenario: str | None = None  # FR-INT-11: the scenario id named at intake; its policies are created at approve
    gaps: tuple[Gap, ...] = ()  # FR-INT-15: the parts Tilo cannot do, set once at intake; answers and edits keep them
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


@dataclass
class Store:
    """In-memory injected state; one instance per test, mutated in place by route handlers."""

    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    events: dict[str, list[dict]] = field(default_factory=dict)  # world_id -> event.schema.json
    # records, append-only (EV-10), written only by EventWriter.append.
    policies: dict[str, dict] = field(default_factory=dict)  # policy_id -> policy.schema.json record
    policy_worlds: dict[str, str] = field(default_factory=dict)  # policy_id -> the world whose
    # stream receives that policy's policy.changed events; a policy absent here still gets one,
    # routed to the world a kill switch was pressed in (policies carry no world_id of their own).
    pending_events: dict[str, list[dict]] = field(default_factory=dict)  # world_id -> event parts
    # built but not yet confirmed committed (EventWriter.append raised, or the attempt has not
    # settled within its own deadline yet); dispatch.py's queue *is* this list, deduped by each
    # part's own `id`, oldest first.
    dispatch_state: dict = field(default_factory=dict, repr=False, compare=False)  # dispatch.py's
    # own per-world and per-policy locks; opaque to every route outside dispatch.py.
    tasks: dict[str, TaskRecord] = field(default_factory=dict)  # task_id -> record (CL-INT-1)
    memory: MemoryLookup = field(default_factory=InMemoryPreferenceStore)  # FR-INT-05 seam until P7
    grant_locks: dict[str, threading.Lock] = field(default_factory=dict, repr=False, compare=False)
    _grant_locks_guard: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    runs: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)  # world_id -> runs.Run (CL-INT-2)
    runs_guard: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def grant_lock(self, owner: str) -> threading.Lock:
        """FR-INT-08: one owner's grants are decided one at a time, so a policy's daily limits count every
        earlier grant (two concurrent approves could otherwise both read the same history)."""
        with self._grant_locks_guard:
            return self.grant_locks.setdefault(owner, threading.Lock())

    # The seams a route uses to read and write records and events. Here (dev mode, tests) the dicts are the store:
    # loads read the cache, and `save` sends events through the writer first. `DurableStore` overrides all of them.
    # `settle=False` is for a caller that has not yet checked who is asking: a load that settles also writes.
    def load_world(self, world_id: str, settle: bool = False) -> WorldRecord | None:
        return self.worlds.get(world_id)

    def load_task(self, task_id: str, settle: bool = False) -> TaskRecord | None:
        return self.tasks.get(task_id)

    def load_owner(self, owner: str, settle: bool = False) -> None:
        """Called before a route iterates an owner's worlds or policies; the cache already holds them."""

    def load_path(self, params: Mapping[str, Any]) -> Store:
        return self

    def settle(self, world_id: str, writer: EventWriter | None = None) -> None:
        """What a previous process left in the world (its queue, a run that died): nothing to do on a plain store."""

    def deadline(self, seconds: float) -> AbstractContextManager[None]:
        """Bounds the calling thread's wait for the store's lock; a plain store has no lock to wait for."""
        return nullcontext()

    def commit(
        self,
        *,
        worlds: Mapping[str, WorldRecord] | None = None,
        tasks: Mapping[str, TaskRecord] | None = None,
        policies: Mapping[str, dict] | None = None,
        policy_worlds: Mapping[str, str] | None = None,
        parts: Mapping[str, list[dict]] | None = None,  # a plain store has no queue: the caller sends its parts
        create: Iterable[tuple[str, str]] = (),
        evict: bool = True,
    ) -> None:
        self.worlds.update(worlds or {})
        self.tasks.update(tasks or {})
        self.policies.update(policies or {})
        self.policy_worlds.update(policy_worlds or {})

    def save(
        self, writer: EventWriter | None, *, parts: Mapping[str, list[dict]] | None = None, **records: Any
    ) -> None:
        """A route's new records and events. The events go through `writer` first (it reads the world's record, so a
        new one is stored before them); a failure removes the worlds this call created and changes nothing else."""
        self.worlds.update(records.get("worlds") or {})
        sending = ""
        try:
            for sending, world_parts in (parts or {}).items():
                for part in world_parts:
                    assert writer is not None
                    writer.append(sending, part)
        except Exception as exc:
            for kind, world_id in records.get("create", ()):
                if kind == "worlds":
                    self.worlds.pop(world_id, None)
            raise event_failure(sending, exc) from None
        self.commit(parts=parts, **records)

    def ack(self, world_id: str, part_id: str) -> None:
        """A queued part is committed: a durable store forgets it in its queue too."""


class EventRejected(Exception):
    """Raised by EventWriter.append when a caller resends an `id` already committed for that
    world with genuinely different content (EV-10 conflict, never a silent overwrite)."""


def event_failure(world_id: str, exc: Exception) -> HTTPException:
    """A writer's failure as the route's answer: a refused event is a fixed 409, anything else 503 `store_unavailable`;
    never the validator's text (it names world, run and event ids)."""
    if isinstance(exc, HTTPException):
        return exc
    logger.warning("event writer failed for world %s (%s)", world_id, type(exc).__name__)
    if isinstance(exc, EventRejected):
        return HTTPException(status_code=409, detail="the event was refused")
    return HTTPException(status_code=503, detail="store_unavailable")


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3). Every event tilo-api hands here carries its own
    stable `id` (a ULID), built once when the part is enqueued and resent unchanged on every
    retry -- the sole idempotency key `append` dedupes on (issue #46 / EV-10), never raw content
    and never which writer object happens to receive the call. The writer stamps `seq`, `ts`, `world_id`,
    `run_id` and `v`; a part's `trace` is kept only after the event validator accepts it, and a part without
    one gets a null trace.

    A writer that wraps the harness `WorldWriter` should also expose an optional `reopen()`: the
    dispatcher calls it after a failed append, before the same event is resent, so a stale lease
    or an ambiguous commit (issue #55 item 2) recovers instead of answering WriterBusy forever."""

    def append(self, world_id: str, event: dict) -> dict:
        """Returns the committed event.schema.json record (the existing one, unchanged, on an
        idempotent-by-id retry); raises EventRejected on a same-id/different-content conflict."""
        ...


SIGN_IN_REQUIRED = "Sign in to use this."


def get_firebase_verifier() -> firebase_auth.FirebaseVerifier:
    """SEC-15: checks a person's Firebase ID token (`tilo_api.firebase_auth`). Google's keys for the API's own
    project; dev mode and an unconfigured project refuse without any call. Tests override it; it never decides
    authorisation beyond who the person is."""
    return firebase_auth.default_verifier()


def get_current_principal(request: HTTPConnection) -> Principal:
    """The signed-in person (SEC-15, BQ-SIGNIN-6): `Authorization: Bearer <Firebase ID token>`, verified through
    `get_firebase_verifier`; `X-Tilo-Channel: mobile_web` picks the channel, nothing else in a request sets anything.
    Every other case is a 401 with one fixed body, whatever the cause. Dev mode replaces this whole function
    (`tilo_api.dev.install`), so a token is never looked at there."""
    resolved = getattr(request.state, "principal", None)  # the access gate already verified this request (server-set)
    if isinstance(resolved, Principal):
        return resolved
    # With no gate, the token is verified once per request (BQ-SIGNIN-9(e)): `spend_mode` and the route share it.
    earlier = getattr(request.state, "signin_attempt", None)
    if isinstance(earlier, Principal):
        return earlier
    if earlier is not None:
        raise HTTPException(status_code=401, detail=SIGN_IN_REQUIRED, headers={"WWW-Authenticate": "Bearer"})
    try:
        principal = _verified_principal(request)
    except HTTPException:
        request.state.signin_attempt = "refused"
        raise
    request.state.signin_attempt = principal
    return principal


def _verified_principal(request: HTTPConnection) -> Principal:
    token = firebase_auth.bearer_token(request.headers.getlist("authorization"))
    if token is None:
        raise HTTPException(status_code=401, detail=SIGN_IN_REQUIRED, headers={"WWW-Authenticate": "Bearer"})
    try:
        factory = request.app.dependency_overrides.get(get_firebase_verifier, get_firebase_verifier)
        claims = factory().verify(token)
        channel = firebase_auth.channel_of(request.headers.get("x-tilo-channel"))
        return firebase_auth.principal_from_claims(claims, channel=channel)
    except Exception as exc:  # any failure at all is "not signed in": nothing here ever fails open
        reason = exc.code if isinstance(exc, firebase_auth.TokenRefused) else f"verifier_failed:{type(exc).__name__}"
        logger.warning("sign-in token not accepted (reason=%s)", reason)  # a fixed code, never the token
        raise HTTPException(status_code=401, detail=SIGN_IN_REQUIRED, headers={"WWW-Authenticate": "Bearer"}) from None


def resolve_principal(app: Any, connection: HTTPConnection) -> Principal:
    """The principal for `connection` through the seam as the app is wired (overrides included), the way FastAPI would
    resolve it. A test double that takes no argument still works. Raises what the seam raises (a 401, usually)."""
    resolver = app.dependency_overrides.get(get_current_principal, get_current_principal)
    return resolver(connection) if inspect.signature(resolver).parameters else resolver()


def get_store(request: Request = None) -> Store:  # type: ignore[assignment]  # FastAPI injects it; None elsewhere
    """Deployed: the durable store for `TILO_API_STORE`, with the request's path ids loaded (ADR-0026 decisions 1, 3);
    without a valid config 503 `not_configured`, never cached. Dev mode and the tests override this seam."""
    from tilo_api import ephemeral
    from tilo_api.durable_store import deployed

    if request is not None and (demo := ephemeral.for_request(request)) is not None:
        return demo.store  # an anonymous demo session stores nothing durable (DEMO-EPHEMERAL-1)
    store = deployed()[0]
    return store.load_path(request.path_params) if request is not None else store


def get_event_writer(request: Request = None) -> EventWriter:  # type: ignore[assignment]
    from tilo_api import ephemeral
    from tilo_api.durable_store import deployed

    if request is not None and (demo := ephemeral.for_request(request)) is not None:
        return demo.writer
    return deployed()[1]


def get_ledger() -> Sequence[LedgerEntry]:
    """The Treasury's ledger (FR-MTR-10). No ledger store is wired in yet (BQ-MTR10-4): fail closed."""
    raise HTTPException(status_code=503, detail="not_configured")


def get_ledger_writer() -> Any:
    """The Treasury's write seam (COST-FAST-1b, BQ-COSTFAST-7): an object with `append(LedgerEntry)`. Not wired
    yet, like `get_ledger`: fail closed. Quick treats that as best effort (`ledger_writer_for`)."""
    raise HTTPException(status_code=503, detail="not_configured")


def ledger_writer_for(request: Request) -> Any:
    """The writer as the app is wired (overrides included), or None when it is unwired or fails."""
    return _resolve(request, get_ledger_writer)


def get_time_baselines() -> Any:
    """The EV-G2 time-saved baselines (FR-PA-20, PRD 14.2):
    `{method_url, units: {unit_type: {p25, median, p75}}}`, minutes
    per unit. Not measured and no config shape yet (BQ-PA20-2), so no production wiring: fail closed."""
    raise HTTPException(status_code=503, detail="not_configured")


def prices_path() -> Path:
    """config/prices.yaml, the price sheet (FR-MTR-01): the one public way for a route to find it."""
    return _REPO_ROOT / "config" / "prices.yaml"


def providers_config() -> ProvidersConfig:
    """Read on every call, not at import: `TILO_MODELS_FILE` picks the models file (PL-02)."""
    return load_providers_config(resolve_models_path(_REPO_ROOT), _REPO_ROOT / "config" / "prices.yaml")


MAX_BUDGET_CAP_CREDITS = 300.0  # BQ-99: PRD 17.3's per-run cap, used when config/metering.yaml gives none


def budget_cap_ceiling() -> float:
    """The most credits one approval may grant: `caps.run_credits` in config/metering.yaml (PRD 14.1, 17.3), or
    MAX_BUDGET_CAP_CREDITS when the file or the value is missing or unusable (BQ-99)."""
    try:
        import yaml

        value = yaml.safe_load((_REPO_ROOT / "config" / "metering.yaml").read_text(encoding="utf-8"))["caps"][
            "run_credits"
        ]
    except Exception as exc:
        logger.warning("metering config unreadable (%s); using the default budget ceiling", type(exc).__name__)
        return MAX_BUDGET_CAP_CREDITS
    if isinstance(value, bool) or not isinstance(value, int | float) or not (math.isfinite(value) and value > 0):
        return MAX_BUDGET_CAP_CREDITS
    return float(value)


def get_access_store() -> AccessStore:
    """SEC-15: where each person's visitor-or-judge declaration is kept: the Firestore store when `TILO_API_STORE` is
    `firestore` (`access_firestore`, through `store_door`); without a valid config 503 `not_configured` (never memory),
    so a deployed process closes every gated route rather than guess. Tests override it."""
    from tilo_api import access_firestore

    return access_firestore.deployed()


def get_app_check_verifier() -> AppCheckVerifier:
    """SEC-10: checks a client's App Check token (`tilo_api.appcheck`). Google's keys for the API's own project; dev
    mode and an unconfigured project refuse without any call. Tests override it; it never decides authorisation."""
    return default_verifier()


def get_spend_caps() -> spend.SpendCaps:
    """SEC-16: `config/spend_caps.yaml`, read on every call (a cap is a config edit, never code)."""
    return spend.load_spend_caps(None)


@functools.cache
def get_rate_limiter() -> spend.RateLimiter:
    """SEC-16: one process-wide limiter from config (per instance on Cloud Run; a shared one is a later decision)."""
    caps = get_spend_caps()
    return spend.RateLimiter(limit=caps.rate_limit_requests, window_s=caps.rate_limit_window_s, clock=time.monotonic)


def get_spend_cap_ledger() -> spend.SpendLedger:
    """SEC-16's ledger (not FR-PA-19's `get_spend_ledger`). Unwired, a deployed judge is replay, never uncapped; wire
    it only with the per-unit `SpendGuard.begin_unit`/`settle_unit` wiring (BQ-SEC16-1), or live spend is unmetered."""
    raise HTTPException(status_code=503, detail="not_configured")


def _resolve(request: Request, seam: Callable[[], Any]) -> Any:
    try:  # the seam as the app is wired (overrides included), or None when it refuses or fails
        return request.app.dependency_overrides.get(seam, seam)()
    except Exception:
        return None


def caps_for(request: Request) -> spend.SpendCaps | None:
    """SEC-16 caps as the app is wired (overrides included), or None when unreadable (COST-FAST-1 reserves a unit)."""
    return _resolve(request, get_spend_caps)


def get_switches(request: Request, flags: Annotated[FlagStore, Depends(get_flag_store)]) -> FlagStore:
    """Deployed, NFR-24's flags plus the ledger's durable `replay_only` (FR-MTR-04); not deployed, the flags alone."""
    return spend.Switches(flags, _resolve(request, get_spend_cap_ledger)) if enforced() else flags


def spend_mode(
    request: Request, uid: str | None, declaration: str | None, switches: FlagStore, *, demo: bool | None = None
) -> tuple[Mode, bool]:
    """(mode, capped): SEC-15's decision, then deployed the `SpendGuard`'s; any doubt is replay (fail closed). An
    anonymous demo session (`Principal.demo_session`, set by the gate from the verified token, or with no gate the
    request's own sign-in) is replay whatever `LIVE`, `TILO_JUDGE_LIVE` or the guard say (BQ-SIGNIN-10): a "replay"
    mode reaches the providers as `force_replay` (`router_for_mode`, `get_safety`), so `LIVE=1` cannot override it.
    Its cap is still read, so new work is refused the same way."""
    mode, capped = _spend_mode(request, uid, declaration, switches)
    if demo is None:  # the gate's flag, or what the request's own sign-in says where there is no gate
        demo = getattr(request.state, "demo_session", False) is True or _signed_in_as_demo(request)
    return ("replay" if demo is True else mode), capped


def _signed_in_as_demo(request: Request) -> bool:
    """True when this request's own sign-in is an anonymous demo session. Only a process the access gate does not
    guard (not deployed) looks: deployed, the gate has already set the flag, and a public route has no person to
    resolve. Nobody signed in (no `Authorization` header) is False: the answer is then the user's own switch. A token
    that is present but cannot be verified fails closed: replay (BQ-SIGNIN-10). The verification is the route's own,
    done once per request (`get_current_principal`), so this adds no second check and no second log line."""
    if enforced():
        return False
    try:
        return resolve_principal(request.app, request).demo_session is True
    except Exception:
        return bool(request.headers.getlist("authorization"))


def _spend_mode(request: Request, uid: str | None, declaration: str | None, switches: FlagStore) -> tuple[Mode, bool]:
    mode = provider_mode(declaration, os.environ, replay_only=bool(switches.get("replay_only")))
    if mode != "live" or uid is None or not isinstance(switches, spend.Switches):
        return mode, False
    caps = _resolve(request, get_spend_caps)
    if switches.ledger is None or caps is None:
        return "replay", False
    from tilo_api import team_access, team_store  # late: team_store's dev seam imports this module

    try:  # FR-TEAM-02: the team's role and personal limits, a MIN on the lifetime cap; unreadable is capped
        cap = team_access.user_cap_minor(
            team_store.team_reader(request.app.dependency_overrides)(), uid, caps.uid_lifetime_minor
        )
    except Exception as exc:
        logger.warning("team limits unreadable, so live is denied: %s", type(exc).__name__)
        cap = 0
    if cap <= 0:
        return "replay", True
    caps = dataclasses.replace(caps, uid_lifetime_minor=min(cap, caps.uid_lifetime_minor))
    guard = spend.SpendGuard(switches.ledger, switches.flags, caps)
    capped = guard.uid_capped(uid)
    return provider_mode(declaration, os.environ, replay_only=not guard.live_allowed(uid), capped=capped), capped


def get_mode(request: Request, switches: Annotated[FlagStore, Depends(get_switches)]) -> Mode:
    """This request's model mode from what the access gate verified (never what a client sent): SEC-15, SEC-16."""
    state = request.state
    return spend_mode(request, getattr(state, "uid", None), getattr(state, "declaration", None), switches)[0]


def get_work_mode(request: Request, switches: Annotated[FlagStore, Depends(get_switches)]) -> Mode:
    """`get_mode` for new work, refused before any router is built: a switch set (503) or the uid capped (403)."""
    if isinstance(switches, spend.Switches) and switches.get("replay_only"):
        raise ReplayOnly
    state = request.state
    mode, capped = spend_mode(request, getattr(state, "uid", None), getattr(state, "declaration", None), switches)
    if capped:
        raise spend.SpendCapReached
    return mode


def router_for_mode(mode: Mode) -> Router:
    """The one place a request's Router is built (PL-01). It replays recordings unless `mode` is "live", which only
    `access.provider_mode` returns: the user's own global switch, or a deployed judge where the user set
    `TILO_JUDGE_LIVE=1` (SEC-15). The permission is injected into the Router, never read-and-written from the
    environment, so no request can turn live mode on for the process (EFF-01). Any other mode is a replay decision
    (a demo session, NFR-24's switch, SEC-16's cap, no live declaration), injected as `force_replay`: it holds at the
    provider layer even where `LIVE=1` is set, and never records (BQ-SIGNIN-10)."""
    try:
        live = mode == "live"
        return Router(providers_config(), fixtures_dir=FIXTURES_DIR, live_permitted=live, force_replay=not live)
    except ProviderConfigError as exc:
        logger.warning("model router unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="The model router is not configured.") from exc


def get_router(mode: Annotated[Mode, Depends(get_work_mode)] = "replay") -> Router:
    """Every model call goes through the provider layer's Router (PL-01), built for this request's mode."""
    return router_for_mode(mode)


def get_safety(mode: Annotated[Mode | None, Depends(get_mode)] = None) -> SafetyProvider:
    """PRD 16.3 item 2: built from the `safety` role on every call; no role, or a provider the factory refuses
    (the fake when live or deployed), closes the screened routes with 503. A request in replay mode screens from
    recordings only, `LIVE=1` or not (BQ-SIGNIN-10); `None` (a direct call with no request) follows the live switch."""
    try:
        return build_safety_provider(providers_config(), fixtures_dir=FIXTURES_DIR, force_replay=mode == "replay")
    except ProviderConfigError as exc:
        logger.warning("safety provider unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="No safety provider is configured; nothing is screened, so nothing is accepted."
        ) from exc


# --- the run seams (CL-INT-2, services/api/tests/API_CL_INT_2.md); each default is the production wiring (BQ-90) ---


def _no_plan_compiler(*, brief: dict, approach: dict, budget_cap: float, context: Any = None) -> dict:
    raise NotImplementedError("no `director` role is configured, so no plan can be compiled and no run starts")


def _seam_router(mode: Mode) -> Router:
    """The run seams build their Router through `get_router`, the request's mode threaded in by `runs.run_seams`.
    The replay default stays a zero-argument call, so a zero-argument override of `get_router` keeps working."""
    return get_router() if mode == "replay" else get_router(mode)


def get_plan_compiler(mode: Mode = "replay") -> Callable[..., dict]:
    """`compile(*, brief, approach, budget_cap, context) -> PlanGraph` (FR-INT-09). The Director drafts it through
    the Router and `validate_plan` decides (BQ-90); with no `director` role in the provider config it refuses."""
    if "director" not in providers_config().roles:
        return _no_plan_compiler
    router = _seam_router(mode)

    def compile_with_director(*, brief: dict, approach: dict, budget_cap: float, context: PlanInputs) -> dict:
        return compile_plan(brief, approach, budget_cap, context, router=router).plan

    return compile_with_director


def get_layout_builder() -> Callable[..., dict]:
    """`layout_for(plan, *, world_id) -> layout`, deterministic."""
    from tilo_api.layout import build_layout

    return build_layout


class _RoleModel:
    """A worker role's model, always through the Router (PL-01); the harness runner calls only `generate`."""

    def __init__(self, router: Router, role: str) -> None:
        self._router, self._role = router, role

    def generate(self, request: Any) -> Any:
        return self._router.generate(self._role, request).response


def _worker_models(mode: Mode = "replay") -> Mapping[str, Any]:
    router = _seam_router(mode)
    return {role: _RoleModel(router, role) for role in ("specialist", "writer", "verifier")}


def get_unit_runner(mode: Mode = "replay") -> Any:
    return DefaultUnitRunner(cast(Any, _worker_models(mode)))


def get_must_ask_providers(mode: Mode = "replay") -> Mapping[str, Any]:
    """The models `MustAsk` judges a unit with (FR-AGT-05), keyed by the unit's role; always the Router's roles."""
    return _worker_models(mode)


def _no_recipients(*, unit: dict, action_type: str, item: dict, brief: dict) -> dict:
    raise LookupError("no address book is wired yet, so a send has no recipients")


def get_action_resolver() -> Callable[..., dict]:
    """`resolve(*, unit, action_type, item, brief) -> {destination, recipients, known_recipients?}`."""
    return _no_recipients


def get_skill_registry() -> SkillRegistry:
    return SkillRegistry(_REPO_ROOT / "skills")


def get_connector_registry() -> ConnectorRegistry:
    path = _REPO_ROOT / "config" / "connectors.yaml"
    return load_registry(path) if path.is_file() else ConnectorRegistry({})


def get_connector_adapters() -> dict[str, Any]:
    return {}  # no live adapter in dev (EFF-01): a send has nowhere to go


@functools.cache
def get_outbox_store() -> InMemoryOutboxStore:  # a demo's own: `ephemeral.DemoSession.outbox`, built by `run_seams`
    return InMemoryOutboxStore()  # the process's own until the Firestore store lands


# ADR-0018 T4: tilo-api has no org until sign-in, so every run's artifact Scope is in this org (PRD 15.1), never a
# request's.
ORG_ID = "org_tilo"


def _demo(request: Request | None) -> Any:
    from tilo_api import ephemeral

    return ephemeral.for_request(request) if request is not None else None


def get_artifact_store(request: Request = None) -> ArtifactStore:  # type: ignore[assignment]
    """Where a run's outputs go. No production backend exists until ADR-0018 T8 (Firestore, GCS), so this refuses and
    no run starts (fail closed, BQ-AGT02-T4-1); dev mode wires one in-memory store, and a demo session its own."""
    if (demo := _demo(request)) is not None:
        return demo.artifacts
    raise NotImplementedError("no artifact store is configured, so no run starts")


def get_redactor(request: Request = None) -> Callable[[str], str]:  # type: ignore[assignment]
    """The shared secret redactor the store was given (MF-06). Not built until FR-MEM-05 (BQ-109): refuses."""
    if (demo := _demo(request)) is not None:
        return demo.redactor
    raise NotImplementedError("the shared secret redactor is not built, so no run starts")


# --- the people API seams (PPL-11a, services/api/tests/API_PPL_11a.md section 4); production fails closed ---

NOTICE_VERSION = "1.0.0"  # stamped as `attestation.notice_version` on a meeting a person adds; read at call time


class PlateSources(Protocol):
    """The cards, runs and mail a plate may draw on; each returns facts, possibly more than the person's own."""

    def cards(self, user_id: str) -> Iterable[dict[str, Any]]: ...
    def runs(self, user_id: str) -> Iterable[dict[str, Any]]: ...
    def mail(self, user_id: str) -> Iterable[dict[str, Any]]: ...


class SourceOwners(Protocol):
    def owner_of(self, kind: str, ref: str) -> str | None: ...  # kind "mail" or "request"


_people_stores_lock = threading.Lock()
_people_stores: PeopleStores | None = None
_people_stores_retry_at: float | None = None
PEOPLE_STORES_BACKOFF_S = 5.0  # after a failed build, no new attempt for this long (FS-18; fixed, 1 to 60 s)
people_stores_clock: Callable[[], float] = time.monotonic  # read at call time, so a test can replace it


def _inside_backoff() -> bool:
    retry_at = _people_stores_retry_at
    return retry_at is not None and people_stores_clock() < retry_at


def get_people_stores(request: Request = None) -> PeopleStores:  # type: ignore[assignment]
    """The process's one `PeopleStores` (the write limiter and idempotency keys live on it, #549). Built on the first
    request, single-flight, only for `TILO_PEOPLE_STORE=firestore` plus a valid `TILO_FIRESTORE_PROJECT` (ADR-0023);
    anything else, or a build that fails, is 503 `not_configured` (the error never echoed). A failed build is
    remembered for `PEOPLE_STORES_BACKOFF_S`: inside the window a request is refused at once, without the lock and
    without a client call; after it one request tries again (FS-18)."""
    global _people_stores, _people_stores_retry_at
    if (demo := _demo(request)) is not None:
        return demo.people  # in memory, per demo session, gone with it
    built = _people_stores
    if built is not None:
        return built
    if _inside_backoff():
        raise HTTPException(status_code=503, detail="not_configured")
    with _people_stores_lock:
        if _people_stores is None:
            if _inside_backoff():  # the request that held the lock failed while this one waited
                raise HTTPException(status_code=503, detail="not_configured")
            from tilo_api.people_firestore import PeopleStoreNotConfigured, open_people_stores  # noqa: PLC0415

            try:
                _people_stores = open_people_stores()
                _people_stores_retry_at = None
            except Exception as exc:
                logger.warning("people stores not built (%s)", type(exc).__name__)
                if not isinstance(exc, PeopleStoreNotConfigured):  # no client was tried: nothing to back off from
                    _people_stores_retry_at = people_stores_clock() + PEOPLE_STORES_BACKOFF_S
                raise HTTPException(status_code=503, detail="not_configured") from None
        return _people_stores


def _forget_people_stores() -> None:
    global _people_stores, _people_stores_retry_at
    with _people_stores_lock:
        _people_stores, _people_stores_retry_at = None, None


get_people_stores.cache_clear = _forget_people_stores  # type: ignore[attr-defined]  # tests start from a cold process


_BOOTSTRAP_UID = re.compile(r"u_[0-9A-Za-z_]{1,48}")


def get_founder_gate() -> Callable[[str], bool]:
    """Who may found an empty org (issue #541 item 1, BQ-PPL11C-15): only the uid in `TILO_PEOPLE_BOOTSTRAP_UID`, read
    on every call and valid only as a `common#user_id` exactly as written. Unset or malformed refuses everyone."""
    configured = os.environ.get("TILO_PEOPLE_BOOTSTRAP_UID", "")
    if _BOOTSTRAP_UID.fullmatch(configured) is None:
        return lambda user_id: False
    return lambda user_id: user_id == configured


def get_clock() -> Callable[[], str]:
    return events.now  # a `common#timestamp`; a route reads it once per request


def get_plate_sources() -> PlateSources:
    raise HTTPException(status_code=503, detail="not_configured")


def get_source_owners() -> SourceOwners:
    raise HTTPException(status_code=503, detail="not_configured")


class MeetingWorlds(Protocol):
    """Creates the Outpost world that holds a meeting's transcript and minutes (FR-MTG-07, BQ-273)."""

    def make_meeting_world(self, *, org_id: str, owner: str, meeting_id: str) -> str: ...


def get_meeting_worlds() -> MeetingWorlds:
    raise HTTPException(status_code=503, detail="not_configured")  # production wiring lands with the Outpost world


class DeskWorlds(Protocol):
    """The one Desk world of a person, made lazily and idempotently: where their work-item events go (PE-12)."""

    def desk_world(self, org_id: str, user_id: str) -> str: ...

    def desk_owner(self, world_id: str) -> str | None:
        """Who owns that Desk world now (None: unknown), so a caller can check an answer before it writes there."""
        ...


def get_desk_worlds() -> DeskWorlds:
    raise HTTPException(status_code=503, detail="not_configured")  # production wiring lands with the Desk


def get_run_archive(request: Request = None) -> Callable[..., RunArchive]:  # type: ignore[assignment]
    """`open_archive(*, org_id, run_id) -> RunArchive`, the run's raw archive. No production store yet: refuses
    (a demo session's is in memory and dies with it)."""
    if (demo := _demo(request)) is not None:
        return demo.open_archive
    raise NotImplementedError("no raw-archive store is configured, so no run starts")


def get_token_broker() -> Any:
    """FR-MTG-09: the token broker's adapter-facing half (`access_token_for_adapter`). Unwired: no host run."""
    raise HTTPException(status_code=503, detail="not_configured")


class ConnectionViews(Protocol):
    """LIVE-GAPS-1b: a read-only view of a person's connector state (SEC-02: never a token, record, Kms or secret)."""

    def view(self, user_id: str, connector: str) -> tuple[str | None, list[str], str | None]: ...


def get_connection_views() -> ConnectionViews:
    """Read-only connector state for `GET /v1/connectors`. Production state comes from tilo-connectors over an internal
    route (ADR-0032 pattern, BQ-LIVEGAPS-1); unwired: refuses (the list route then shows every connector available)."""
    raise HTTPException(status_code=503, detail="not_configured")


def get_meeting_host_transport() -> Any:
    """FR-MTG-09: the `Transport` behind `MeetingHostAdapter`. No live transport in dev (EFF-01): refuses."""
    raise HTTPException(status_code=503, detail="not_configured")


REPLAY_ONLY_MESSAGE = "This link is replay-only right now: new work is paused; finished runs can still be replayed."


class ReplayOnly(Exception):
    """NFR-24: the answer is 503 with `replay_only: true` beside the text (tilo_api.app's handler), the labelled
    replay offer."""


MODEL_UNAVAILABLE_MESSAGE = (
    "The model is unavailable right now (quota or outage), so nothing new was started; finished runs can still be "
    "replayed."
)
_UNAVAILABLE = frozenset({"QuotaError", "RetryableError"})  # PL-02: 429 and 5xx/timeouts, not a bad reply


class ModelUnavailable(Exception):
    """NFR-22: every model candidate failed on quota or availability. Answered like NFR-24's refusal (503,
    `replay_only: true`, a detail that says replay), for this request only: the `replay_only` flag is not set."""


def raise_if_model_unavailable(error: BaseException) -> None:
    """NFR-22 (PRD 17.2): a planning error whose cause is the router running out of candidates, every attempt on
    quota or availability, becomes ModelUnavailable. A reply the model did send but got wrong stays the caller's."""
    cause = error.__cause__
    if (
        isinstance(cause, RouterExhaustedError)
        and cause.attempts
        and all(a.error_type in _UNAVAILABLE for a in cause.attempts)
    ):
        raise ModelUnavailable from error


def get_flag_store() -> FlagStore:
    """The process-wide flag store (`tilo_metering.flags.process_flags`). The Treasury and the Firestore-backed
    store are not wired in production yet, so until they are nothing sets `replay_only` here (BQ-238)."""
    return process_flags()


def refuse_if_replay_only(flags: FlagStore) -> None:
    """NFR-24 (PRD 17.2): with `replay_only` set the link starts no new live work. Called by the routes that reach
    the Director or start a run, after sign-in and the owner check; reads of what exists are untouched."""
    if flags.get("replay_only"):
        raise ReplayOnly


def _dispatch_config(key: str, default: float) -> float:
    """A positive finite number, at most _MAX_DISPATCH_S, from config/dispatch.yaml; anything else
    logs and uses the default."""
    try:
        import yaml

        raw = yaml.safe_load((_REPO_ROOT / "config" / "dispatch.yaml").read_text(encoding="utf-8"))
        value = float(raw["dispatch"][key])
    except Exception as exc:
        logger.warning("dispatch config %s unreadable (%s); using default %s", key, exc, default)
        return default
    if not (math.isfinite(value) and 0 < value <= _MAX_DISPATCH_S):
        logger.warning(
            "dispatch config %s=%r is not in (0, %s]; using default %s", key, value, _MAX_DISPATCH_S, default
        )
        return default
    return value


def get_part_write_deadline_s() -> float:
    """A single writer.append attempt's bounded wait (issue #46: read from config, injectable so a
    test can prove it is read fresh on every call; unlike the other three it has a working default)."""
    return _dispatch_config("part_write_deadline_s", _DEFAULT_PART_WRITE_DEADLINE_S)


def get_attempt_abandon_after_s() -> float:
    """How long an append may stay in flight before dispatch presumes it lost and resends the same
    event id (idempotent, EV-10)."""
    return _dispatch_config("attempt_abandon_after_s", _DEFAULT_ABANDON_AFTER_S)


# --- the assistant panel seams (PPL-11b, services/api/tests/API_PPL_11b.md): each default refuses until wired ---


class PlateSource(Protocol):
    """ADR-0021: the one plate builder, for the signed-in person only (PE-26). PPL-11a supplies it (BQ-PPL11B-15)."""

    def build(self, user: str, now: str) -> dict: ...


class _PlateBuilder:
    """The panel's `PlateSource` over PPL-11a's one plate builder (ADR-0021, BQ-PPL11B-15)."""

    def __init__(self, stores: PeopleStores, sources: PlateSources, owners: SourceOwners) -> None:
        self._stores, self._sources, self._owners = stores, sources, owners

    def build(self, user: str, now: str) -> dict:
        from tilo_api.people_plate import build_plate  # noqa: PLC0415  (people_plate imports this module)

        plate = build_plate(self._stores, self._sources, self._owners, ORG_ID, user, now)
        if plate is None:
            raise LookupError("no such person")
        return plate


def get_plate_source(
    stores: Annotated[PeopleStores, Depends(get_people_stores)],
    sources: Annotated[PlateSources, Depends(get_plate_sources)],
    owners: Annotated[SourceOwners, Depends(get_source_owners)],
) -> PlateSource:
    return _PlateBuilder(stores, sources, owners)  # each seam is 503 `not_configured` until wired


def get_panel_source_owners() -> PanelSourceOwners:
    return NoSourceOwners()  # fail closed until PPL-31 and PPL-11a read the owner from the source store (BQ-PPL11B-13)


def get_assistant_config() -> AssistantConfig:
    """Read on every call; an unusable file closes the panel (503) and the log names the key path only."""
    try:
        return load_assistant_config()
    except AssistantConfigError as exc:
        logger.warning("assistant config unusable: %s", exc)
        raise HTTPException(status_code=503, detail="not_configured") from exc


@functools.cache
def get_spend_ledger() -> SpendLedger:
    """The panel's daily allowance per person (FR-PA-19): in memory and process-wide until a shared store exists
    (BQ-PPL11B-6), like `get_outbox_store`."""
    from tilo_api.assistant.metering import InMemorySpendLedger  # noqa: PLC0415  (metering imports the model modules)

    return InMemorySpendLedger()


@functools.cache
def get_decision_cache() -> DecisionCache:
    from tilo_api.assistant.metering import InMemoryDecisionCache  # noqa: PLC0415

    config = get_assistant_config()
    return InMemoryDecisionCache(per_user_entries=config.cache_per_user_entries, ttl_hours=config.cache_ttl_hours)


def get_assistant_decider(mode: Annotated[Mode, Depends(get_mode)] = "replay") -> Decider | None:
    """The model fallback (FR-PA-14, FR-PA-19): the metered decider over the Router, or None, and the panel answers
    by rules only. None when the `assistant` role is not configured (dev mode), has no caps or no price, or the
    router or the safety provider is unavailable."""
    from tilo_api.assistant.metering import MeteredDecider  # noqa: PLC0415
    from tilo_api.assistant.model import AssistantModelUnavailable, ModelDecider  # noqa: PLC0415

    try:
        config = get_assistant_config()
        providers = providers_config()
        if config.model["role"] not in providers.roles:
            return None
        router = _seam_router(mode)
        # this request's mode reaches the screen too (BQ-SIGNIN-10); a stand-in that takes no argument still works
        safety = get_safety(mode) if inspect.signature(get_safety).parameters else get_safety()
        inner = ModelDecider(router=router, providers=providers, safety=safety, config=config)
        return MeteredDecider(inner, ledger=get_spend_ledger(), cache=get_decision_cache(), config=config)
    except (HTTPException, ProviderConfigError, AssistantModelUnavailable):
        return None
