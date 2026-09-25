"""Injected auth, storage and event-writing seams for tilo-api (ticket ST-3a round 3,
services/api/tests/API_ST3a.md). Real sign-in, Firestore and the harness are later tickets
(PRD 15.3); every route below takes a `Principal`, a `Store` and (where it emits events) an
`EventWriter` via FastAPI's dependency overrides, and production code raises
NotImplementedError until those land so a route can never run unauthenticated, against no
store, or write an event itself (PI-18: the harness is the only writer). `Store.pending_events`
(round 3) holds parts a writer failure could not land yet -- the writer being down must never
stop the kill switch itself from lowering autonomy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["owner", "team_lead", "approver", "viewer"]


@dataclass(frozen=True)
class Principal:
    """The test double for auth (real sign-in is a later ticket). One instance per request,
    supplied by overriding get_current_principal in tests via app.dependency_overrides."""

    user_id: str  # common.schema.json#/$defs/user_id
    role: Role
    world_id: str | None = None  # The one world this principal is a member of; None means no
    # membership anywhere. Every world route checks
    # principal.world_id == the path's world_id before it does
    # anything else with store.worlds -- a mismatch gets exactly
    # the same 404 as an unknown world_id (no membership oracle).
    domain: str | None = None  # team_lead's PRD 8.3 expert domain; None otherwise
    districts: tuple[str, ...] = ()  # districts this principal may see beyond "vis": "all":
    # a team_lead's domain districts, or a viewer's shared
    # scope. Ignored when role == "owner" (owner sees
    # everything, PRD 10.1).


@dataclass
class DistrictRecord:
    name: str
    summary: str


@dataclass
class WorldRecord:
    owner: str  # common.schema.json#/$defs/user_id
    owner_channels: tuple[
        str, ...
    ]  # common.schema.json#/$defs/channel values; the owner's enabled channels for kill-switch confirmations
    districts: dict[
        str, DistrictRecord | None
    ]  # district_id -> DistrictRecord, this world's full layout (owner's-eye view). A test may
    # store None or another malformed value under a key to prove the read routes fail
    # closed (treat it as hidden) rather than raising.
    run_id: str  # common.schema.json#/$defs/run_id: the world's current run, the harness's own
    # record; tilo-api reads this, it never invents one (PI-18).


@dataclass
class Store:
    """In-memory injected state (no Firestore this ticket). One instance built fresh per test
    and supplied by overriding get_store; a route handler mutates it in place, the same object
    the test holds, so a test can inspect the result without a second GET."""

    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    policies: dict[str, dict] = field(
        default_factory=dict
    )  # policy_id -> policy.schema.json record (mutated in place: level, changed_by, history).
    # A test may store a record missing "history", with "history" not a list, or with
    # "level" absent or not one of L0..L3, to prove a kill switch fails safe.
    policy_worlds: dict[str, str] = field(
        default_factory=dict
    )  # policy_id -> world_id whose event stream receives that policy's policy.changed events.
    # A policy_id absent from this map has "no world mapping" -- Stop-all/Pause still
    # lower it to L1 and route its event to the world the request was made against;
    # revoke (no world_id of its own) hands no event to any world.
    events: dict[str, list[dict]] = field(
        default_factory=dict
    )  # world_id -> event.schema.json records, append-only, oldest first (seq strictly
    # increasing, EV-10). Only EventWriter.append appends here; a route handler never does.
    pending_events: dict[str, list[dict]] = field(
        default_factory=dict
    )  # world_id -> event parts a mutating route built but EventWriter.append raised on (the
    # harness is unreachable): the level change itself is never rolled back for this. Flushed,
    # oldest first, on the next stop/pause call against the same world_id -- a part is removed
    # from here only once `append` returns for it, so it is written exactly once, never lost.


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3, PI-18). tilo-api builds an event *part* -- every
    event.schema.json field except v, id, seq, ts, world_id, run_id and trace -- and hands it
    here; a production implementation talks to the harness process."""

    def append(self, world_id: str, part: dict) -> dict:
        """part keys: type, actor, target, level, district, item, severity, credits, summary,
        cause, vis, authz, data (any key the caller has no value for is set to that field's
        schema-honest default). Returns the fully stamped event.schema.json record appended to
        store.events[world_id]."""
        ...


def get_current_principal() -> Principal:
    """Raises NotImplementedError in production until real sign-in lands; every test overrides
    this via app.dependency_overrides[get_current_principal]."""
    raise NotImplementedError


def get_store() -> Store:
    """Raises NotImplementedError in production until Firestore wiring lands; every test
    overrides this via app.dependency_overrides[get_store]."""
    raise NotImplementedError


def get_event_writer() -> EventWriter:
    """Raises NotImplementedError in production until the harness wiring lands; every test
    overrides this via app.dependency_overrides[get_event_writer]."""
    raise NotImplementedError
