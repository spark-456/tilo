"""Kill switches (FR-HIL-07, PI-13, PI-18) and roles/redaction (FR-HIL-09, SEC-07) routes, per
the exact shape pinned in services/api/tests/API_ST3a.md (round 3). Only the policy owner stops,
pauses or revokes; a non-member or a non-owner gets exactly the same 404/response as an unknown
world or policy (no membership or ownership oracle). Stop-all and Pause-all validate every
policy's plan before mutating anything (never half-apply, never 500), keep lowering autonomy even
when the event writer is down (the part is kept pending and flushed on the next mutating call
against that world), and serialize under one lock so two concurrent calls never double-write.
The two GET routes rebuild every kept event by allowlisting exactly the fields API_ST3a.md names,
never by copying the stored event forward: a hidden event, a hidden district, a real store id, an
archive/message ref and a dangling cause-or-data reference never reach a non-owner response.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tilo_api.deps import EventWriter, Principal, Store, WorldRecord, get_current_principal, get_event_writer, get_store
from tilo_api.events import now, policy_changed_part, policy_vis, world_paused_part

router = APIRouter()

# One lock for every Stop-all/Pause-all mutation (round-3 qa finding): simple and correct for an
# in-memory single-process store -- two concurrent calls against the same or different worlds
# serialize, so the second always sees the first's completed state and never double-applies.
_MUTATE_LOCK = threading.Lock()

_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")

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
    "model_role": None,
    "profile": None,
    "tokens_in": None,
    "tokens_out": None,
    "tool": None,
    "latency_ms": None,
    "archive_ref": None,
}


def _is_owner(principal: Principal, owner: str) -> bool:
    return principal.role == "owner" and principal.user_id == owner


def _require_member_world(principal: Principal, store: Store, world_id: str) -> WorldRecord:
    """Membership check applied first on every world route: a mismatch (wrong world, or no
    membership) is identical to an unknown world_id -- same 404, so a caller cannot tell "no
    such world" from "you are not a member of it" (round-2 security finding)."""
    if principal.world_id != world_id:
        raise HTTPException(status_code=404)
    world = store.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404)
    return world


def _safe_districts(value: Any) -> tuple[str, ...]:
    """Round-3 security finding: Principal.districts is typed tuple[str, ...], but a caller that
    (by a bug elsewhere) ends up with a bare str or any other non-list/tuple/set must never have
    it iterated char-by-char or substring-matched against a district id -- treated as no
    districts at all."""
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(d for d in value if isinstance(d, str))
    return ()


def _visible(is_owner: bool, vis: Any, safe_districts: tuple[str, ...]) -> bool:
    """Server-side redaction (PRD 10.1, EV-13): the owner sees everything; "all" is visible to
    anyone; a district list is visible only when it intersects the caller's own districts. Fail
    closed -- anything else is not visible."""
    if is_owner:
        return True
    if vis == "all":
        return True
    if isinstance(vis, list):
        return any(d in safe_districts for d in vis)
    return False


def _district_fields(record: Any) -> tuple[str, str] | None:
    """None or unusable (round-2 finding): a malformed district record is treated as hidden,
    never raises, whoever is asking."""
    name = getattr(record, "name", None)
    summary = getattr(record, "summary", None)
    if isinstance(name, str) and isinstance(summary, str):
        return name, summary
    return None


def _is_malformed_event(event: Any) -> bool:
    """Round-3 finding: an event missing id (or id not a string), a cause that is not a string or
    None, or missing any other key event.schema.json requires is dropped for everyone, owner
    included -- a value tilo-api cannot safely read cannot be honestly shown to anyone."""
    if not isinstance(event, dict):
        return True
    for key in _REQUIRED_EVENT_KEYS:
        if key not in event:
            return True
    if not isinstance(event["id"], str):
        return True
    cause = event["cause"]
    return cause is not None and not isinstance(cause, str)


def _redact_data(data: Any, id_map: dict[str, str]) -> Any:
    """A ULID-shaped data value naming another event is remapped to that event's view-local id
    when it survived filtering, else nulled -- the same treatment as `cause`. `message_ref`
    (archive-position-shaped, not ULID-shaped) is always null for a scoped viewer regardless."""
    if not isinstance(data, dict):
        return data
    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key == "message_ref":
            redacted[key] = None
        elif isinstance(value, str) and _ULID_RE.match(value):
            redacted[key] = id_map.get(value)
        else:
            redacted[key] = value
    return redacted


def _owner_event_view(event: dict) -> dict:
    """The owner's full stream (PRD 15.3): every allowlisted field, unchanged."""
    return {
        "seq": event["seq"],
        "id": event["id"],
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
        "cause": event["cause"],
        "vis": event["vis"],
        "data": event["data"],
        "trace": event["trace"],
    }


def _scoped_event_view(event: dict, seq: int, id_map: dict[str, str], safe_districts: tuple[str, ...]) -> dict:
    """A redacted view (PRD 15.3): view-local seq/id, a hidden district nulled even on a vis:
    "all" event, cause remapped-or-nulled, ULID-shaped data remapped-or-nulled, archive_ref
    stripped outright."""
    district = event["district"]
    if district is not None and district not in safe_districts:
        district = None
    cause = event["cause"]
    cause = id_map.get(cause) if cause is not None else None
    trace_value = event.get("trace")
    trace = dict(trace_value) if isinstance(trace_value, dict) else dict(_EMPTY_TRACE)
    trace["archive_ref"] = None
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
        "district": district,
        "cause": cause,
        "vis": event["vis"],
        "data": _redact_data(event["data"], id_map),
        "trace": trace,
    }


def _write_or_pend(store: Store, writer: EventWriter, world_id: str, part: dict) -> None:
    """The writer being down must never stop the kill switch (round-3 qa/security finding): a
    part that fails to write is kept pending rather than lost or allowed to raise out of the
    route; the level change it records already happened and is never rolled back."""
    try:
        writer.append(world_id, part)
    except Exception:
        store.pending_events.setdefault(world_id, []).append(part)


def _flush_pending(store: Store, writer: EventWriter, world_id: str) -> None:
    """Attempt every part still pending for this world, oldest first, before this call's own new
    work. A part is removed from pending_events only once `append` returns for it, so it is
    written exactly once, never twice, never silently dropped."""
    pending = store.pending_events.get(world_id)
    if not pending:
        return
    store.pending_events[world_id] = []
    for part in pending:
        _write_or_pend(store, writer, world_id, part)


def _stop_all_owner_policies(
    store: Store, writer: EventWriter, owner: str, world: WorldRecord, requested_world_id: str, change: str, at: str
) -> tuple[int, int]:
    """PI-13/PI-18: validate every owned policy's plan first, then apply -- never half-applies,
    never 500s. L0 stays untouched, not counted. A policy is skipped as an idempotent repeat
    (already_l1, no new history entry, no event) only when it is *provably* already consistent:
    level == "L1" and its own history[-1]["level"] == "L1" too (round-3 code-review finding, "no
    silent history repair" -- a level that merely reads L1 while history disagrees or is
    unreadable is an inconsistent record, not a proven repeat, and goes through the exact same
    normal lowering path as any other policy). Anything else -- including a missing/malformed
    level, fail safe -- gets exactly one history entry and one policy.changed, routed to its
    mapped world or, absent one, to the world the request was made against (never a KeyError)."""
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

    for policy_id, policy, target_world_id in plan:
        history = policy.get("history")
        history = history if isinstance(history, list) else []
        history.append({"by": owner, "at": at, "change": change, "level": "L1"})
        policy["history"] = history
        policy["level"] = "L1"
        policy["changed_by"] = {"by": owner, "at": at}
        vis = policy_vis(policy, world.districts)
        part = policy_changed_part(policy_id=policy_id, change=change, owner=owner, at=at, vis=vis)
        _write_or_pend(store, writer, target_world_id, part)

    return len(plan), already_l1


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
    with _MUTATE_LOCK:
        _flush_pending(store, writer, world_id)
        stopped, already_l1 = _stop_all_owner_policies(store, writer, world.owner, world, world_id, "stop_all", at)
        pending = len(store.pending_events.get(world_id, []))

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
    with _MUTATE_LOCK:
        _flush_pending(store, writer, world_id)
        stopped, already_l1 = _stop_all_owner_policies(store, writer, world.owner, world, world_id, "stop_all", at)
        # Only a call that actually lowered something this round is a new pause action (also
        # what keeps two concurrent Pause-alls, serialized by the lock above, from each filing
        # their own world.paused once the first has already lowered every owned policy).
        if stopped > 0:
            part = world_paused_part(world_id=world_id, owner=world.owner, channel=body.channel)
            _write_or_pend(store, writer, world_id, part)
        pending = len(store.pending_events.get(world_id, []))

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
        # Same 404 for "no such policy" and "not yours" -- no ownership oracle (round-2 finding).
        raise HTTPException(status_code=404)

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
        target_world = store.worlds.get(target_world_id)
        world_districts = target_world.districts if target_world is not None else None
        vis = policy_vis(policy, world_districts)
        part = policy_changed_part(policy_id=policy_id, change="revoked", owner=owner, at=at, vis=vis)
        writer.append(target_world_id, part)

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
