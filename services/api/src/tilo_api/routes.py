"""Kill switches (FR-HIL-07, PI-13, PI-18) and roles/redaction (FR-HIL-09, SEC-07) routes, per
the exact shape pinned in services/api/tests/API_ST3a.md (round 2). Only the policy owner stops,
pauses or revokes; a non-member or a non-owner gets exactly the same 404/response as an unknown
world or policy (no membership or ownership oracle). Stop-all and Pause-all validate every
policy's plan before mutating anything, so a request never half-applies and never 500s.
Redaction on the two GET routes is server-side and fail closed: a hidden event or district is
dropped entirely, a view's own `seq` is dense, and a `cause` naming a hidden event is nulled.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from tilo_api.deps import EventWriter, Principal, Store, WorldRecord, get_current_principal, get_event_writer, get_store
from tilo_api.events import now, policy_changed_part, policy_vis, world_paused_part

router = APIRouter()


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


def _visible(principal: Principal, world: WorldRecord, vis: Any) -> bool:
    """Server-side redaction (PRD 10.1, EV-13): the owner sees everything; "all" is visible to
    anyone; a district list is visible only when it intersects the principal's districts. Fail
    closed -- anything else is not visible."""
    if principal.role == "owner" and principal.user_id == world.owner:
        return True
    if vis == "all":
        return True
    if isinstance(vis, list):
        return any(d in principal.districts for d in vis)
    return False


def _district_fields(record: Any) -> tuple[str, str] | None:
    """None or unusable (round-2 finding): a malformed district record is treated as hidden,
    never raises, whoever is asking."""
    name = getattr(record, "name", None)
    summary = getattr(record, "summary", None)
    if isinstance(name, str) and isinstance(summary, str):
        return name, summary
    return None


def _last_history_level(history: Any) -> Any:
    if not isinstance(history, list) or not history:
        return None
    last = history[-1]
    return last.get("level") if isinstance(last, dict) else None


def _append_l1_entry(policy: dict, owner: str, change: str, at: str) -> None:
    history = policy.get("history")
    history = history if isinstance(history, list) else []
    history.append({"by": owner, "at": at, "change": change, "level": "L1"})
    policy["history"] = history
    policy["level"] = "L1"


def _stop_all_owner_policies(
    store: Store, writer: EventWriter, owner: str, requested_world_id: str, change: str, at: str
) -> tuple[int, int]:
    """PI-13/PI-18: validate every owned policy's plan first, then apply -- never half-applies,
    never 500s. A kill switch only lowers autonomy: L0 stays untouched, not counted; anything
    else -- including a missing/malformed level, fail safe -- is lowered to L1 with exactly one
    policy.changed, routed to its mapped world or, absent one, to the world the request was made
    against (never a KeyError). A policy already at L1 is idempotent (already_l1, no event) --
    but its history is still repaired to end in L1 if it does not already (a malformed record's
    own inconsistency is not proof it was really at L1), never a new entry when it already is."""
    to_apply: list[tuple[str, dict, str]] = []
    to_repair: list[dict] = []
    already_l1 = 0
    for policy_id, policy in store.policies.items():
        if not isinstance(policy, dict) or policy.get("owner") != owner:
            continue
        level = policy.get("level")
        if level == "L0":
            continue
        if level == "L1":
            already_l1 += 1
            if _last_history_level(policy.get("history")) != "L1":
                to_repair.append(policy)
            continue
        to_apply.append((policy_id, policy, store.policy_worlds.get(policy_id, requested_world_id)))

    for policy in to_repair:
        _append_l1_entry(policy, owner, change, at)

    for policy_id, policy, target_world_id in to_apply:
        _append_l1_entry(policy, owner, change, at)
        policy["changed_by"] = {"by": owner, "at": at}
        part = policy_changed_part(policy_id=policy_id, change=change, owner=owner, at=at, vis=policy_vis(policy))
        writer.append(target_world_id, part)

    return len(to_apply), already_l1


class PauseRequest(BaseModel):
    channel: Literal["web", "mobile_web", "whatsapp", "email"] | None = None


@router.post("/worlds/{world_id}/autopilot/stop")
def stop_autopilot(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
) -> dict:
    world = _require_member_world(principal, store, world_id)
    if not _is_owner(principal, world.owner):
        raise HTTPException(status_code=403)

    at = now()
    stopped, already_l1 = _stop_all_owner_policies(store, writer, world.owner, world_id, "stop_all", at)
    return {
        "stopped": stopped,
        "already_l1": already_l1,
        "confirmations": [{"channel": c} for c in world.owner_channels],
    }


@router.post("/worlds/{world_id}/pause")
def pause_world(
    world_id: str,
    body: PauseRequest = PauseRequest(),
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
) -> dict:
    world = _require_member_world(principal, store, world_id)
    if not _is_owner(principal, world.owner):
        raise HTTPException(status_code=403)

    at = now()
    stopped, already_l1 = _stop_all_owner_policies(store, writer, world.owner, world_id, "stop_all", at)
    writer.append(world_id, world_paused_part(world_id=world_id, owner=world.owner, channel=body.channel))
    return {"stopped": stopped, "already_l1": already_l1, "paused": True}


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
        part = policy_changed_part(policy_id=policy_id, change="revoked", owner=owner, at=at, vis=policy_vis(policy))
        writer.append(target_world_id, part)

    return {"policy_id": policy_id, "level": "L1"}


@router.get("/worlds/{world_id}/events")
def get_world_events(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    world = _require_member_world(principal, store, world_id)
    all_events = store.events.get(world_id, [])
    visible_ids = {e["id"] for e in all_events if _visible(principal, world, e.get("vis"))}

    result: list[dict] = []
    for event in all_events:
        if event["id"] not in visible_ids:
            continue
        copy = dict(event)
        copy["seq"] = len(result) + 1
        if copy.get("cause") is not None and copy["cause"] not in visible_ids:
            copy["cause"] = None
        result.append(copy)
    return {"events": result}


@router.get("/worlds/{world_id}")
def get_world(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    world = _require_member_world(principal, store, world_id)
    districts = []
    has_hidden = False
    for district_id, record in world.districts.items():
        fields = _district_fields(record)
        if fields is None or not _visible(principal, world, [district_id]):
            has_hidden = True
            continue
        name, summary = fields
        districts.append({"id": district_id, "name": name, "summary": summary})
    return {"world_id": world_id, "districts": districts, "has_hidden_districts": has_hidden}
