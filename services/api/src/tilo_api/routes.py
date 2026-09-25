"""Kill switches (FR-HIL-07, PI-13, PI-18) and roles/redaction (FR-HIL-09, SEC-07), per the exact
shape in services/api/tests/API_ST3a.md (round 5). Only the policy owner stops, pauses or
revokes; a non-member/non-owner gets the same 404 as unknown (no oracle).

Locking: the fast, no-I/O mutation (policy level/history/changed_by, world.paused) happens under
per-world locks (never one global lock, so world A never waits on world B); every write to
store.events/pending_events happens strictly outside that lock, in per-world order, bounded so a
writer that never returns cannot hold a request past its 5s budget.

GET routes rebuild every kept event by allowlisting, never copying it forward; for a non-owner,
an event naming a hidden district anywhere -- `district`, `target`, `actor`, or any `data` leaf
or key, at any depth -- is dropped whole, never returned with a field blanked.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
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
_MAX_DATA_DEPTH = 60  # a scoped viewer fails closed (event dropped) past this; the owner never walks data at all
_WRITE_BUDGET_S = 3.5  # one world's whole batch, split across its parts, leaves margin under the 5s route budget
_MAX_PART_DEADLINE_S = 0.5  # caps any single part's wait so a *small* batch against a hung writer still
# returns quickly (a 1-part batch would otherwise get the whole budget to itself)
_POLL_S = 0.0005  # this platform's thread-wait timer granularity makes a single sub-30ms blocking
# wait unreliable (observed overshooting by 10x); busy-polling in small increments is precise

# Per-world locks, never one global lock: two calls against the same world serialize; two
# against different worlds never wait on each other. `_locks_guard` only ever protects the dict
# lookup itself.
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
    never returned with a field nulled (round-5 finding 1)."""
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
        "trace": trace,
    }


def _pend(store: Store, world_id: str, part: dict) -> None:
    with _lock_for(world_id):
        store.pending_events.setdefault(world_id, []).append(part)


def _settled(future: Future[dict], deadline_s: float) -> bool:
    """True once `future` completes within deadline_s. Busy-polls in small increments rather
    than a single blocking wait: a single sub-30ms `Future.result(timeout=...)` proved unreliable
    on this platform (observed overshooting by 10x, defeating the deadline's whole purpose)."""
    end = time.perf_counter() + deadline_s
    while time.perf_counter() < end:
        if future.done():
            return True
        time.sleep(_POLL_S)
    return future.done()


def _write_world(store: Store, writer: EventWriter, world_id: str, parts: list[dict]) -> None:
    """Attempts every part for one world, one at a time, build order first: a call is never
    invoked for part i+1 until part i has settled, so commit order always matches build order
    (finding 3). Each attempt gets up to _MAX_PART_DEADLINE_S (finding 2: a hung writer must
    never hold a part, or the request, past budget) -- one that misses it is left running
    (uncancelled) and queued pending. The deadline is shared over the whole batch, not divided
    per part: a batch of fast/successful parts is never cut short for being long, while a batch
    whose parts are each individually slow stops *attempting* further ones once the shared
    budget is gone, rather than exceeding it one slow part at a time."""
    if not parts:
        return
    deadline = time.perf_counter() + _WRITE_BUDGET_S
    pool = ThreadPoolExecutor(max_workers=len(parts))
    try:
        for part in parts:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                _pend(store, world_id, part)
                continue
            future = pool.submit(writer.append, world_id, part)
            if not _settled(future, min(_MAX_PART_DEADLINE_S, remaining)) or future.exception() is not None:
                _pend(store, world_id, part)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _dispatch(store: Store, writer: EventWriter, work: dict[str, list[dict]]) -> None:
    """One thread per touched world (round-5 finding 3: different worlds run in parallel; a
    single world's own parts stay ordered, handled inside _write_world)."""
    threads = [
        threading.Thread(target=_write_world, args=(store, writer, w, parts)) for w, parts in work.items() if parts
    ]
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
    """PI-13/PI-18: plan every owned policy first, then apply -- never half-applies, never 500s.
    L0 stays untouched. A policy is skipped as already_l1 only when *provably* consistent (level
    == "L1" and its own history agrees too, "no silent history repair"); anything else (including
    a missing/malformed level, or an L1 whose history disagrees) is lowered with one history
    entry and one policy.changed, vis computed against its own target world."""
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


def _stop_all_and_dispatch(
    store: Store,
    writer: EventWriter,
    world: WorldRecord,
    world_id: str,
    at: str,
    build_extra: Callable[[], dict | None] | None = None,
) -> tuple[int, int, int]:
    """Shared body of stop/pause: lock every touched world just for the drain-and-apply (no I/O),
    build_extra() runs under that same lock so pause's paused-flag check+set is atomic with it,
    then dispatch every touched world's batch outside the lock. Returns (stopped, already_l1, pending)."""
    touched = _touched_worlds(store, world_id, world.owner)
    work: dict[str, list[dict]] = {}
    with _locked(touched):
        for w in touched:
            work[w] = store.pending_events.pop(w, [])
        stopped, already_l1, new_parts = _stop_all_owner_policies(store, world.owner, world_id, "stop_all", at)
        for target_world_id, part in new_parts:
            work.setdefault(target_world_id, []).append(part)
        extra = build_extra() if build_extra is not None else None
        if extra is not None:
            work.setdefault(world_id, []).append(extra)

    _dispatch(store, writer, work)
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

    def build_paused_part() -> dict | None:
        if world.paused:  # sole dedupe: the flag, checked/set under stop_all_and_dispatch's lock
            return None
        world.paused = True
        return world_paused_part(world_id=world_id, owner=world.owner, channel=body.channel)

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
        apply_level_change()
        return {"policy_id": policy_id, "level": "L1"}

    with _locked([target_world_id]):
        work = store.pending_events.pop(target_world_id, [])  # flush this world's whole backlog first
        apply_level_change()
        target_world = store.worlds.get(target_world_id)
        vis = policy_vis(policy, target_world.districts if target_world else None)
        work.append(policy_changed_part(policy_id=policy_id, change="revoked", owner=owner, at=at, vis=vis))

    _dispatch(store, writer, {target_world_id: work})
    return {"policy_id": policy_id, "level": "L1"}


@router.get("/worlds/{world_id}/events")
def get_world_events(
    world_id: str,
    principal: Principal = Depends(get_current_principal),
    store: Store = Depends(get_store),
) -> JSONResponse:
    world = _require_member_world(principal, store, world_id)
    is_owner = _is_owner(principal, world.owner)
    safe_districts = _safe_districts(principal.districts)

    well_formed = [e for e in store.events.get(world_id, []) if not _is_malformed_event(e)]
    visible = [e for e in well_formed if _visible(is_owner, e.get("vis"), safe_districts)]

    if is_owner:
        # A JSONResponse (stdlib json, not FastAPI's pydantic-based response serialization,
        # which has its own much shallower recursion/depth guard): the owner's data is returned
        # exactly as stored, however deeply nested (round-5 finding 5), and must not 500 either.
        return JSONResponse(content={"events": [_owner_event_view(e) for e in visible]})

    surviving = [e for e in visible if not _event_hides_district(e, safe_districts)]
    id_map = {e["id"]: f"v{i + 1}" for i, e in enumerate(surviving)}
    events = [_scoped_event_view(e, i + 1, id_map, safe_districts) for i, e in enumerate(surviving)]
    return JSONResponse(content={"events": events})


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
