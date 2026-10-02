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

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

Role = Literal["owner", "team_lead", "approver", "viewer"]
Channel = Literal["web", "mobile_web", "whatsapp", "email"]

logger = logging.getLogger("tilo_api.deps")
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_PART_WRITE_DEADLINE_S = 0.5
_DEFAULT_ABANDON_AFTER_S = 3.0


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
    owner_channels: tuple[str, ...] = ("web", "whatsapp", "email")  # kill-switch confirmations
    run_id: str = "r_village_basic_1"  # the world's current run; tilo-api reads this, never invents it
    paused: bool = False  # true once Pause all has actually paused this world (PRD 9.4 honesty:
    # only ever true together with a world.paused event queued or committed somewhere)


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


def _dispatch_config(key: str, default: float) -> float:
    """A positive finite number from config/dispatch.yaml; anything else logs and uses the default."""
    try:
        import yaml

        raw = yaml.safe_load((_REPO_ROOT / "config" / "dispatch.yaml").read_text(encoding="utf-8"))
        value = float(raw["dispatch"][key])
    except Exception as exc:
        logger.warning("dispatch config %s unreadable (%s); using default %s", key, exc, default)
        return default
    if not (math.isfinite(value) and value > 0):
        logger.warning("dispatch config %s=%r is not a positive finite number; using default %s", key, value, default)
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
