"""Kill switches (FR-HIL-07, PI-13, PI-18): stop/pause/revoke. Only the policy owner stops,
pauses or revokes; a non-member/non-owner gets the same 404 as unknown (no oracle).

Locking: the fast, no-I/O mutation (policy level/history/changed_by, world.paused, vis) happens
under per-world locks (never one global lock, so world A never waits on world B). Revoke of an
unmapped policy takes a policy-scoped lock instead (there is no world to key one by). Every lock
and every world's write queue lives on the `Store` instance itself (`Store._dispatch_state`,
`Store._dispatch_lock`) -- never a module-level dict keyed by world_id alone -- so two Store
instances that happen to share a world_id string never share lock, queue or dedupe state.

Writing (round 7, ST-3a-3): one long-lived consumer per world (`_WorldConsumer`), owning that
world's ordered queue. A mutating route only enqueues, under the world lock, then calls
`drain()`, which waits up to the call's shared budget. The head of a world's queue is attempted
first and is never passed until it settles (succeeds, or genuinely fails/raises); a part is
deduped on a stable id carried alongside it in the queue record, never on `id(part)`, so a part
is never re-sent once committed, even if `store.pending_events` is externally rebuilt with
fresh-but-identical-content dicts (a persisted-queue reload). An attempt that neither succeeds
nor raises within its own bounded deadline is presumed hung: the consumer stops waiting on it
(freeing its own "worker slot" without touching the still-running thread, which is simply
abandoned) and, on this or a later call, becomes available to retry against whichever writer that
call supplies -- recovering without a restart. A genuine (fast) failure, unlike a hang, does not
block later parts in the same call.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tilo_api.deps import EventWriter, Principal, Store, WorldRecord, get_current_principal, get_event_writer, get_store
from tilo_api.events import now, policy_changed_part, policy_vis, world_paused_part

router = APIRouter()

_BUDGET_S = 3.5  # one call's whole write attempt, shared across every part it touches
_PART_DEADLINE_S = 0.3  # caps a single attempt's wait: long enough for every writer this ticket's
# tests exercise to settle for real (fast, slow, or slow-then-failing), short enough that a
# different, unrelated caller sharing a world with a truly hung one is never held up long


def _content_key(part: dict) -> str:
    """A part's identity for dedupe purposes is its content, never id(part) -- id() can be reused
    by the allocator once a committed part is freed (round-6 bug), and a persisted queue reload
    hands back a brand-new dict with identical content and a different id() (also round 6)."""
    return json.dumps(part, sort_keys=True, default=str)


def _remove_from_pending(store: Store, world_id: str, part: dict) -> None:
    """dict equality (not identity) is what makes this safe against a reload: `list.remove` finds
    a content-equal entry even if it is a different object than the one originally attempted."""
    pending = store.pending_events.get(world_id)
    if pending is None:
        return
    try:
        pending.remove(part)
    except ValueError:
        return
    if not pending:
        store.pending_events.pop(world_id, None)


class _QueueItem:
    """One tracked part in a world's queue. `stable_id` (ambiguity 20: any stable form is fine,
    just never `id(part)` and never a field of `part` itself) exists alongside the part, never
    inside it -- `EventWriter.append` never sees it. Identity (not a list position) is what
    `drain` uses to find and remove one of these, so it stays correct even when a concurrent
    `reconcile_and_extend` splices the shared queue mid-drain."""

    __slots__ = ("stable_id", "part", "settled", "attempt_active", "attempt_deadline", "attempt_writer")

    def __init__(self, part: dict) -> None:
        self.stable_id = uuid.uuid4().hex
        self.part = part
        self.settled = False
        self.attempt_active = False
        self.attempt_deadline = 0.0
        self.attempt_writer: object | None = None  # the EventWriter instance the current (or
        # most recent) attempt is using -- see drain()'s timeout handling below


class _WorldConsumer:
    """The single consumer for one world (one instance lives in that Store's own
    `_dispatch_state`, never at module level). Owns the ordered queue and enforces: the head is
    attempted first and is never passed until it settles; a committed part is written at most
    once; a hung attempt frees its own bookkeeping slot (never the orphaned thread itself) so a
    later attempt -- on this call or the next -- can retry against whichever writer is current."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._queue: list[_QueueItem] = []
        self._by_content: dict[str, _QueueItem] = {}

    def _find_or_create(self, part: dict) -> _QueueItem:
        key = _content_key(part)
        item = self._by_content.get(key)
        if item is None:
            item = _QueueItem(part)
            self._by_content[key] = item
        else:
            item.part = part  # keep the latest content-equal object (a reload hands a new one)
        return item

    def reconcile_and_extend(
        self, store: Store, world_id: str, front_parts: list[dict], back_parts: list[dict]
    ) -> None:
        """Called under the world's lock, before any writer I/O. This is purely additive -- it
        never rebuilds or replaces the tracked queue wholesale, only merges into it -- because a
        `drain()` for this same world can be running concurrently (its own lock hold is released
        while it waits on a part's own attempt) and must never have an in-flight item's tracking
        pulled out from under it. Any part currently in store.pending_events[world_id] that this
        consumer has never tracked (a fresh consumer's first look at a pre-seeded backlog, or a
        persisted-queue reload's brand-new-but-content-identical dicts, ambiguity 20) is adopted,
        appended in that list's own order; front_parts are then spliced in ahead of *everything*
        (round 7: world.paused jumps ahead of this call's own audit parts *and* the existing
        backlog) and back_parts behind everything, each only if not already tracked."""
        with self._cv:
            # Drop anything already settled -- a drain() call may not have gotten back around to
            # pruning it (every waiter on it can have already timed out and returned before its
            # notification arrived, same race as above) -- *before* rebuilding pending_events from
            # this list below, or a settled-but-not-yet-pruned entry would be resurrected into it.
            self._queue = [it for it in self._queue if not it.settled]
            tracked = {id(it) for it in self._queue}
            for part in store.pending_events.get(world_id, []):
                item = self._find_or_create(part)
                if item.settled:
                    # store.pending_events[world_id] can transiently still show a part whose
                    # attempt already succeeded: the notification arrived after every waiter on it
                    # had already timed out and returned, so nobody was left to remove it from
                    # store.pending_events at the time (drain() catches this for self._queue
                    # itself; a settled item must never be re-adopted into it here either). The
                    # rebuild below, from self._queue's now-correct content, clears it out for good.
                    continue
                if id(item) not in tracked:
                    self._queue.append(item)
                    tracked.add(id(item))
            front_items = []
            for p in front_parts:
                item = self._find_or_create(p)
                if id(item) not in tracked:
                    front_items.append(item)
                    tracked.add(id(item))
            back_items = []
            for p in back_parts:
                item = self._find_or_create(p)
                if id(item) not in tracked:
                    back_items.append(item)
                    tracked.add(id(item))
            self._queue = front_items + self._queue + back_items
            live_keys = {_content_key(it.part) for it in self._queue}
            for key in list(self._by_content):
                if key not in live_keys:
                    del self._by_content[key]
            if self._queue:
                store.pending_events[world_id] = [it.part for it in self._queue]
            else:
                store.pending_events.pop(world_id, None)
            self._cv.notify_all()

    def _run_attempt(self, writer: EventWriter, world_id: str, item: _QueueItem, store: Store) -> None:
        part = item.part
        try:
            writer.append(world_id, part)
        except Exception:
            with self._cv:
                if not item.settled:
                    item.attempt_active = False
                self._cv.notify_all()
            return
        with self._cv:
            if not item.settled:
                item.settled = True
                _remove_from_pending(store, world_id, part)
            item.attempt_active = False
            self._cv.notify_all()

    def drain(self, store: Store, writer: EventWriter, world_id: str, deadline: float) -> None:
        """Attempts this world's queue, oldest-first, starting from the head. A genuine failure
        (the attempt concluded, raising) does not block later parts -- move on within this same
        call. A timeout (the attempt is still running when its own bounded deadline passes) is
        presumed a hang: this call gives up waiting on it. Whether that frees the head for a
        *retry*, right here in this same call, hinges on whether `writer` is the very instance
        already presumed stuck (`head.attempt_writer`): retrying the *same* instance risks nothing
        -- if it is truly hung it will never answer either way -- but a slow-not-hung writer can
        still land its real, original write after we stop waiting on it (`LateSuccessEventWriter`,
        issue #38 item 2's own repro): starting a second attempt against that *same* instance
        would then commit the part twice the moment both eventually return. So a same-instance
        timeout just leaves the head (and everything behind it) pending and returns; only a
        *different* writer instance -- a genuine swap-in, e.g. after an operator points this world
        at a healthy harness -- is trusted enough to retry immediately. `skip` (local to this
        call) is never stored on the item itself, and the head is found each pass by scanning from
        the front -- never a cached list position -- so a concurrent `reconcile_and_extend`
        splicing a part in ahead of everything (world.paused) can never desync this loop from
        where the actual head now is; multiple concurrent `drain()` calls for the same world are
        safe for the same reason plus `attempt_active` itself being the sole, lock-guarded gate on
        ever spawning a second attempt for one item."""
        skip: set[int] = set()
        with self._cv:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                head = next((it for it in self._queue if id(it) not in skip), None)
                if head is None:
                    return
                if head.settled:
                    # Settled by an attempt whose notification arrived after every waiter on it
                    # had already given up (timed out) and returned -- nobody was left to remove
                    # it from the queue at the time. A fresh drain() call must catch this itself,
                    # before ever treating a merely `not attempt_active` item as unattempted: that
                    # flag alone does not mean "never tried," only "no attempt is running right
                    # now," and a settled item can reach here with it already False.
                    try:
                        self._queue.remove(head)
                    except ValueError:
                        pass
                    continue
                if not head.attempt_active:
                    budget = min(_PART_DEADLINE_S, remaining)
                    head.attempt_active = True
                    head.attempt_deadline = time.monotonic() + budget
                    head.attempt_writer = writer
                    threading.Thread(
                        target=self._run_attempt, args=(writer, world_id, head, store), daemon=True
                    ).start()
                wait_s = max(0.0, min(head.attempt_deadline - time.monotonic(), remaining))

                def _settled_or_freed(head: _QueueItem = head) -> bool:
                    return head.settled or not head.attempt_active

                progressed = self._cv.wait_for(_settled_or_freed, timeout=wait_s)
                if head.settled:
                    try:
                        self._queue.remove(head)
                    except ValueError:
                        pass  # already removed by another concurrent drain() call for this world
                    continue
                if progressed:
                    # the attempt concluded without succeeding (a real exception, not a timeout):
                    # it does not block what comes after it this call.
                    skip.add(id(head))
                    continue
                # timed out waiting: presumed hung.
                if head.attempt_writer is writer:
                    # same instance as the one already presumed stuck -- do not retry (see
                    # docstring); leave it, and everything behind it, pending for this call.
                    return
                # a different writer is available (a genuine swap-in): abandon the old
                # bookkeeping -- never the orphaned thread itself -- and retry right now, against
                # the writer this call actually supplies.
                head.attempt_active = False
                continue


def _dispatch_state(store: Store) -> dict[tuple[str, str], object]:
    return store._dispatch_state  # type: ignore[return-value]


def _lock_for(store: Store, key: str) -> threading.Lock:
    with store._dispatch_lock:
        state = _dispatch_state(store)
        lock = state.get(("lock", key))
        if lock is None:
            lock = threading.Lock()
            state[("lock", key)] = lock
        return lock  # type: ignore[return-value]


def _locked(store: Store, world_ids: list[str]) -> ExitStack:
    """Acquires every touched world's lock, sorted, so two calls sharing worlds never deadlock."""
    stack = ExitStack()
    for w in sorted(set(world_ids)):
        stack.enter_context(_lock_for(store, w))
    return stack


def _consumer_for(store: Store, world_id: str) -> _WorldConsumer:
    with store._dispatch_lock:
        state = _dispatch_state(store)
        consumer = state.get(("consumer", world_id))
        if consumer is None:
            consumer = _WorldConsumer()
            state[("consumer", world_id)] = consumer
        return consumer  # type: ignore[return-value]


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
    vis included -- see _stop_all_owner_policies) and for enqueueing onto each touched world's own
    consumer; build_extra() runs under that same lock so pause's paused-flag check+set is atomic
    with it, and (round 7) its own part -- world.paused -- is enqueued ahead of everything else
    queued for the request's own world_id, never just appended behind it. Draining (writer I/O)
    happens after the lock is released, one thread per touched world, fully in parallel; only the
    order within one world's own queue is constrained. Returns (stopped, already_l1, pending)."""
    touched = _touched_worlds(store, world_id, world.owner)
    new_work: dict[str, list[dict]] = {}
    front_for_request_world: dict | None = None
    with _locked(store, touched):
        stopped, already_l1, new_parts = _stop_all_owner_policies(store, world.owner, world_id, "stop_all", at)
        for target_world_id, part in new_parts:
            new_work.setdefault(target_world_id, []).append(part)
        extra = build_extra() if build_extra is not None else None
        if extra is not None:
            front_for_request_world = extra
        for w in touched:
            front = [front_for_request_world] if (w == world_id and front_for_request_world is not None) else []
            _consumer_for(store, w).reconcile_and_extend(store, w, front, new_work.get(w, []))

    deadline = time.monotonic() + _BUDGET_S
    threads = [
        threading.Thread(target=_consumer_for(store, w).drain, args=(store, writer, w, deadline), daemon=True)
        for w in touched
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

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
        with _lock_for(store, f"policy:{policy_id}"):
            apply_level_change()
        return {"policy_id": policy_id, "level": "L1"}

    with _locked(store, [target_world_id]):
        apply_level_change()
        target_world = store.worlds.get(target_world_id)
        vis = policy_vis(policy, target_world.districts if target_world else None)
        part = policy_changed_part(policy_id=policy_id, change="revoked", owner=owner, at=at, vis=vis)
        # Flushes this world's whole pending backlog first (existing items reconciled ahead of
        # this call's own new part, oldest first, unchanged since round 5) -- revoke's own part is
        # never given the "front" treatment pause's world.paused gets.
        _consumer_for(store, target_world_id).reconcile_and_extend(store, target_world_id, [], [part])

    deadline = time.monotonic() + _BUDGET_S
    _consumer_for(store, target_world_id).drain(store, writer, target_world_id, deadline)
    return {"policy_id": policy_id, "level": "L1"}
