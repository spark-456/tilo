"""Kill switches (FR-HIL-07, PI-13) and roles/redaction (FR-HIL-09, SEC-07) routes, per the
exact shape pinned in services/api/tests/API_ST3a.md. Only the policy owner stops, pauses or
revokes (else 403, store unchanged); redaction is server side and fail closed -- an event or
district a principal may not see is dropped from the response entirely, never returned with
fields blanked (PRD 10.1).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from tilo_api.deps import Principal, Store, WorldRecord, get_current_principal, get_store
from tilo_api.events import now, policy_changed_event, world_paused_event

router = APIRouter()


def _is_owner(principal: Principal, owner: str) -> bool:
    return principal.role == "owner" and principal.user_id == owner


def _stop_all_owner_policies(store: Store, owner: str, change: str, at: str) -> tuple[int, int]:
    """PI-13: every one of the owner's policies to L1, one policy.changed per policy actually
    changed this call; a policy already at L1 is skipped (idempotent repeat, no duplicate event).
    A kill switch only ever lowers autonomy: an L0 policy is already below L1, so it is left at
    L0 untouched -- no history entry, no event, not counted as stopped or already_l1."""
    stopped = 0
    already_l1 = 0
    for policy_id, policy in store.policies.items():
        if policy.get("owner") != owner:
            continue
        level = policy.get("level")
        if level == "L1":
            already_l1 += 1
            continue
        if level == "L0":
            continue
        policy["history"].append({"by": owner, "at": at, "change": change, "level": "L1"})
        policy["level"] = "L1"
        policy["changed_by"] = {"by": owner, "at": at}
        stopped += 1
        target_world = store.policy_worlds[policy_id]
        event = policy_changed_event(
            store=store,
            world_id=target_world,
            policy_id=policy_id,
            change=change,
            level="L1",
            owner=owner,
            at=at,
        )
        store.events.setdefault(target_world, []).append(event)
    return stopped, already_l1


def _visible(principal: Principal, world: WorldRecord, vis: Any) -> bool:
    """Server-side redaction (PRD 10.1, EV-13's vis rule): the owner sees everything; else "all"
    is visible to anyone, and a district list is visible only when it intersects the principal's
    districts. Fail closed -- anything else (a malformed vis) is not visible."""
    if principal.role == "owner" and principal.user_id == world.owner:
        return True
    if vis == "all":
        return True
    if isinstance(vis, list):
        return any(d in principal.districts for d in vis)
    return False


class PauseRequest(BaseModel):
    channel: str | None = None


@router.post("/worlds/{world_id}/autopilot/stop")
def stop_autopilot(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    world = store.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404)
    if not _is_owner(principal, world.owner):
        raise HTTPException(status_code=403)

    at = now()
    stopped, already_l1 = _stop_all_owner_policies(store, world.owner, "stop_all", at)
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
) -> dict:
    world = store.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404)
    if not _is_owner(principal, world.owner):
        raise HTTPException(status_code=403)

    at = now()
    stopped, already_l1 = _stop_all_owner_policies(store, world.owner, "stop_all", at)
    event = world_paused_event(store=store, world_id=world_id, owner=world.owner, channel=body.channel)
    store.events.setdefault(world_id, []).append(event)
    return {"stopped": stopped, "already_l1": already_l1, "paused": True}


@router.post("/policies/{policy_id}/revoke")
def revoke_policy(
    policy_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    policy = store.policies.get(policy_id)
    if policy is None:
        raise HTTPException(status_code=404)
    owner = policy["owner"]
    if not _is_owner(principal, owner):
        raise HTTPException(status_code=403)

    at = now()
    policy["history"].append({"by": owner, "at": at, "change": "revoked", "level": "L1"})
    policy["level"] = "L1"
    policy["changed_by"] = {"by": owner, "at": at}
    world_id = store.policy_worlds[policy_id]
    event = policy_changed_event(
        store=store, world_id=world_id, policy_id=policy_id, change="revoked", level="L1", owner=owner, at=at
    )
    store.events.setdefault(world_id, []).append(event)
    return {"policy_id": policy_id, "level": "L1"}


@router.get("/worlds/{world_id}/events")
def get_world_events(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    world = store.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404)
    events = [e for e in store.events.get(world_id, []) if _visible(principal, world, e.get("vis"))]
    return {"events": events}


@router.get("/worlds/{world_id}")
def get_world(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> dict:
    world = store.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404)
    visible_ids = [did for did in world.districts if _visible(principal, world, [did])]
    districts = [
        {"id": did, "name": world.districts[did].name, "summary": world.districts[did].summary} for did in visible_ids
    ]
    return {
        "world_id": world_id,
        "districts": districts,
        "has_hidden_districts": len(visible_ids) < len(world.districts),
    }
