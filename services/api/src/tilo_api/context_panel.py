"""CONTEXT-P2: the 03:00 caller-owned projection. Security review required before integration.
No directory listing, teammate identities, contract/event changes or writes. Every people
record still passes the existing oracle; ownership filters can only narrow its result."""

import json
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from tilo_people.access import AccessRequest, read
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.connectors_list import _optional_views, connectors_route
from tilo_api.people import _answer, _PeopleRoute, _writer
from tilo_api.people_access import request_parts
from tilo_api.people_pins import _Owners
from tilo_api.people_writes import Refusal
from tilo_api.skill_store import SkillStore
from tilo_api.skills_routes import _guarded
from tilo_api.worlds_list import list_worlds

router = APIRouter(route_class=_PeopleRoute)
MAX_ROWS = 200


def _project(record: dict, keys: tuple[str, ...]) -> dict:
    return {key: record[key] for key in keys if key in record}


def _rows(rows: list[dict]) -> dict:
    rows.sort(key=lambda row: (row.get("created_at", ""), row["id"]))
    return {"items": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


def _context(
    principal: deps.Principal,
    stores: PeopleStores,
    clock: Callable[[], str],
    owners: deps.SourceOwners,
    store: deps.Store,
    skills: SkillStore,
    registry: Any,
    views: Any,
) -> dict[str, Any]:
    w = _writer(principal, stores, clock)
    directory = w.directory()
    me = directory.record(w.actor)
    if me is None:
        raise Refusal(404, "not_found")
    response = list_worlds(limit=100, cursor=None, include_sample=None, principal=principal, store=store)
    worlds = json.loads(bytes(response.body))
    worlds["worlds"] = [row for row in worlds["worlds"] if row["world_id"] != deps.SAMPLE_WORLD_ID]
    owned = {wid for wid, world in store.worlds.items() if world.owner == w.actor and wid != deps.SAMPLE_WORLD_ID}

    def readable(kind, record, action="read_full"):
        if record.get("org_id") != w.org:
            return None
        parts = request_parts(
            stores,
            actor=w.actor,
            org_id=w.org,
            record_kind=kind,
            record_id=record["id"],
            now=w.now,
            source_owners=_Owners(owners),
        )
        return None if parts is None else read(AccessRequest(action=action, **parts), directory)

    items = {}
    # PE-16 has no creator/source selector. Existing org-local candidate scans are
    # filtered before oracle reads; neither a new index nor a wider read is authorised.
    for stored in stores.work_items.list(w.org):
        record = stored.record
        made = record.get("created_by", {})
        if record.get("owner") != w.actor and not (made.get("by") == "person" and made.get("ref") == w.actor):
            continue
        got = readable("work_item", record, "read_full" if record["owner"] == w.actor else "read_status")
        if got is not None:
            keys = (
                ("id", "title", "status", "due", "snoozed_until", "created_at")
                if record["owner"] == w.actor
                else ("id", "status")
            )
            items[record["id"]] = _project(got, keys)
    meetings = []
    for stored in stores.meetings.list(w.org, "owner", w.actor):
        record = stored.record
        if record.get("owner") == w.actor and (got := readable("meeting", record)) is not None:
            meetings.append(_project(got, ("id", "title", "status", "scheduled", "world_id", "created_at")))
    pins = {}
    for stored in stores.pins.list(w.org):
        record, source = stored.record, stored.record.get("source") or {}
        scope = record.get("scope") or {}
        mine = record.get("set_up_by") == w.actor or (scope.get("kind") == "personal" and scope.get("user") == w.actor)
        world_owned = source.get("kind") == "request" and source.get("ref") in owned
        if (mine or world_owned) and (got := readable("pinboard_item", record)) is not None:
            pins[record["id"]] = _project(got, ("id", "title", "body", "kind", "status", "url", "due", "created_at"))
    own_skills = _guarded(lambda: skills.list_for_owner(w.org, w.actor))
    return {
        "worlds": worlds,
        "work_items": _rows(list(items.values())),
        "meetings": _rows(meetings),
        "pins": _rows(list(pins.values())),
        "workspace": {
            "org_id": w.org,
            "role": me["org_role"],
            "connectors": [
                _project(row, ("id", "state", "state_known"))
                for row in connectors_route(principal, registry, views)["connectors"]
            ],
            "skills": [
                _project(row, ("id", "name", "status", "paused"))
                for row in own_skills
                if row.get("org_id") == w.org and row.get("owner") == w.actor and row.get("status") != "draft"
            ],
        },
        "unavailable": ["knowledge", "forecasts", "ledger", "routines", "notifications", "calendar"],
    }


@router.get("/v1/context")
def context_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
    owners: Annotated[deps.SourceOwners, Depends(deps.get_source_owners)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    skills: Annotated[SkillStore, Depends(deps.get_skill_store)],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
    views: Annotated[Any, Depends(_optional_views)],
) -> dict[str, Any]:
    return _answer(lambda: _context(principal, stores, clock, owners, store, skills, registry, views))
