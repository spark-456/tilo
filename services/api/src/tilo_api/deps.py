"""Injected auth and storage seams for tilo-api (ticket FR-HIL-09/SEC-07,
services/api/tests/API_ST3a.md). Real sign-in and Firestore are later tickets (PRD 15.3); every
route takes a `Principal` and a `Store` via FastAPI dependency overrides. Production code raises
NotImplementedError until those land, so a route can never run unauthenticated or against no
store.

Split out of the ST-3a kill-switch-and-redaction branch (FR-HIL-07): only the shapes the roles
and redaction routes (`tilo_api.redaction`) need are kept here. FR-HIL-07 adds back the
event-writing seam (`EventWriter`/`get_event_writer`) and the kill-switch fields of `WorldRecord`
and `Store` it needs for itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Role = Literal["owner", "team_lead", "approver", "viewer"]


@dataclass(frozen=True)
class Principal:
    """Test double for auth. One per request, via app.dependency_overrides[get_current_principal]."""

    user_id: str  # common.schema.json#/$defs/user_id
    role: Role
    world_id: str | None = None  # the one world this principal is a member of; a mismatch with
    # the path's world_id gets the same 404 as an unknown world (no membership oracle)
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


@dataclass
class Store:
    """In-memory injected state; one instance per test, mutated in place by route handlers."""

    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    events: dict[str, list[dict]] = field(default_factory=dict)  # world_id -> event.schema.json
    # records, append-only (EV-10), read-only from these routes' point of view.


def get_current_principal() -> Principal:
    raise NotImplementedError


def get_store() -> Store:
    raise NotImplementedError
