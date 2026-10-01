"""Kill switches (FR-HIL-07, PI-13, PI-18, issue #46's binding S0 decision): stop/pause/revoke.
Only the policy owner stops, pauses or revokes; a non-member/non-owner gets the same 404 as
unknown (no oracle).

Design (issue #46, redone after the round-7/ST-3a-3 writer-identity approach was rejected): the
full event, id included, is built once when a part is enqueued (`events.new_part_id`) and resent
unchanged on every retry. The queue *is* `Store.pending_events[world_id]`, deduped by that `id`,
never by content and never by which writer object attempts it. At most one `append` is ever in
flight per world at a time (`_world_locks(store, w)["inflight"]`: a call that finds a young one
waits for it up to its own part deadline; one older than `attempt_abandon_after_s` is presumed lost
and the same part, same `id`, is attempted again -- idempotent by EV-10). The fast, no-I/O
mutation (policy level/history/changed_by, the `paused` flag, vis) happens under a separate,
always-blocking per-world `"mutate"` lock, held only for that decision and the enqueue -- never
across a `writer.append` call -- so one world's stuck writer
never delays another call's mutation, on the same or a different world. `world.paused` is
enqueued (and drained) ahead of this same call's own `policy.changed` parts (FR-WLD-07/NFR-07's 2s
budget). Every lock lives on the `Store` instance itself (`Store.dispatch_state`), never a
module-level dict, so two Store instances sharing a world_id string never share lock or queue
state (ST-3a-3).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
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

_CALL_BUDGET_S = 4.5  # a whole request's own write-attempt budget, under FR-HIL-07's 5s
_SOLE_RETRY_LIMIT = 2  # total attempts for a fast-failing part with nothing else left to try
_MAX_ABANDONED = 2  # presumed-lost attempts tolerated per world before no new thread is started
_EXECUTOR = ThreadPoolExecutor(max_workers=16)  # shared, bounded across every Store and world;
# correctness (one append in flight per world) comes from each world's own drain lock, not from
# this pool's size -- it only bounds total OS threads.


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
    """The one append currently in flight for a world (S0, issue #46 item 1)."""

    def __init__(self, part_id: str) -> None:
        self.part_id = part_id
        self.started = time.monotonic()
        self.future: Future[None]
        self.abandoned = False


def _run_attempt(store: Store, world_id: str, part: dict, writer: EventWriter, attempt: _Attempt) -> None:
    """Runs on a worker thread. A success removes the part from the queue *before* this future
    settles, so a call waiting on it never sees a committed part still pending."""
    locks = _world_locks(store, world_id)
    try:
        writer.append(world_id, part)
        _remove_pending(store, world_id, part["id"])
    except Exception:
        # issue #55 item 2: a writer that lost its lease or lost a commit race answers the resend
        # with WriterBusy until it is reopened; reopening is the writer's own optional hook, and
        # the resend (same id) is then idempotent.
        reopen = getattr(writer, "reopen", None)
        if callable(reopen):
            try:
                reopen()
            except Exception:
                pass
        raise
    finally:
        with locks["queue"]:
            if locks["inflight"] is attempt:
                locks["inflight"] = None
            if attempt.abandoned:
                locks["abandoned"] -= 1


def drain(
    store: Store,
    world_id: str,
    writer: EventWriter,
    deadline_at: float,
    part_deadline_s: float,
    abandon_after_s: float,
) -> None:
    """Attempts `store.pending_events[world_id]`'s head, oldest first, until the queue is empty,
    the shared deadline passes, or an attempt fails to settle within `part_deadline_s` (a hang):
    that leaves it, and everything behind it, still pending while the attempt keeps running in the
    background (Python threads cannot be cancelled).

    At most one attempt is in flight per world. A call that finds one still young waits for it, up
    to its own part deadline. A call that finds one older than `abandon_after_s` presumes it lost,
    stops counting it and starts a fresh attempt of the same part: `EventWriter.append` is
    idempotent by event id (EV-10), so a late success of the abandoned attempt is a harmless no-op.
    At most `_MAX_ABANDONED` presumed-lost attempts are tolerated per world; past that nothing new
    is started, so a dead writer cannot leak unbounded threads. A fast (non-hanging) failure does
    not block a *different* part behind it in the same call, but is retried in place, up to
    `_SOLE_RETRY_LIMIT` attempts, when nothing else is left to try this call."""
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
                    p for p in queue if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"] not in given_up
                ]
                if not candidates or locks["abandoned"] >= _MAX_ABANDONED:
                    return
                part = candidates[0]
                attempt = _Attempt(part["id"])
                locks["inflight"] = attempt
                attempt.future = _EXECUTOR.submit(_run_attempt, store, world_id, part, writer, attempt)
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


def _touched_worlds(store: Store, world_id: str, owner: str) -> list[str]:
    """The request's own world plus every owned policy's mapped world -- pending must count, and a
    later call must flush, every world a call's own policies could route an event to."""
    touched = {world_id}
    for policy_id, policy in store.policies.items():
        if isinstance(policy, dict) and policy.get("owner") == owner:
            touched.add(store.policy_worlds.get(policy_id, world_id))
    return sorted(touched)


def _apply_stop_all(store: Store, owner: str, requested_world_id: str, change: str, at: str):
    """Called with every touched world's mutate lock already held: plans and applies in one pass
    (never half-applies), skipping L0 and provably-consistent L1 policies (round-3, "no silent
    history repair"). Returns (stopped, already_l1, {target_world_id: [new part, ...]})."""
    stopped = 0
    already_l1 = 0
    parts_by_world: dict[str, list[dict]] = {}
    for policy_id, policy in list(store.policies.items()):
        if not isinstance(policy, dict) or policy.get("owner") != owner:
            continue
        if policy.get("level") == "L0":
            continue
        if events.is_consistent_l1(policy):
            already_l1 += 1
            continue
        target_world_id = store.policy_worlds.get(policy_id, requested_world_id)
        target_world = store.worlds.get(target_world_id)
        vis = events.policy_vis(policy, target_world.districts if target_world else None)
        events.apply_level_change(policy, owner=owner, change=change, at=at)
        part = events.policy_changed_part(
            part_id=events.new_part_id(), policy_id=policy_id, change=change, owner=owner, at=at, vis=vis
        )
        parts_by_world.setdefault(target_world_id, []).append(part)
        stopped += 1
    return stopped, already_l1, parts_by_world


def _drain_touched(
    store: Store, touched, writer: EventWriter, deadline_at: float, part_deadline_s: float, abandon_after_s: float
) -> int:
    for w in touched:
        drain(store, w, writer, deadline_at, part_deadline_s, abandon_after_s)
    return sum(len(store.pending_events.get(w) or []) for w in touched)


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
        stopped, already_l1, parts_by_world = _apply_stop_all(store, world.owner, world_id, "stop_all", at)
        for w, parts in parts_by_world.items():
            for part in parts:
                _enqueue(store, w, part)

    deadline_at = time.monotonic() + _CALL_BUDGET_S
    pending = _drain_touched(store, touched, writer, deadline_at, part_deadline_s, abandon_after_s)
    body = {
        "stopped": stopped,
        "already_l1": already_l1,
        "confirmations": [{"channel": c} for c in world.owner_channels],
        "pending": pending,
    }
    return JSONResponse(content=body, status_code=202 if pending else 200)


class PauseRequest(BaseModel):
    channel: Literal["web", "mobile_web", "whatsapp", "email"] | None = None


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

    deadline_at = time.monotonic() + _CALL_BUDGET_S
    with _locked(store, [world_id]):
        if not world.paused:
            world.paused = True
            part = events.world_paused_part(part_id=events.new_part_id(), world_id=world_id, channel=principal.channel)
            _enqueue(store, world_id, part, front=True)
    drain(store, world_id, writer, deadline_at, part_deadline_s, abandon_after_s)  # priority phase: world.paused
    # (and any older backlog) ahead of this call's own policy.changed parts, built next.

    at = events.now()
    touched = _touched_worlds(store, world_id, world.owner)
    with _locked(store, touched):
        stopped, already_l1, parts_by_world = _apply_stop_all(store, world.owner, world_id, "stop_all", at)
        for w, parts in parts_by_world.items():
            for part in parts:
                _enqueue(store, w, part)
    pending = _drain_touched(store, touched, writer, deadline_at, part_deadline_s, abandon_after_s)

    body_out = {"stopped": stopped, "already_l1": already_l1, "paused": True, "pending": pending}
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
    target_world_id = store.policy_worlds.get(policy_id)

    if target_world_id is None:
        # No world to flush or lock -- the mutation alone still needs one, scoped to this policy
        # id (round-6/ST-3a-2, issue #38 item 5), so two concurrent revokes of the same unmapped
        # policy cannot race and drop one's history entry.
        with _policy_lock(store, policy_id):
            events.apply_level_change(policy, owner=owner, change="revoked", at=at)
        return {"policy_id": policy_id, "level": "L1"}

    deadline_at = time.monotonic() + _CALL_BUDGET_S
    with _locked(store, [target_world_id]):
        target_world = store.worlds.get(target_world_id)
        vis = events.policy_vis(policy, target_world.districts if target_world else None)
        events.apply_level_change(policy, owner=owner, change="revoked", at=at)
        part = events.policy_changed_part(
            part_id=events.new_part_id(), policy_id=policy_id, change="revoked", owner=owner, at=at, vis=vis
        )
        _enqueue(store, target_world_id, part)
    drain(store, target_world_id, writer, deadline_at, part_deadline_s, abandon_after_s)
    return {"policy_id": policy_id, "level": "L1"}
