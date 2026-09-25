"""Kill switches (FR-HIL-07, PI-13, PI-18): stop/pause/revoke. Only the policy owner stops,
pauses or revokes; a non-member/non-owner gets the same 404 as unknown (no oracle).

Locking: the fast, no-I/O mutation (policy level/history/changed_by, world.paused, vis) happens
under per-world locks (never one global lock, so world A never waits on world B). Revoke of an
unmapped policy takes a policy-scoped lock instead (there is no world to key one by).

Writing: one bounded, persistent worker pool per world (round 6) -- not a pool rebuilt every
call -- processes that world's parts one at a time, build order first (existing pending, oldest
first, then this call's own new parts), so commit order in store.events matches build order. An
attempt still running from an earlier call is never resubmitted (`_WorldChannel._in_flight`
dedupes by part identity): a late success is written at most once. Each attempt is bounded by a
budget shared across the whole call (not divided per part), so a hung writer cannot hold a
request, or another world's caller, past budget; different worlds' pools run fully in parallel.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import ExitStack
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tilo_api.deps import EventWriter, Principal, Store, WorldRecord, get_current_principal, get_event_writer, get_store
from tilo_api.events import now, policy_changed_part, policy_vis, world_paused_part

router = APIRouter()

_BUDGET_S = 3.5  # one call's whole write attempt, shared across every part it touches
_PART_DEADLINE_S = 0.3  # caps any single part's wait so a small batch against a hung writer
# still returns quickly, and a different, unrelated caller sharing a world is never held up long
_POOL_WORKERS = 8  # a small, bounded, reused pool per world -- never one thread per part per call

# Per-world (and, prefixed, per-policy) locks, never one global lock: two calls against the same
# key serialize; two against different keys never wait on each other. `_locks_guard` only ever
# protects the registry lookup itself.
_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


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


class _WorldChannel:
    """The single ordered writer for one world (round 6, issue #38 items 2-3): a bounded,
    persistent pool -- a small constant number of worker threads, reused across calls, never one
    per part per call. `_in_flight` maps a part's identity to its still-running attempt so a
    second call touching the same world reuses it instead of submitting a duplicate; a part is
    removed from `pending_events` only once its own attempt actually succeeds."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=_POOL_WORKERS)
        self._in_flight: dict[int, Future] = {}

    def _future_for(self, writer: EventWriter, world_id: str, part: dict) -> Future:
        key = id(part)
        with self._lock:
            future = self._in_flight.get(key)
            if future is None:
                future = self._pool.submit(writer.append, world_id, part)
                self._in_flight[key] = future
            return future

    def process(self, store: Store, writer: EventWriter, world_id: str, parts: list[dict]) -> None:
        """parts: this call's own build-order list (existing pending first, then new). Attempts
        each in order, never invoking part i+1's attempt before part i's has settled -- so commit
        order always matches build order -- bounded by a budget shared across the whole list: a
        batch of fast/successful parts is never cut short, while a batch of individually slow
        parts stops even *attempting* further ones once the shared budget is gone."""
        deadline = time.monotonic() + _BUDGET_S
        for part in parts:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue  # leave it pending, untried this call
            future = self._future_for(writer, world_id, part)
            try:
                future.result(timeout=min(_PART_DEADLINE_S, remaining))
            except FutureTimeoutError:
                continue  # still running -- stays in _in_flight for a later call to find and wait on
            except Exception:
                with self._lock:
                    self._in_flight.pop(id(part), None)
                continue  # genuinely failed -- a later call submits a fresh attempt
            else:
                with self._lock:
                    self._in_flight.pop(id(part), None)
                pending = store.pending_events.get(world_id)
                if pending and part in pending:
                    pending.remove(part)
                    if not pending:
                        store.pending_events.pop(world_id, None)


_channels_guard = threading.Lock()
_channels: dict[str, _WorldChannel] = {}


def _channel_for(world_id: str) -> _WorldChannel:
    with _channels_guard:
        return _channels.setdefault(world_id, _WorldChannel())


def _enqueue_and_dispatch(
    store: Store, writer: EventWriter, new_work: dict[str, list[dict]], touched: list[str]
) -> None:
    """For every touched world: appends its new parts (if any) behind whatever is already
    pending, then processes that world's whole ordered list on its own thread -- different
    worlds' writes run fully in parallel; only the order within one world's own list is bound."""
    threads = []
    for world_id in touched:
        new_parts = new_work.get(world_id, [])
        existing = list(store.pending_events.get(world_id, []))
        if new_parts:
            store.pending_events.setdefault(world_id, []).extend(new_parts)
        ordered = existing + new_parts
        if not ordered:
            continue
        channel = _channel_for(world_id)
        threads.append(threading.Thread(target=channel.process, args=(store, writer, world_id, ordered)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _touched_worlds(store: Store, world_id: str, owner: str) -> list[str]:
    """The request's own world plus every owned policy's mapped world (pending/flush must count
    and reach every world a call's own policies could route an event to)."""
    touched = {world_id}
    for policy_id, policy in store.policies.items():
        if isinstance(policy, dict) and policy.get("owner") == owner:
            touched.add(store.policy_worlds.get(policy_id, world_id))
    return list(touched)


def _stop_all_owner_policies(
    store: Store, owner: str, requested_world_id: str, change: str, at: str
) -> tuple[int, int, list[tuple[str, dict]]]:
    """PI-13/PI-18: plan every owned policy first -- vis computed here too, before any mutation
    (a malformed scope must never abort the kill switch, so policy_vis itself never raises; this
    is nonetheless where the fix lives structurally) -- then apply, never half-applies, never
    500s. L0 stays untouched. A policy is skipped as already_l1 only when *provably* consistent
    (level == "L1" and its own history agrees too, "no silent history repair"); anything else
    (including a missing/malformed level, or an L1 whose history disagrees) is lowered with one
    history entry and one policy.changed."""
    plan: list[tuple[str, dict, str, object]] = []
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
        target_world_id = store.policy_worlds.get(policy_id, requested_world_id)
        target_world = store.worlds.get(target_world_id)
        vis = policy_vis(policy, target_world.districts if target_world else None)
        plan.append((policy_id, policy, target_world_id, vis))

    new_parts: list[tuple[str, dict]] = []
    for policy_id, policy, target_world_id, vis in plan:
        history = policy.get("history")
        history = history if isinstance(history, list) else []
        history.append({"by": owner, "at": at, "change": change, "level": "L1"})
        policy["history"] = history
        policy["level"] = "L1"
        policy["changed_by"] = {"by": owner, "at": at}
        new_parts.append(
            (target_world_id, policy_changed_part(policy_id=policy_id, change=change, owner=owner, at=at, vis=vis))
        )

    return len(plan), already_l1, new_parts


class PauseRequest(BaseModel):
    channel: Literal["web", "mobile_web", "whatsapp", "email"] | None = None


def _stop_all_and_dispatch(
    store: Store,
    writer: EventWriter,
    world: WorldRecord,
    world_id: str,
    at: str,
    build_extra: Callable[[], dict | None] | None = None,
) -> tuple[int, int, int]:
    """Shared body of stop/pause: lock every touched world just for the plan-and-apply (no I/O,
    vis included -- see _stop_all_owner_policies); build_extra() runs under that same lock so
    pause's paused-flag check+set is atomic with it. New parts are then enqueued and dispatched,
    per touched world, outside the lock. Returns (stopped, already_l1, pending)."""
    touched = _touched_worlds(store, world_id, world.owner)
    new_work: dict[str, list[dict]] = {}
    with _locked(touched):
        stopped, already_l1, new_parts = _stop_all_owner_policies(store, world.owner, world_id, "stop_all", at)
        for target_world_id, part in new_parts:
            new_work.setdefault(target_world_id, []).append(part)
        extra = build_extra() if build_extra is not None else None
        if extra is not None:
            new_work.setdefault(world_id, []).append(extra)

    _enqueue_and_dispatch(store, writer, new_work, touched)
    pending = sum(len(store.pending_events.get(w, [])) for w in touched)
    return stopped, already_l1, pending


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

    stopped, already_l1, pending = _stop_all_and_dispatch(store, writer, world, world_id, now())
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
    _ = body  # validated against the schema enum (422 outside it); no longer read -- principal.channel is the source

    def build_paused_part() -> dict | None:
        if world.paused:  # sole dedupe: the flag, checked/set under stop_all_and_dispatch's lock
            return None
        world.paused = True
        return world_paused_part(world_id=world_id, owner=world.owner, channel=principal.channel)

    stopped, already_l1, pending = _stop_all_and_dispatch(store, writer, world, world_id, now(), build_paused_part)
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
    target_world_id = store.policy_worlds.get(policy_id)

    def apply_level_change() -> None:
        history = policy.get("history")
        history = history if isinstance(history, list) else []
        history.append({"by": owner, "at": at, "change": "revoked", "level": "L1"})
        policy["history"] = history
        policy["level"] = "L1"
        policy["changed_by"] = {"by": owner, "at": at}

    if target_world_id is None:
        # No world to flush or lock -- but the mutation itself still needs one, scoped to this
        # one policy id (a disjoint namespace from world locks), so two concurrent revokes of the
        # same unmapped policy can never race and drop one's history entry.
        with _lock_for(f"policy:{policy_id}"):
            apply_level_change()
        return {"policy_id": policy_id, "level": "L1"}

    with _locked([target_world_id]):
        apply_level_change()
        target_world = store.worlds.get(target_world_id)
        vis = policy_vis(policy, target_world.districts if target_world else None)
        part = policy_changed_part(policy_id=policy_id, change="revoked", owner=owner, at=at, vis=vis)

    _enqueue_and_dispatch(store, writer, {target_world_id: [part]}, [target_world_id])
    return {"policy_id": policy_id, "level": "L1"}
