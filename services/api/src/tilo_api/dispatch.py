"""Kill switches (FR-HIL-07, PI-13, PI-18): Stop all autopilot, Pause all, revoke a policy.
Only the policy owner acts; a non-member or non-owner gets the same 404 as unknown (no oracle).
Deterministic: no model is involved and every decision is plain code.

Level changes are planned in full, then applied under a per-world "mutate" lock that is never held
across I/O, so a stuck writer never delays a level change. Each event part is built once, `id`
included, and resent unchanged on every retry; the queue is `Store.pending_events[world_id]`,
deduped by that id (EV-10), never by content or writer object. At most one append is in flight per
world, each on its own daemon thread (not joined at exit). A call that finds a young attempt waits
for it up to its part deadline; one older than `attempt_abandon_after_s` is presumed lost and the
same part is sent again. At most `_MAX_ABANDONED` presumed-lost threads per world, so one world's
hung writer never takes threads another world needs. Pause all applies its level changes first,
then drains `world.paused` alone first, then everything else (FR-WLD-07's 2 s). All lock and queue
state lives on the `Store` instance. Round history is in services/api/tests/API_ST3a.md.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tilo_api import events
from tilo_api.deps import (
    EventWriter,
    Principal,
    Store,
    WorldRecord,
    get_attempt_abandon_after_s,
    get_current_principal,
    get_event_writer,
    get_part_write_deadline_s,
    get_store,
)

router = APIRouter()
logger = logging.getLogger("tilo_api.dispatch")

_CALL_BUDGET_S = 4.5  # a whole request's own write-attempt budget, under FR-HIL-07's 5s
_SOLE_RETRY_LIMIT = 2  # total attempts for a fast-failing part with nothing else left to try
_MAX_ABANDONED = 2  # presumed-lost threads tolerated per world before no new thread starts


def _dispatch_bucket(store: Store) -> dict:
    ds = store.dispatch_state
    if "guard" not in ds:
        ds["guard"] = threading.Lock()
        ds["worlds"] = {}
        ds["policies"] = {}
    return ds


def _world_locks(store: Store, world_id: str) -> dict:
    ds = _dispatch_bucket(store)
    with ds["guard"]:
        entry = ds["worlds"].get(world_id)
        if entry is None:
            entry = {
                "mutate": threading.Lock(),
                "queue": threading.RLock(),  # guards the queue list and the in-flight record
                "inflight": None,  # the one _Attempt currently counted against this world
                "abandoned": 0,  # presumed-lost attempts whose threads have not settled yet
            }
            ds["worlds"][world_id] = entry
    return entry


def _policy_lock(store: Store, policy_id: str) -> threading.Lock:
    ds = _dispatch_bucket(store)
    with ds["guard"]:
        lock = ds["policies"].get(policy_id)
        if lock is None:
            lock = threading.Lock()
            ds["policies"][policy_id] = lock
    return lock


@contextmanager
def _locked(store: Store, world_ids):
    locks = [_world_locks(store, w)["mutate"] for w in sorted(set(world_ids))]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


def _enqueue(store: Store, world_id: str, part: dict, *, front: bool = False) -> None:
    with _world_locks(store, world_id)["queue"]:
        queue = store.pending_events.get(world_id)
        queue = list(queue) if isinstance(queue, list) else []
        store.pending_events[world_id] = [part, *queue] if front else [*queue, part]


def _remove_pending(store: Store, world_id: str, part_id: str) -> None:
    with _world_locks(store, world_id)["queue"]:
        queue = store.pending_events.get(world_id)
        if not isinstance(queue, list):
            return
        store.pending_events[world_id] = [p for p in queue if not (isinstance(p, dict) and p.get("id") == part_id)]


class _Attempt:
    """The one append in flight for a world. `started` is when its thread was started."""

    def __init__(self, part_id: str) -> None:
        self.part_id = part_id
        self.started = time.monotonic()
        self.future: Future[None] = Future()
        self.abandoned = False


def _run_attempt(store: Store, world_id: str, part: dict, writer: EventWriter, attempt: _Attempt) -> None:
    """Thread body. A success leaves the queue before the future settles, so a waiter never sees a
    committed part still pending. A WriterBusy answer (matched by name: tilo-api cannot import the
    harness) reopens the writer, but only while this attempt is still the one counted in flight."""
    locks = _world_locks(store, world_id)
    error: Exception | None = None
    try:
        writer.append(world_id, part)
        _remove_pending(store, world_id, part["id"])
    except Exception as exc:
        error = exc
        with locks["queue"]:
            current = locks["inflight"] is attempt and not attempt.abandoned
        reopen = getattr(writer, "reopen", None)
        if current and type(exc).__name__ == "WriterBusy" and callable(reopen):
            try:
                reopen()
            except Exception:
                logger.warning("writer reopen failed for world %s", world_id)
    with locks["queue"]:
        if locks["inflight"] is attempt:
            locks["inflight"] = None
        if attempt.abandoned:
            locks["abandoned"] -= 1
    if error is None:
        attempt.future.set_result(None)
    else:
        attempt.future.set_exception(error)


def drain(
    store: Store,
    world_id: str,
    writer: EventWriter,
    deadline_at: float,
    part_deadline_s: float,
    abandon_after_s: float,
    only_type: str | None = None,
) -> None:
    """Attempts the world's pending parts oldest first until the queue is empty, the deadline
    passes, or an attempt does not settle within `part_deadline_s` (that part and everything behind
    it stay pending). See the module docstring for the in-flight and abandon rules. A fast failure
    does not block a different part behind it; it is retried in place up to `_SOLE_RETRY_LIMIT`
    attempts only when nothing else is left to try."""
    locks = _world_locks(store, world_id)
    given_up: set[str] = set()
    sole_attempts: dict[str, int] = {}

    def note_failure(part_id: str, others_waiting: bool) -> None:
        if others_waiting:
            given_up.add(part_id)
            return
        sole_attempts[part_id] = sole_attempts.get(part_id, 0) + 1
        if sole_attempts[part_id] >= _SOLE_RETRY_LIMIT:
            given_up.add(part_id)

    while time.monotonic() < deadline_at:
        wait_on: Future[None] | None = None
        wait_part = ""
        wait_s = 0.0
        with locks["queue"]:
            current = locks["inflight"]
            if current is not None:
                age = time.monotonic() - current.started
                if age >= abandon_after_s:
                    current.abandoned = True
                    locks["abandoned"] += 1
                    locks["inflight"] = None
                    current = None
                else:
                    wait_on = current.future
                    wait_part = current.part_id
                    wait_s = min(part_deadline_s - age, deadline_at - time.monotonic())
            if current is None:
                queue = store.pending_events.get(world_id)
                if not isinstance(queue, list):
                    return
                candidates = [
                    p
                    for p in queue
                    if isinstance(p, dict)
                    and isinstance(p.get("id"), str)
                    and p["id"] not in given_up
                    and (only_type is None or p.get("type") == only_type)
                ]
                if not candidates or locks["abandoned"] >= _MAX_ABANDONED:
                    return
                part = candidates[0]
                attempt = _Attempt(part["id"])
                try:
                    # Started before it is counted in flight; the thread's cleanup waits on this lock.
                    threading.Thread(
                        target=_run_attempt, args=(store, world_id, part, writer, attempt), daemon=True
                    ).start()
                except RuntimeError:
                    logger.warning("could not start an append thread for world %s", world_id)
                    return  # nothing was counted; the part stays pending for the next call
                locks["inflight"] = attempt
                future = attempt.future
        if wait_on is not None:
            if wait_s <= 0:
                return
            try:
                wait_on.result(timeout=wait_s)
            except FutureTimeoutError:
                return
            except Exception:
                note_failure(wait_part, others_waiting=False)  # someone else's attempt failed fast
            continue
        remaining = deadline_at - time.monotonic()
        try:
            future.result(timeout=max(0.0, min(part_deadline_s, remaining)))
        except FutureTimeoutError:
            return
        except Exception:
            note_failure(part["id"], others_waiting=len(candidates) > 1)


def _require_member_world(principal: Principal, store: Store, world_id: str) -> WorldRecord:
    if principal.world_id != world_id:
        raise HTTPException(status_code=404)
    world = store.worlds.get(world_id)
    if world is None:
        raise HTTPException(status_code=404)
    return world


def _require_owner(principal: Principal, world: WorldRecord) -> None:
    if not (principal.role == "owner" and principal.user_id == world.owner):
        raise HTTPException(status_code=403)


def _world_for(store: Store, policy_id: object, fallback: str | None) -> str | None:
    """The world whose stream gets a policy's events: its mapping if that is a string, else the
    fallback (a malformed mapping never raises)."""
    mapped = store.policy_worlds.get(policy_id) if isinstance(policy_id, str) else None
    return mapped if isinstance(mapped, str) and mapped else fallback


def _layout(store: Store, world_id: str | None) -> dict | None:
    """The target world's districts, or None (no layout) for an unknown or non-WorldRecord entry."""
    world = store.worlds.get(world_id) if isinstance(world_id, str) else None
    return world.districts if isinstance(world, WorldRecord) and isinstance(world.districts, dict) else None


def _touched_worlds(store: Store, world_id: str, owner: str) -> list[str]:
    """The request's world first, then every other world an owned policy routes to, sorted."""
    others = {world_id}
    for policy_id, policy in store.policies.items():
        if isinstance(policy, dict) and policy.get("owner") == owner:
            others.add(_world_for(store, policy_id, world_id) or world_id)
    return [world_id, *sorted(others - {world_id})]


def _confirmations(world: WorldRecord) -> list[dict[str, str]]:
    """Built after the change was applied, so a malformed owner_channels must never raise."""
    channels = world.owner_channels
    if not isinstance(channels, (tuple, list)):
        return []
    return [{"channel": c} for c in channels if isinstance(c, str)]


def _revoke_fallback_world(store: Store, principal: Principal) -> str | None:
    """The principal's own world, only when it exists and this principal owns it: a policy with no
    mapping must never write an event into someone else's (or a nonexistent) stream."""
    world_id = principal.world_id
    world = store.worlds.get(world_id) if isinstance(world_id, str) else None
    if isinstance(world, WorldRecord) and principal.role == "owner" and world.owner == principal.user_id:
        return world_id
    return None


def _plan_stop_all(store: Store, owner: str, request_world: str, change: str, at: str):
    """Plans every part before anything changes, so a bad record can never half-apply. Skips L0 and
    provably consistent L1 policies (no silent history repair). Returns (plan, already_l1) where
    plan is a list of (policy, target_world_id, part)."""
    plan: list[tuple[dict, str, dict]] = []
    already_l1 = 0
    for policy_id, policy in list(store.policies.items()):
        if not isinstance(policy, dict) or policy.get("owner") != owner or policy.get("level") == "L0":
            continue
        if events.is_consistent_l1(policy):
            already_l1 += 1
            continue
        target = _world_for(store, policy_id, request_world) or request_world
        part = events.policy_changed_part(
            part_id=events.new_part_id(),
            policy_id=policy_id,
            change=change,
            owner=owner,
            at=at,
            vis=events.policy_vis(policy, _layout(store, target)),
        )
        plan.append((policy, target, part))
    return plan, already_l1


def _apply_plan(store: Store, plan, owner: str, change: str, at: str) -> None:
    for policy, target, part in plan:
        events.apply_level_change(policy, owner=owner, change=change, at=at)
        _enqueue(store, target, part)


def _drain_touched(
    store: Store, touched, writer: EventWriter, deadline_at: float, part_deadline_s: float, abandon_after_s: float
) -> int:
    for w in touched:
        drain(store, w, writer, deadline_at, part_deadline_s, abandon_after_s)
    return sum(len(q) for q in (store.pending_events.get(w) for w in touched) if isinstance(q, list))


@router.post("/worlds/{world_id}/autopilot/stop")
def stop_autopilot(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
    part_deadline_s: float = Depends(get_part_write_deadline_s),
    abandon_after_s: float = Depends(get_attempt_abandon_after_s),
) -> JSONResponse:
    world = _require_member_world(principal, store, world_id)
    _require_owner(principal, world)

    at = events.now()
    touched = _touched_worlds(store, world_id, world.owner)
    with _locked(store, touched):
        plan, already_l1 = _plan_stop_all(store, world.owner, world_id, "stop_all", at)
        _apply_plan(store, plan, world.owner, "stop_all", at)

    deadline_at = time.monotonic() + _CALL_BUDGET_S
    pending = _drain_touched(store, touched, writer, deadline_at, part_deadline_s, abandon_after_s)
    body = {
        "stopped": len(plan),
        "already_l1": already_l1,
        "confirmations": _confirmations(world),
        "pending": pending,
    }
    return JSONResponse(content=body, status_code=202 if pending else 200)


class PauseRequest(BaseModel):
    channel: Literal["web", "mobile_web", "email"] | None = None


@router.post("/worlds/{world_id}/pause")
def pause_world(
    world_id: str,
    body: PauseRequest = PauseRequest(),
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
    part_deadline_s: float = Depends(get_part_write_deadline_s),
    abandon_after_s: float = Depends(get_attempt_abandon_after_s),
) -> JSONResponse:
    world = _require_member_world(principal, store, world_id)
    _require_owner(principal, world)
    del body  # validated against the schema enum (422 outside it); principal.channel is authoritative

    at = events.now()
    touched = _touched_worlds(store, world_id, world.owner)
    with _locked(store, touched):
        # Levels first (never waits on I/O), then world.paused at the head of its world's queue.
        plan, already_l1 = _plan_stop_all(store, world.owner, world_id, "stop_all", at)
        _apply_plan(store, plan, world.owner, "stop_all", at)
        if not world.paused:
            world.paused = True
            part = events.world_paused_part(
                part_id=events.new_part_id(), world_id=world_id, actor=principal.user_id, channel=principal.channel
            )
            _enqueue(store, world_id, part, front=True)

    deadline_at = time.monotonic() + _CALL_BUDGET_S
    drain(store, world_id, writer, deadline_at, part_deadline_s, abandon_after_s, only_type="world.paused")
    pending = _drain_touched(store, touched, writer, deadline_at, part_deadline_s, abandon_after_s)
    body_out = {"stopped": len(plan), "already_l1": already_l1, "paused": True, "pending": pending}
    return JSONResponse(content=body_out, status_code=202 if pending else 200)


@router.post("/policies/{policy_id}/revoke")
def revoke_policy(
    policy_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
    writer: EventWriter = Depends(get_event_writer),
    part_deadline_s: float = Depends(get_part_write_deadline_s),
    abandon_after_s: float = Depends(get_attempt_abandon_after_s),
) -> dict:
    policy = store.policies.get(policy_id)
    if not isinstance(policy, dict) or principal.user_id != policy.get("owner"):
        raise HTTPException(status_code=404)  # same 404 for unknown and not-yours -- no oracle

    owner = policy["owner"]
    at = events.now()
    # Routed like Stop all: the policy's mapped world, else the principal's own world if they own it.
    target = _world_for(store, policy_id, _revoke_fallback_world(store, principal))

    if target is None:
        # Nowhere to send an event; the level change alone still needs a per-policy lock.
        with _policy_lock(store, policy_id):
            events.apply_level_change(policy, owner=owner, change="revoked", at=at)
        return {"policy_id": policy_id, "level": "L1"}

    deadline_at = time.monotonic() + _CALL_BUDGET_S
    with _locked(store, [target]):
        part = events.policy_changed_part(
            part_id=events.new_part_id(),
            policy_id=policy_id,
            change="revoked",
            owner=owner,
            at=at,
            vis=events.policy_vis(policy, _layout(store, target)),
        )
        events.apply_level_change(policy, owner=owner, change="revoked", at=at)
        _enqueue(store, target, part)
    drain(store, target, writer, deadline_at, part_deadline_s, abandon_after_s)
    return {"policy_id": policy_id, "level": "L1"}
