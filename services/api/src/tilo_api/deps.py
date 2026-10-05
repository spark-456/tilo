"""Injected auth, storage and event-writer seams for tilo-api (FR-HIL-09/SEC-07 roles and
redaction, FR-HIL-07 kill switches, services/api/tests/API_ST3a.md). Real sign-in, Firestore and
the harness are later tickets (PRD 15.3); every route takes a `Principal`, a `Store` and, for the
three that emit events, an `EventWriter` via FastAPI dependency overrides. Production code raises
NotImplementedError until those land, so a route can never run unauthenticated or against no
store or writer.

`Store.dispatch_state` is FR-HIL-07's own per-world lock and per-policy lock bookkeeping
(services/api/src/tilo_api/dispatch.py): it lives on the Store instance itself, never a
module-level dict keyed by world_id alone, so two Store instances that happen to use the same
world_id string never share lock state.
"""

from __future__ import annotations

import functools
import logging
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from fastapi import HTTPException
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.registry import ConnectorRegistry, load_registry
from tilo_harness.executor import DefaultUnitRunner
from tilo_harness.skills import SkillRegistry
from tilo_metering.flags import FlagStore, process_flags
from tilo_planning.compiler import PlanInputs, compile_plan
from tilo_planning.memory import InMemoryPreferenceStore, MemoryLookup
from tilo_planning.questions import Question
from tilo_providers.config import ProviderConfigError, ProvidersConfig, load_providers_config, resolve_models_path
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.router import Router
from tilo_providers.safety import build_safety_provider

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


class EventRejected(Exception):
    """Raised by EventWriter.append when a caller resends an `id` already committed for that
    world with genuinely different content (EV-10 conflict, never a silent overwrite)."""


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3). Every event tilo-api hands here carries its own
    stable `id` (a ULID), built once when the part is enqueued and resent unchanged on every
    retry -- the sole idempotency key `append` dedupes on (issue #46 / EV-10), never raw content
    and never which writer object happens to receive the call. `seq`, `ts`, `run_id` and `trace`
    remain writer-only.

    A writer that wraps the harness `WorldWriter` should also expose an optional `reopen()`: the
    dispatcher calls it after a failed append, before the same event is resent, so a stale lease
    or an ambiguous commit (issue #55 item 2) recovers instead of answering WriterBusy forever."""

    def append(self, world_id: str, event: dict) -> dict:
        """Returns the committed event.schema.json record (the existing one, unchanged, on an
        idempotent-by-id retry); raises EventRejected on a same-id/different-content conflict."""
        ...


def get_current_principal() -> Principal:
    raise NotImplementedError


def get_store() -> Store:
    raise NotImplementedError


def get_event_writer() -> EventWriter:
    raise NotImplementedError


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


def get_router() -> Router:
    """Every model call goes through the provider layer's Router (PL-01); it replays recordings unless the
    user turned live mode on (EFF-01)."""
    try:
        return Router(providers_config(), fixtures_dir=FIXTURES_DIR)
    except ProviderConfigError as exc:
        logger.warning("model router unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="The model router is not configured.") from exc


def get_safety() -> SafetyProvider:
    """PRD 16.3 item 2: built from the `safety` role on every call; no role, or a provider the factory refuses
    (the fake when live or deployed), closes the screened routes with 503."""
    try:
        return build_safety_provider(providers_config(), fixtures_dir=FIXTURES_DIR)
    except ProviderConfigError as exc:
        logger.warning("safety provider unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="No safety provider is configured; nothing is screened, so nothing is accepted."
        ) from exc


# --- the run seams (CL-INT-2, services/api/tests/API_CL_INT_2.md); each default is the production wiring (BQ-90) ---


def _no_plan_compiler(*, brief: dict, approach: dict, budget_cap: float, context: Any = None) -> dict:
    raise NotImplementedError("no `director` role is configured, so no plan can be compiled and no run starts")


def get_plan_compiler() -> Callable[..., dict]:
    """`compile(*, brief, approach, budget_cap, context) -> PlanGraph` (FR-INT-09). The Director drafts it through
    the Router and `validate_plan` decides (BQ-90); with no `director` role in the provider config it refuses."""
    if "director" not in providers_config().roles:
        return _no_plan_compiler
    router = get_router()

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


def _worker_models() -> Mapping[str, Any]:
    router = get_router()
    return {role: _RoleModel(router, role) for role in ("specialist", "writer", "verifier")}


def get_unit_runner() -> Any:
    return DefaultUnitRunner(cast(Any, _worker_models()))


def get_must_ask_providers() -> Mapping[str, Any]:
    """The models `MustAsk` judges a unit with (FR-AGT-05), keyed by the unit's role; always the Router's roles."""
    return _worker_models()


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
def get_outbox_store() -> InMemoryOutboxStore:
    return InMemoryOutboxStore()  # the process's own until the Firestore store lands


REPLAY_ONLY_MESSAGE = "This link is replay-only right now: new work is paused; finished runs can still be replayed."


class ReplayOnly(Exception):
    """NFR-24: the answer is 503 with `replay_only: true` beside the text (tilo_api.app's handler), the labelled
    replay offer."""


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
