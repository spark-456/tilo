"""GET routes rebuild every kept event by allowlisting, never copying it forward (round 5/6): for
a non-owner, an event naming a hidden district anywhere -- `district`, `target`, `actor`, or any
`data` leaf or key, at any depth -- is dropped whole, never returned with a field blanked. `data`
is redacted recursively with a depth guard so arbitrarily deep nesting fails closed (dropped)
instead of a 500; the owner's view never walks `data` at all.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from tilo_people.stores import PeopleStores

from tilo_api.deps import (
    Principal,
    Store,
    get_clock,
    get_current_principal,
    get_people_provider,
    get_store,
    readable_world,
    world_layout,
)
from tilo_api.layout import visible_layout

router = APIRouter()

_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
_DISTRICT_RE = re.compile(r"^D[0-9]{1,4}$")
_REQUIRED_EVENT_KEYS = (
    "v",
    "id",
    "seq",
    "ts",
    "world_id",
    "run_id",
    "type",
    "actor",
    "target",
    "level",
    "district",
    "item",
    "severity",
    "credits",
    "summary",
    "cause",
    "vis",
    "authz",
    "data",
    "trace",
)
_TRACE_KEYS = ("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref")
_EMPTY_TRACE = dict.fromkeys(_TRACE_KEYS)
_MAX_DATA_DEPTH = 60  # a scoped viewer fails closed (event dropped) past this; the owner never walks data at all


def _is_owner(principal: Principal, owner: str) -> bool:
    return principal.role == "owner" and principal.user_id == owner


def _safe_districts(value: Any) -> tuple[str, ...]:
    """A Principal.districts that is not a list/tuple/set (e.g. a bare str) is never substring
    matched -- treated as no districts."""
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(d for d in value if isinstance(d, str))
    return ()


def _visible(is_owner: bool, vis: Any, safe_districts: tuple[str, ...]) -> bool:
    if is_owner or vis == "all":
        return True
    if isinstance(vis, list):
        return any(d in safe_districts for d in vis)
    return False


def _district_fields(record: Any) -> tuple[str, str] | None:
    name, summary = getattr(record, "name", None), getattr(record, "summary", None)
    return (name, summary) if isinstance(name, str) and isinstance(summary, str) else None


def _is_malformed_event(event: Any) -> bool:
    if not isinstance(event, dict) or any(k not in event for k in _REQUIRED_EVENT_KEYS):
        return True
    if not isinstance(event["id"], str):
        return True
    cause = event["cause"]
    return cause is not None and not isinstance(cause, str)


def _hides_district(value: Any, safe_districts: tuple[str, ...]) -> bool:
    return isinstance(value, str) and bool(_DISTRICT_RE.match(value)) and value not in safe_districts


def _data_hides_district(value: Any, safe_districts: tuple[str, ...], depth: int = 0) -> bool:
    """Recurses at any dict/list depth over both keys and values; too-deep data fails closed
    (treated as hiding a district) rather than risking a RecursionError."""
    if depth > _MAX_DATA_DEPTH:
        return True
    if isinstance(value, dict):
        return any(
            _hides_district(k, safe_districts) or _data_hides_district(v, safe_districts, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return any(_data_hides_district(v, safe_districts, depth + 1) for v in value)
    return _hides_district(value, safe_districts)


def _event_hides_district(event: dict, safe_districts: tuple[str, ...]) -> bool:
    """A non-owner never receives an event naming a hidden district anywhere -- dropped whole,
    never returned with a field nulled."""
    return (
        _hides_district(event["district"], safe_districts)
        or _hides_district(event["target"], safe_districts)
        or _hides_district(event["actor"], safe_districts)
        or _data_hides_district(event["data"], safe_districts)
    )


def _redact_data(value: Any, key: str | None, id_map: dict[str, str]) -> Any:
    """Within an already-kept event, message_ref is always null and a ULID-shaped value or dict
    key is remapped to its named event's view-local id (or dropped, for a key, since a JSON key
    cannot be null) when that event survived filtering, else nulled/dropped."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            new_key = k
            if isinstance(k, str) and _ULID_RE.match(k):
                if k not in id_map:
                    continue
                new_key = id_map[k]
            result[new_key] = _redact_data(v, new_key, id_map)
        return result
    if isinstance(value, list):
        return [_redact_data(v, None, id_map) for v in value]
    if isinstance(value, str):
        if key == "message_ref":
            return None
        if _ULID_RE.match(value):
            return id_map.get(value)
    return value


def _owner_event_view(event: dict) -> dict:
    """The full record as stored (PRD 15.3), `v`, `world_id`, `run_id` and `item` included (CL-INT-4)."""
    return {k: event[k] for k in _REQUIRED_EVENT_KEYS}


def _allowlisted_trace(trace_value: Any) -> dict:
    """A scoped view's trace is rebuilt from exactly event.schema.json#/$defs/trace's seven keys
    -- any extra (schema-invalid) key a stored value happens to carry is dropped, never copied
    forward -- with archive_ref always null (it names a raw-archive position, PRD 13.2)."""
    source = trace_value if isinstance(trace_value, dict) else _EMPTY_TRACE
    trace = {k: source.get(k) for k in _TRACE_KEYS}
    trace["archive_ref"] = None
    return trace


def _scoped_event_view(event: dict, seq: int, id_map: dict[str, str], safe_districts: tuple[str, ...]) -> dict:
    cause = event["cause"]
    vis = event["vis"]
    return {
        "seq": seq,
        "id": f"v{seq}",
        "ts": event["ts"],
        "type": event["type"],
        "actor": event["actor"],
        "target": event["target"],
        "level": event["level"],
        "severity": event["severity"],
        "credits": event["credits"],
        "summary": event["summary"],
        "authz": event["authz"],
        "district": event["district"],
        "cause": id_map.get(cause) if cause is not None else None,
        "vis": [d for d in vis if d in safe_districts] if isinstance(vis, list) else vis,
        "data": _redact_data(event["data"], None, id_map),
        "trace": _allowlisted_trace(event.get("trace")),
    }


@router.get("/worlds/{world_id}/events")
def get_world_events(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    people: Callable[[], PeopleStores | None] = Depends(get_people_provider),
    clock: Callable[[], str] = Depends(get_clock),
) -> JSONResponse:
    world, principal = readable_world(principal, store, people, clock, world_id)  # a team reader is a derived Viewer
    is_owner = _is_owner(principal, world.owner)
    if is_owner:
        store.settle(world_id)  # only after the checks: a restart's queued events and its `world.failed` (ADR-0026 5)
    safe_districts = _safe_districts(principal.districts)

    well_formed = [e for e in store.events.get(world_id, []) if not _is_malformed_event(e)]
    visible = [e for e in well_formed if _visible(is_owner, e.get("vis"), safe_districts)]

    if is_owner:
        # A JSONResponse (stdlib json, not FastAPI's pydantic-based response serialization,
        # which has its own much shallower recursion/depth guard): the owner's data is returned
        # exactly as stored, however deeply nested, and must not 500 either.
        return JSONResponse(content={"events": [_owner_event_view(e) for e in visible]})

    surviving = [e for e in visible if not _event_hides_district(e, safe_districts)]
    id_map = {e["id"]: f"v{i + 1}" for i, e in enumerate(surviving)}
    events = [_scoped_event_view(e, i + 1, id_map, safe_districts) for i, e in enumerate(surviving)]
    return JSONResponse(content={"events": events})


@router.get("/worlds/{world_id}/layout")
def get_world_layout(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    people: Callable[[], PeopleStores | None] = Depends(get_people_provider),
    clock: Callable[[], str] = Depends(get_clock),
) -> JSONResponse:
    """FR-WLD-05, CL-INT-4: the run's layout, never invented: 404 until the run has built one. The owner gets all
    of it; anyone else only what their districts show (`visible_layout`), and 404 when that is nothing."""
    world, principal = readable_world(principal, store, people, clock, world_id)
    layout = world_layout(store, world_id)
    if layout is None:
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    if not _is_owner(principal, world.owner):
        layout = visible_layout(layout, _safe_districts(principal.districts))
        if layout is None:
            raise HTTPException(status_code=404, detail="Tilo could not find that.")
    return JSONResponse(content=copy.deepcopy(layout))


@router.get("/worlds/{world_id}")
def get_world(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    people: Callable[[], PeopleStores | None] = Depends(get_people_provider),
    clock: Callable[[], str] = Depends(get_clock),
) -> dict:
    world, principal = readable_world(principal, store, people, clock, world_id)
    is_owner = _is_owner(principal, world.owner)
    safe_districts = _safe_districts(principal.districts)

    districts = []
    has_hidden = False
    for district_id, record in world.districts.items():
        fields = _district_fields(record)
        if fields is None or not _visible(is_owner, [district_id], safe_districts):
            has_hidden = True
            continue
        name, summary = fields
        districts.append({"id": district_id, "name": name, "summary": summary})
    return {"world_id": world_id, "districts": districts, "has_hidden_districts": has_hidden}
