"""CONTEXT-P2: read-only context, narrowed by server records and the people oracle.
World loads never settle runs. Demo sessions resolve no durable sources."""

from collections.abc import Callable, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from tilo_people._schema import valid
from tilo_people.access import AccessRequest, read
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.connectors_list import _optional_views, connectors_route
from tilo_api.people import _answer, _PeopleRoute, _writer
from tilo_api.people_access import request_parts
from tilo_api.people_pins import _Owners
from tilo_api.people_quotes import MAX_HISTORY
from tilo_api.people_writes import Refusal
from tilo_api.skill_store import SkillStore
from tilo_api.skills_routes import _guarded
from tilo_api.worlds_list import DEFAULT_LIMIT, _item, _position

router = APIRouter(route_class=_PeopleRoute)
MAX_ROWS = 200


def _project(record: dict, keys: tuple[str, ...]) -> dict:
    return {key: record[key] for key in keys if key in record}


def _rows(rows: list[dict], truncated: bool = False) -> dict:
    rows.sort(key=lambda row: (row.get("created_at", ""), row["id"]))
    return {"items": rows[:MAX_ROWS], "truncated": truncated or len(rows) > MAX_ROWS}


def _empty() -> dict[str, Any]:
    return {
        "worlds": {"worlds": [], "truncated": False},
        **{key: {"items": [], "truncated": False} for key in ("work_items", "meetings", "pins")},
        "workspace": {"org_id": deps.ORG_ID, "role": None, "connectors": [], "skills": []},
        "unavailable": ["knowledge", "forecasts", "ledger", "routines", "notifications", "calendar"],
    }


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
    if principal.demo_session:
        return _empty()
    w = _writer(principal, stores, clock)
    directory = w.directory()
    me = directory.record(w.actor)
    if me is None:
        raise Refusal(404, "not_found")
    # Only the verified caller and named membership assigners; never list people.
    facts = [me]
    for membership in me["memberships"][:MAX_ROWS]:
        assigner = stores.persons.get(w.org, membership["assigned_by"]["by"])
        if assigner is not None and isinstance(assigner.record, Mapping) and assigner.record.get("id") != w.actor:
            facts.append(assigner.record)
    directory = Directory.of({fact["id"]: fact for fact in facts}.values())
    teams = [m["team"] for m in me["memberships"][:MAX_ROWS] if directory.is_member(w.actor, m["team"], w.now)]
    if principal.world_id is None:
        store.load_owner(w.actor, settle=False)
    else:
        store.load_world(principal.world_id, settle=False)
    accessible = {}
    for wid in store.worlds:
        if wid == deps.SAMPLE_WORLD_ID:
            continue
        try:
            accessible[wid] = deps.member_world(principal, store, wid)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
    ordered = sorted(accessible, key=lambda wid: _position(principal, store, wid, accessible[wid]), reverse=True)
    worlds = {
        "worlds": [_item(principal, store, wid, accessible[wid]) for wid in ordered[:DEFAULT_LIMIT]],
        "truncated": len(ordered) > DEFAULT_LIMIT,
    }

    def readable(kind, record, action="read_full"):
        if not isinstance(record, dict):
            return None
        history = record.get("history", [])
        if not isinstance(history, list) or len(history) > MAX_HISTORY or not valid(f"{kind}.schema.json", record):
            return None
        if record.get("org_id") != w.org:
            return None
        try:
            parts = request_parts(
                stores,
                actor=w.actor,
                org_id=w.org,
                record_kind=kind,
                record_id=record["id"],
                now=w.now,
                source_owners=_Owners(owners),
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        return None if parts is None else read(AccessRequest(action=action, **parts), directory)

    overflow = {"work_items": False, "pins": False, "meetings": False}

    def candidates(name, selectors):
        rows = {}
        for field, value in selectors:
            found = getattr(stores, name).list_bounded(w.org, field, value, limit=MAX_ROWS + 1)
            overflow[name] |= len(found) > MAX_ROWS
            for stored in found[:MAX_ROWS]:
                record = stored.record
                if isinstance(record, dict) and isinstance(record.get("id"), str):
                    rows[record["id"]] = record
        return rows.values()

    items = {}
    selectors = [("owner", w.actor), ("created_by.ref", w.actor)]
    selectors.extend(("source.ref", wid) for wid in ordered[:DEFAULT_LIMIT])
    for record in candidates("work_items", selectors):
        owner = record.get("owner")
        made = record.get("created_by", {})
        if not isinstance(made, dict):
            continue
        if owner != w.actor and not (made.get("by") == "person" and made.get("ref") == w.actor):
            continue
        got = readable("work_item", record, "read_full" if owner == w.actor else "read_status")
        if got is not None:
            keys = (
                ("id", "title", "status", "due", "snoozed_until", "created_at", "flagged")
                if owner == w.actor
                else ("id", "status")
            )
            items[record["id"]] = _project(got, keys)
    meetings = []
    for record in candidates("meetings", [("owner", w.actor)]):
        if record.get("owner") == w.actor and (got := readable("meeting", record)) is not None:
            meetings.append(_project(got, ("id", "title", "status", "scheduled", "world_id", "created_at")))
    pins = {}
    for record in candidates("pins", [("scope.user", w.actor), *(("scope.team", team) for team in teams)]):
        scope = record.get("scope") or {}
        if not isinstance(scope, dict):
            continue
        mine = scope.get("kind") == "personal" and scope.get("user") == w.actor
        team = scope.get("team")
        team_member = (
            scope.get("kind") == "team" and isinstance(team, str) and directory.is_member(w.actor, team, w.now)
        )
        if (mine or team_member) and (got := readable("pinboard_item", record)) is not None:
            pins[record["id"]] = _project(
                got, ("id", "title", "body", "kind", "status", "url", "due", "created_at", "flagged")
            )
    own_skills = _guarded(lambda: skills.list_for_owner(w.org, w.actor))
    return {
        "worlds": worlds,
        "work_items": _rows(list(items.values()), overflow["work_items"]),
        "meetings": _rows(meetings, overflow["meetings"]),
        "pins": _rows(list(pins.values()), overflow["pins"]),
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
                if isinstance(row, dict)
                and row.get("org_id") == w.org
                and row.get("owner") == w.actor
                and row.get("status") != "draft"
            ][:MAX_ROWS],
        },
        "unavailable": ["knowledge", "forecasts", "ledger", "routines", "notifications", "calendar"],
    }


@router.get("/v1/context")
def context_route(
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
) -> dict[str, Any]:
    if principal.demo_session:
        return _empty()

    def resolve(factory):
        provider = request.app.dependency_overrides.get(factory, factory)
        if provider is factory and factory in (deps.get_people_stores, deps.get_source_owners, deps.get_store):
            return provider(request)
        return provider()

    return _answer(
        lambda: _context(
            principal,
            resolve(deps.get_people_stores),
            resolve(deps.get_clock),
            resolve(deps.get_source_owners),
            resolve(deps.get_store),
            resolve(deps.get_skill_store),
            resolve(deps.get_connector_registry),
            _optional_views(request),
        )
    )
