"""Injected auth, storage and event-writing seams for tilo-api (ticket ST-3a round 4,
services/api/tests/API_ST3a.md). Real sign-in, Firestore and the harness are later tickets
(PRD 15.3); every route takes a `Principal`, a `Store` and (where it emits events) an
`EventWriter` via FastAPI dependency overrides. Production code raises NotImplementedError until
those land, so a route can never run unauthenticated, against no store, or write an event itself
(PI-18: the harness is the only writer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["owner", "team_lead", "approver", "viewer"]


@dataclass(frozen=True)
class Principal:
    """Test double for auth. One per request, via app.dependency_overrides[get_current_principal]."""

    user_id: str  # common.schema.json#/$defs/user_id
    role: Role
    world_id: str | None = None  # the one world this principal is a member of; a mismatch with
    # the path's world_id gets the same 404 as an unknown world (no membership oracle)
    domain: str | None = None  # team_lead's PRD 8.3 expert domain
    channel: str = "web"  # common.schema.json#/$defs/channel: the caller's own resolved session
    # channel (round 6). world.paused.data.channel is taken from here, never the request body,
    # so a caller cannot claim a confirmation channel it is not actually on.
    districts: tuple[str, ...] = ()  # visible beyond vis: "all"; ignored for role == "owner"


@dataclass
class DistrictRecord:
    name: str
    summary: str


@dataclass
class WorldRecord:
    owner: str  # common.schema.json#/$defs/user_id
    owner_channels: tuple[str, ...]  # common.schema.json#/$defs/channel, for stop-all confirmations
    districts: dict[str, DistrictRecord | None]  # district_id -> record; a malformed/None value
    # is a test proving the read routes fail closed (hidden) rather than raising
    run_id: str  # common.schema.json#/$defs/run_id: read, never invented (PI-18)
    paused: bool = False  # round-4: set True the moment Pause-all first actually pauses this
    # world, under the same lock that serializes its mutation; the one thing that dedupes
    # world.paused (never inferred from whether a policy changed this call). Write-only: no
    # route this ticket adds reads it back out or ever clears it.


@dataclass
class Store:
    """In-memory injected state; one instance per test, mutated in place by route handlers."""

    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    policies: dict[str, dict] = field(default_factory=dict)  # policy_id -> policy.schema.json
    # record, mutated in place (level, changed_by, history). A test may store one with a
    # missing/malformed history or level to prove a kill switch fails safe.
    policy_worlds: dict[str, str] = field(default_factory=dict)  # policy_id -> world_id whose
    # stream receives that policy's policy.changed (policy.schema.json carries no world_id of
    # its own, PRD 15.3). Absent = "no mapping": stop/pause route to the request's own world;
    # revoke emits no event.
    events: dict[str, list[dict]] = field(default_factory=dict)  # world_id -> event.schema.json
    # records, append-only (EV-10). Only EventWriter.append writes here.
    pending_events: dict[str, list[dict]] = field(default_factory=dict)  # world_id -> parts a
    # writer failure could not land (the level change itself is never rolled back). Flushed
    # oldest-first by the next mutating call that touches that world; a part leaves this dict
    # only once `append` returns for it, so it is written exactly once, never lost.


class EventWriter(Protocol):
    """The single writer of events (PRD 15.3, PI-18): tilo-api builds an unstamped event *part*
    and hands it here; production talks to the harness process."""

    def append(self, world_id: str, part: dict) -> dict:
        """part keys: type, actor, target, level, district, item, severity, credits, summary,
        cause, vis, authz, data. Returns the fully stamped record appended to store.events."""
        ...


def get_current_principal() -> Principal:
    raise NotImplementedError


def get_store() -> Store:
    raise NotImplementedError


def get_event_writer() -> EventWriter:
    raise NotImplementedError
