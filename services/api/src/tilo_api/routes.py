"""Kill switches (FR-HIL-07, PI-13, PI-18) and roles/redaction (FR-HIL-09, SEC-07), per the exact
shape in services/api/tests/API_ST3a.md (round 4). Only the policy owner stops, pauses or
revokes; a non-member/non-owner gets the same 404 as unknown (no oracle). Stop-all/Pause-all
lower every targeted policy before any writer call, keep lowering autonomy when the writer is
down (a failed part is queued in Store.pending_events and flushed, per touched world, by the
next mutating call), and use per-world locks so concurrent calls never double-write and one
world's writer latency never blocks another's. The two GET routes rebuild every kept event by
allowlisting -- never copying the stored event forward -- redacting `data` recursively at any
depth.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tilo_api.deps import EventWriter, Principal, Store, WorldRecord, get_current_principal, get_event_writer, get_store
from tilo_api.events import now, policy_changed_part, policy_vis, world_paused_part

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
_EMPTY_TRACE = {
    k: None for k in ("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref")
}

# Round-4 fix (qa, biggest): per-world locks, not one global lock, so a Stop-all against world A
# never waits on world B's writer latency. `_locks_guard` only ever protects the dict lookup
# itself, never held during a route's own work.
_locks_guard = threading.Lock()
_world_locks: dict[str, threading.Lock] = {}


def _lock_for(world_id: str) -> threading.Lock:
    with _locks_guard:
        return _world_locks.setdefault(world_id, threading.Lock())


def _locked(world_ids: list[str]) -> ExitStack:
    """Acquires every touched world's lock, sorted, so two calls sharing worlds never deadlock."""
    stack = ExitStack()
    for w in sorted(set(world_ids)):
        stack.enter_context(_lock_for(w))
    return stack


def _is_owner(principal: Principal, owner: str) -> bool:
    return principal.role == "owner" and principal.user_id == owner


def _require_member_world(principal: Principal, store: Store, world_id: str) -> WorldRecord:
    """A membership mismatch (wrong world or none) gets the same 404 as an unknown world_id."""
    if principal.world_id != world_id:
        raise HTTPException(status_code=404)
    world = store.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404)
    return world


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


def _redact_district(value: Any, safe_districts: tuple[str, ...]) -> Any:
    if isinstance(value, str) and _DISTRICT_RE.match(value):
        return value if value in safe_districts else None
    return value


def _redact_value(value: Any, key: str | None, id_map: dict[str, str], safe_districts: tuple[str, ...]) -> Any:
    """Walks `data` recursively (any dict/list depth): message_ref always null, a ULID-shaped
    leaf remapped-or-nulled like `cause`, a district-shaped leaf nulled when hidden."""
    if isinstance(value, dict):
        return {k: _redact_value(v, k, id_map, safe_districts) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v, None, id_map, safe_districts) for v in value]
    if isinstance(value, str):
        if key == "message_ref":
            return None
        if _ULID_RE.match(value):
            return id_map.get(value)
        return _redact_district(value, safe_districts)
    return value


def _owner_event_view(event: dict) -> dict:
    return {k: event[k] for k in _REQUIRED_EVENT_KEYS if k not in ("v", "world_id", "run_id", "item", "trace")} | {
        "trace": event["trace"]
    }


def _scoped_event_view(event: dict, seq: int, id_map: dict[str, str], safe_districts: tuple[str, ...]) -> dict:
    trace_value = event.get("trace")
    trace = dict(trace_value) if isinstance(trace_value, dict) else dict(_EMPTY_TRACE)
    trace["archive_ref"] = None
    cause = event["cause"]
    vis = event["vis"]
    return {
        "seq": seq,
        "id": f"v{seq}",
        "ts": event["ts"],
        "type": event["type"],
        "actor": _redact_district(event["actor"], safe_districts),
        "target": _redact_district(event["target"], safe_districts),
        "level": event["level"],
        "severity": event["severity"],
        "credits": event["credits"],
        "summary": event["summary"],
        "authz": event["authz"],
        "district": _redact_district(event["district"], safe_districts),
        "cause": id_map.get(cause) if cause is not None else None,
        "vis": [d for d in vis if d in safe_districts] if isinstance(vis, list) else vis,
        "data": _redact_value(event["data"], None, id_map, safe_districts),
        "trace": trace,
    }


def _write_parts(store: Store, writer: EventWriter, items: list[tuple[str, dict]]) -> None:
    """Attempts every (world_id, part) concurrently, not sequentially, so N writer calls take
    ~O(latency) not O(N * latency) (round-4 qa: the 5s budget must hold against a slow writer
    too). A part whose write raises is queued pending; a success already landed via the writer."""
    if not items:
        return

    def attempt(item: tuple[str, dict]) -> None:
        world_id, part = item
        try:
            writer.append(world_id, part)
        except Exception:
            store.pending_events.setdefault(world_id, []).append(part)

    with ThreadPoolExecutor(max_workers=min(64, len(items))) as pool:
        list(pool.map(attempt, items))


def _touched_worlds(store: Store, world_id: str, owner: str) -> list[str]:
    """The request's own world plus every owned policy's mapped world (round-4: pending/flush
    must count and reach every world a call's own policies could route an event to)."""
    touched = {world_id}
    for policy_id, policy in store.policies.items():
        if isinstance(policy, dict) and policy.get("owner") == owner:
            touched.add(store.policy_worlds.get(policy_id, world_id))
    return list(touched)


def _flush_touched(store: Store, writer: EventWriter, touched: list[str]) -> None:
    items: list[tuple[str, dict]] = []
    for w in touched:
        pending = store.pending_events.get(w)
        if pending:
            items.extend((w, part) for part in pending)
            store.pending_events[w] = []
    _write_parts(store, writer, items)


def _stop_all_owner_policies(
    store: Store, owner: str, requested_world_id: str, change: str, at: str
) -> tuple[int, int, list[tuple[str, dict]]]:
    """PI-13/PI-18: plan every owned policy first, then apply -- never half-applies, never 500s.
    L0 stays untouched. A policy is skipped as already_l1 only when *provably* consistent (level
    == "L1" and its own history agrees too, round-3 "no silent history repair"); anything else
    (including a missing/malformed level, or an L1 whose history disagrees) is lowered with one
    history entry and one policy.changed, vis computed against its own target world (round-4)."""
    plan: list[tuple[str, dict, str]] = []
    already_l1 = 0
    for policy_id, policy in store.policies.items():
        if not isinstance(policy, dict) or policy.get("owner") != owner:
            continue
        level = policy.get("level")
        if level == "L0":
            continue
        history = policy.get("history")
        consistent_l1 = (
            level == "L1"
            and isinstance(history, list)
            and bool(history)
            and isinstance(history[-1], dict)
            and history[-1].get("level") == "L1"
        )
        if consistent_l1:
            already_l1 += 1
            continue
        plan.append((policy_id, policy, store.policy_worlds.get(policy_id, requested_world_id)))

    new_parts: list[tuple[str, dict]] = []
    for policy_id, policy, target_world_id in plan:
        history = policy.get("history")
        history = history if isinstance(history, list) else []
        history.append({"by": owner, "at": at, "change": change, "level": "L1"})
        policy["history"] = history
        policy["level"] = "L1"
        policy["changed_by"] = {"by": owner, "at": at}
        target_world = store.worlds.get(target_world_id)
        vis = policy_vis(policy, target_world.districts if target_world else None)
        new_parts.append(
            (target_world_id, policy_changed_part(policy_id=policy_id, change=change, owner=owner, at=at, vis=vis))
        )

    return len(plan), already_l1, new_parts


class PauseRequest(BaseModel):
    channel: Literal["web", "mobile_web", "whatsapp", "email"] | None = None


@router.post("/worlds/{world_id}/autopilot/stop")
def stop_autopilot(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
) -> JSONResponse:
    world = _require_member_world(principal, store, world_id)
    if not _is_owner(principal, world.owner):
        raise HTTPException(status_code=403)

    at = now()
    touched = _touched_worlds(store, world_id, world.owner)
    with _locked(touched):
        _flush_touched(store, writer, touched)
        stopped, already_l1, new_parts = _stop_all_owner_policies(store, world.owner, world_id, "stop_all", at)
        _write_parts(store, writer, new_parts)
        pending = sum(len(store.pending_events.get(w, [])) for w in touched)

    result = {
        "stopped": stopped,
        "already_l1": already_l1,
        "confirmations": [{"channel": c} for c in world.owner_channels],
        "pending": pending,
    }
    return JSONResponse(content=result, status_code=202 if pending else 200)


@router.post("/worlds/{world_id}/pause")
def pause_world(
    world_id: str,
    body: PauseRequest = PauseRequest(),
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
) -> JSONResponse:
    world = _require_member_world(principal, store, world_id)
    if not _is_owner(principal, world.owner):
        raise HTTPException(status_code=403)

    at = now()
    touched = _touched_worlds(store, world_id, world.owner)
    with _locked(touched):
        _flush_touched(store, writer, touched)
        stopped, already_l1, new_parts = _stop_all_owner_policies(store, world.owner, world_id, "stop_all", at)
        if not world.paused:
            world.paused = True
            new_parts.append((world_id, world_paused_part(world_id=world_id, owner=world.owner, channel=body.channel)))
        _write_parts(store, writer, new_parts)
        pending = sum(len(store.pending_events.get(w, [])) for w in touched)

    result = {"stopped": stopped, "already_l1": already_l1, "paused": True, "pending": pending}
    return JSONResponse(content=result, status_code=202 if pending else 200)


@router.post("/policies/{policy_id}/revoke")
def revoke_policy(
    policy_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
) -> dict:
    policy = store.policies.get(policy_id)
    if not isinstance(policy, dict) or principal.user_id != policy.get("owner"):
        raise HTTPException(status_code=404)  # same 404 for unknown and not-yours -- no oracle

    owner = policy["owner"]
    at = now()
    history = policy.get("history")
    history = history if isinstance(history, list) else []
    history.append({"by": owner, "at": at, "change": "revoked", "level": "L1"})
    policy["history"] = history
    policy["level"] = "L1"
    policy["changed_by"] = {"by": owner, "at": at}

    target_world_id = store.policy_worlds.get(policy_id)
    if target_world_id is not None:
        with _locked([target_world_id]):
            target_world = store.worlds.get(target_world_id)
            vis = policy_vis(policy, target_world.districts if target_world else None)
            part = policy_changed_part(policy_id=policy_id, change="revoked", owner=owner, at=at, vis=vis)
            _write_parts(store, writer, [(target_world_id, part)])

    return {"policy_id": policy_id, "level": "L1"}


@router.get("/worlds/{world_id}/events")
def get_world_events(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    world = _require_member_world(principal, store, world_id)
    is_owner = _is_owner(principal, world.owner)
    safe_districts = _safe_districts(principal.districts)

    well_formed = [e for e in store.events.get(world_id, []) if not _is_malformed_event(e)]
    visible = [e for e in well_formed if _visible(is_owner, e.get("vis"), safe_districts)]

    if is_owner:
        return {"events": [_owner_event_view(e) for e in visible]}

    id_map = {e["id"]: f"v{i + 1}" for i, e in enumerate(visible)}
    events = [_scoped_event_view(e, i + 1, id_map, safe_districts) for i, e in enumerate(visible)]
    return {"events": events}


@router.get("/worlds/{world_id}")
def get_world(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    world = _require_member_world(principal, store, world_id)
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
