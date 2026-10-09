"""The meeting room (ADR-0028 decision 13, MROOM-A1 slice 1; contracts/meeting_room.rules.md MR-01 to MR-12).

`POST /v1/worlds/{id}/rooms`, `GET .../rooms/{room_id}`, `POST .../turns`, `POST .../adjourn`. A room is nothing but
its `meeting.*` events plus the redacted archive records they point at (rebuilt on every request); the words are only
ever in the archive (MR-12). Access is re-checked at every request (MR-03); a stranger's request is the same 404 as a
missing room. `/changes` is slice 1b. Seams with no production backing (archive, redactor, team store) refuse with
503 `not_configured`."""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from tilo_harness.untrusted import neutralise
from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.router import Router

from tilo_api import deps, events, spend, team_access, team_store
from tilo_api.meeting_room_config import RoomConfig, RoomConfigError, load_room_config
from tilo_api.meeting_room_reply import (
    FakeRoomModel,
    Reply,
    RoomCapped,
    RoomModel,
    RoomModelUnavailable,
    RouterRoomModel,
    _flagged,
    answer,
    ground,
    locate,
)
from tilo_api.people_writes import _capped_body

logger = logging.getLogger("tilo_api.meeting_room")
router = APIRouter(prefix="/v1/worlds/{world_id}/rooms", tags=["meeting-room"])
_ROOM_SCHEMA = "meeting_room.schema.json#/$defs/"
_TEAM_ROLES = {"Approver": "approver", "Member": "member"}
_WORKERS = ("specialist", "writer", "verifier")
_LOCKS: dict[str, threading.Lock] = {}  # room id -> the one turn in flight (MR-04); this process only
_WRITES: dict[str, threading.Lock] = {}  # room id -> check-open-and-write; dropped when the room closes
_WORLDS: dict[str, threading.Lock] = {}  # world id -> count-and-convene (open_rooms_per_world); this process only
_LOCKS_GUARD = threading.Lock()
_REPLIED = "events/data/meeting.replied.schema.json"
_EPS = 1e-9
NOT_FOUND = "That room or world was not found for this sign-in."  # the one 404 of every room route (MR-12)


def _refuse(status: int, error: str, **more: Any) -> JSONResponse:
    return JSONResponse({"error": error, **more}, status_code=status)


@dataclass
class Room:
    room_id: str
    world_id: str
    run_id: str
    convener: str
    lead: str
    agents: list[str]
    as_role: str
    vis: Any
    district: str | None
    credit_cap: float
    max_turns: int
    turns: list[dict] = field(default_factory=list)
    spent: float = 0.0
    state: str = "open"
    reason: str | None = None
    last_id: str = ""
    last_ts: str = ""


def rebuild(stream: list[dict]) -> dict[str, Room]:
    """Every room of a world, from its `meeting.*` events alone (MR-05 order: convened, ..., adjourned)."""
    rooms: dict[str, Room] = {}
    for e in stream:
        d = e.get("data") or {}
        room = rooms.get(str(d.get("room_id"))) if str(e["type"]).startswith("meeting.") else None
        if e["type"] == "meeting.convened":
            rooms[d["room_id"]] = room = Room(
                d["room_id"],
                e["world_id"],
                e["run_id"],
                e["actor"],
                d["lead"],
                list(d["agents"]),
                d["as_role"],
                e["vis"],
                e["district"],
                d["credit_cap"],
                d["max_turns"],
            )
        elif room is None:
            continue
        elif e["type"] == "meeting.asked":
            room.turns.append(
                {
                    "turn": d["turn"],
                    "to": d["to"],
                    "mode": d["mode"],
                    "ref": d["message_ref"],
                    "reply": None,
                    "event": e,
                }
            )
        elif e["type"] == "meeting.replied" and room.turns:
            room.turns[-1]["reply"] = {"from": e["actor"], "data": d}
            room.spent = math.fsum([room.spent, e["credits"]])
        elif e["type"] == "meeting.adjourned":
            room.state, room.reason = "adjourned", d["reason"]
        else:
            continue
        room.last_id, room.last_ts = e["id"], e["ts"]
    return rooms


def _part(etype: str, room: Room, actor: str, target: str, summary: str, data: dict, **more: Any) -> dict:
    return {
        "id": events.new_part_id(),
        "type": etype,
        "actor": actor,
        "target": target,
        "level": None,
        "district": more.pop("district", room.district),
        "item": None,
        "severity": "info",
        "credits": more.pop("credits", 0),
        "summary": summary,
        "cause": more.pop("cause", room.last_id or None),
        "vis": room.vis,
        "authz": None,
        "data": {"room_id": room.room_id, **data},
        **more,
    }


def _write(writer: deps.EventWriter, room: Room, part: dict) -> dict:
    try:
        return writer.append(room.world_id, part)
    except Exception as exc:
        raise deps.event_failure(room.world_id, exc) from None


def _lock_of(table: dict[str, threading.Lock], key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return table.setdefault(key, threading.Lock())


def _closing_id(room_id: str) -> str:
    return events.stable_part_id(room_id, "adjourned")  # one closing per room, whoever writes it first (MR-05)


def _drop_locks(room_id: str) -> None:
    with _LOCKS_GUARD:  # a closed room needs no locks; a late request makes a fresh one and finds it closed
        _LOCKS.pop(room_id, None)
        _WRITES.pop(room_id, None)


def _adjourn_part(room: Room, reason: str) -> dict:
    actor = room.convener if reason == "person" else "system"
    data = {"reason": reason, "turns": len(room.turns), "credits_spent": room.spent}
    part = _part("meeting.adjourned", room, actor, room.lead, "The Meeting Hall meeting ended.", data)
    return {**part, "id": _closing_id(room.room_id)}


def _closing_queued(store: deps.Store, world_id: str, room_id: str) -> bool:
    return any(
        isinstance(p, dict) and p.get("id") == _closing_id(room_id) for p in store.pending_events.get(world_id) or []
    )  # a closing waiting in the dispatcher's queue is a closing


def _adjourn(ctx: Ctx, room: Room, reason: str) -> None:
    """Closes the room once: re-reads it under the room's write lock, so no second adjourned and no reply after it."""
    with _lock_of(_WRITES, room.room_id):
        fresh = rebuild(ctx.stream()).get(room.room_id)
        queued = _closing_queued(ctx.store, ctx.world_id, room.room_id)
        if fresh is not None and fresh.state == "open" and queued:
            room.reason = "paused"
        elif fresh is not None and fresh.state == "open":
            _write(ctx.writer, fresh, _adjourn_part(fresh, reason))
            room.reason = reason
        else:
            room.reason = fresh.reason if fresh is not None else reason
        room.state = "adjourned"
    _drop_locks(room.room_id)


def adjourn_parts(store: deps.Store, world_id: str) -> list[dict]:
    """Pause all / Stop all (MR-05): one unwritten `meeting.adjourned` (paused) part per open room, no I/O. The
    dispatcher queues them AHEAD of `world.paused` under its usual deadlines, so a slow writer cannot hold it."""
    try:
        rooms = rebuild(list(store.events.get(world_id, []))).values()
        return [_adjourn_part(r, "paused") for r in rooms if r.state == "open"]
    except Exception as exc:
        logger.warning("rooms not adjourned for world %s (%s)", world_id, type(exc).__name__)
        return []


def _seam(request: Request, seam: Callable[[], Any]) -> Any:
    try:
        return request.app.dependency_overrides.get(seam, seam)()
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="not_configured") from None


def get_room_config() -> RoomConfig:
    try:
        return load_room_config()
    except RoomConfigError as exc:
        logger.warning("meeting room config unusable: %s", exc)
        raise HTTPException(status_code=503, detail="not_configured") from exc


def get_room_model(router: Annotated[Router, Depends(deps.get_router)]) -> RoomModel:
    return RouterRoomModel(router, deps.providers_config())


class _DevLines:
    """Dev mode's in-memory raw archive store (the dev run's own archive refuses appends); one per install."""

    def __init__(self) -> None:
        self.lines: dict[tuple[str, str], list[str]] = {}
        self.lock = threading.Lock()

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        with self.lock:
            self.lines.setdefault((org_id, run_id), []).append(line)

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        with self.lock:
            return list(self.lines.get((org_id, run_id), []))


def dev_overrides() -> dict[Callable[..., Any], Callable[..., Any]]:
    """Dev mode only (applied after the dev run's seams): a deterministic model that costs nothing, and an archive that
    keeps the room's words in memory. The redactor stays `dev_run.dev_redact`."""
    from tilo_archive import RunArchive  # noqa: PLC0415

    from tilo_api import dev_run  # noqa: PLC0415

    lines = _DevLines()
    redact = lambda p: {k: dev_run.dev_redact(v) if isinstance(v, str) else v for k, v in p.items()}  # noqa: E731

    def opener() -> Callable[..., Any]:
        dev_run._refuse()  # noqa: SLF001
        return lambda *, org_id, run_id: RunArchive(lines, org_id=org_id, run_id=run_id, redactor=redact)

    return {get_room_model: FakeRoomModel, deps.get_run_archive: opener}


def _as_role(
    principal: deps.Principal, world: deps.WorldRecord, cfg: RoomConfig, team: Callable, rooms: set
) -> str | None:
    """MR-03 / decision 7: the world's owner, or an Approver or Member of the team whose view covers every attendee's
    district. A Viewer, a demo session and the Director's room for anyone but the owner: None."""
    if principal.demo_session or principal.role == "viewer":
        return None
    if principal.role == "owner" and principal.user_id == world.owner:
        return "owner" if "Owner" in cfg.convene_roles else None
    state = team()
    role = state.roles.get(principal.user_id) if state is not None else None
    if role not in _TEAM_ROLES or role not in cfg.convene_roles or None in rooms:  # None: the Director's room
        return None
    return _TEAM_ROLES[role] if rooms <= set(principal.districts) else None


@dataclass
class Ctx:
    request: Request
    principal: deps.Principal
    world: deps.WorldRecord
    world_id: str
    cfg: RoomConfig
    store: deps.Store
    writer: deps.EventWriter
    now: Callable[[], str]

    def stream(self) -> list[dict]:
        return list(self.store.events.get(self.world_id, []))

    def team(self) -> Any:
        return team_store.team_reader(self.request.app.dependency_overrides)()

    def districts_of(self, room: Room, stream: list[dict]) -> set:
        layout = self.world.layout
        return {(locate(layout, stream, a) or ("", None))[1] for a in [room.lead, *room.agents]}

    def idle(self, room: Room) -> bool:
        gap = datetime.fromisoformat(self.now()) - datetime.fromisoformat(room.last_ts)
        return gap.total_seconds() > self.cfg.idle_timeout_s

    def housekeep(self, room: Room, *, check_access: bool = True) -> str | None:
        """Closes an open room whose convener lost access, or that is paused or idle; returns the reason, if any. The
        access check comes first: a request refused for it writes nothing but the `access_lost` it caused."""
        if room.state != "open":
            return None
        reason = None
        if check_access and self.principal.user_id == room.convener:
            held = _as_role(self.principal, self.world, self.cfg, self.team, self.districts_of(room, self.stream()))
            reason = None if held is not None else "access_lost"
        if reason is None:
            reason = "paused" if self.world.paused else "idle" if self.idle(room) else None
        if reason is not None:
            _adjourn(self, room, reason)
        return reason


async def _body(request: Request) -> Any:
    """The JSON body, refused with 413 above 32 KiB BEFORE it is read (BQ-PPL11C-1: the people writes' reader)."""
    sends = request.headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in request.headers
    if sends and request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")  # the people rule: no form or text/plain
    raw = await _capped_body(request)
    try:
        return json.loads(raw) if raw else None
    except Exception:  # not JSON, or nested past the parser's limit: the schema check answers 422
        return None


def get_ctx(
    world_id: str,
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    cfg: Annotated[RoomConfig, Depends(get_room_config)],
    now: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> Ctx:
    world = store.worlds.get(world_id)
    if principal.world_id != world_id or world is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)  # one message for unknown and not yours: no oracle
    return Ctx(request, principal, world, world_id, cfg, store, writer, now)


def _view(ctx: Ctx, room: Room) -> dict:
    """The room read model (meeting_room.schema.json root); the words come from the archive, never from an event."""
    records = {}
    refs = [r for t in room.turns for r in (t["ref"], t["reply"] and t["reply"]["data"]["message_ref"]) if r]
    if refs:
        archive = _seam(ctx.request, deps.get_run_archive)(org_id=deps.ORG_ID, run_id=room.run_id)
        records = {f"{room.run_id}/{r['seq']}": r["payload"] for r in archive.records()}

    def words(ref: str | None) -> str | None:
        text = (records.get(ref) or {}).get("text") if ref else None
        if ref and not isinstance(text, str):
            raise HTTPException(status_code=503, detail="store_unavailable")
        return text

    turns = []
    for t in room.turns:
        r = t["reply"]
        reply = None
        if r is not None:
            d = r["data"]
            proposal = d["proposal"] and {
                "proposal_id": d["proposal"]["proposal_id"],
                "units": d["proposal"]["units"],
                "artifacts": d["proposal"]["artifacts"],
            }
            reply = {
                "from": r["from"],
                "outcome": d["outcome"],
                "text": words(d["message_ref"]),
                "units": d["units"],
                "artifacts": d["artifacts"],
                "proposal": proposal,
            }
        turns.append(
            {
                "turn": t["turn"],
                "to": t["to"],
                "mode": t["mode"],
                "text": words(t["ref"]),
                "reply": reply,
                "change": None,
            }
        )
    return {
        "room_id": room.room_id,
        "world_id": room.world_id,
        "run_id": room.run_id,
        "state": room.state,
        "reason": room.reason,
        "lead": room.lead,
        "agents": room.agents,
        "as_role": room.as_role,
        "credit_cap": room.credit_cap,
        "credits_spent": room.spent,
        "max_turns": room.max_turns,
        "turns": turns,
    }


def _find(ctx: Ctx, room_id: str, *, convener_only: bool = False) -> Room:
    """The world's owner (reads) or the convener; anyone else, and a missing room, get the one 404 (MR-12). Only the
    convener speaks or closes a room: the events name them as the actor."""
    p, room = ctx.principal, rebuild(ctx.stream()).get(room_id)
    owner = p.role == "owner" and p.user_id == ctx.world.owner and not convener_only
    if room is None or not (owner or p.user_id == room.convener):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return room


@router.post("")
def convene(body: Annotated[Any, Depends(_body)], ctx: Annotated[Ctx, Depends(get_ctx)]) -> JSONResponse:
    p, layout, stream = ctx.principal, ctx.world.layout, ctx.stream()
    if p.demo_session:
        return _refuse(403, "demo_session")
    if p.role == "viewer":
        return _refuse(403, "not_allowed")
    if not conforms(_ROOM_SCHEMA + "convene_request", body):
        return _refuse(422, "bad_request")
    if layout is None:
        return _refuse(409, "no_layout")
    lead, agents = body["lead"], body["agents"]
    found = {a: locate(layout, stream, a) or ("", None) for a in [lead, *agents]}
    rank, district = found[lead]
    workers_ok = all(found[a][0] in _WORKERS and found[a][1] == district for a in agents)
    leads_ok = all(found[a][0] == "lead" for a in agents)
    ok = (rank == "lead" and district is not None and workers_ok) or (rank == "director" and leads_ok)
    if not ok or lead in agents or 1 + len(agents) > ctx.cfg.max_agents:
        return _refuse(422, "bad_attendees")
    districts = {found[a][1] for a in [lead, *agents]}
    as_role = _as_role(p, ctx.world, ctx.cfg, ctx.team, districts)
    if as_role is None:
        return _refuse(403, "not_allowed")
    with _lock_of(_WORLDS, ctx.world_id):  # count and write as one step (open_rooms_per_world)
        for open_room in (r for r in rebuild(ctx.stream()).values() if r.state == "open"):
            ctx.housekeep(open_room, check_access=False)  # sweep: an idle or paused room never blocks a new one
        if ctx.world.paused:
            return _refuse(409, "world_paused")
        stream = ctx.stream()
        if sum(r.state == "open" for r in rebuild(stream).values()) >= ctx.cfg.open_rooms_per_world:
            return _refuse(409, "room_open")
        vis = (
            [] if rank == "director" else sorted(d for d in districts if d)
        )  # SEC-07: the Director's room fails closed
        done = any(e["type"] in ("world.completed", "world.failed") for e in stream)
        cap = float(ctx.cfg.credit_cap)
        room = Room(
            events.new_part_id(), ctx.world_id, ctx.world.run_id, p.user_id, lead, list(agents), as_role, vis,
            district, cap, ctx.cfg.max_turns,
        )  # fmt: skip
        data = {
            "lead": lead,
            "agents": room.agents,
            "as_role": as_role,
            "run_state": "finished" if done else "live",
            "credit_cap": room.credit_cap,
            "max_turns": room.max_turns,
        }
        summary = "A person called the lead and its team into the Meeting Hall."
        _write(ctx.writer, room, _part("meeting.convened", room, p.user_id, lead, summary, data, cause=None))
    return JSONResponse(_view(ctx, room), status_code=201)


@router.get("/{room_id}")
def read_room(room_id: str, ctx: Annotated[Ctx, Depends(get_ctx)]) -> JSONResponse:
    room = _find(ctx, room_id)
    if ctx.housekeep(room) == "access_lost":
        return _refuse(403, "access_lost")
    if room.convener == ctx.principal.user_id and room.state != "open":  # a closed room's words need the access too
        held = _as_role(ctx.principal, ctx.world, ctx.cfg, ctx.team, ctx.districts_of(room, ctx.stream()))
        if held is None:
            return _refuse(403, "access_lost")
    return JSONResponse(_view(ctx, room))


@router.post("/{room_id}/adjourn")
def adjourn(room_id: str, _: Annotated[Any, Depends(_body)], ctx: Annotated[Ctx, Depends(get_ctx)]) -> JSONResponse:
    room = _find(ctx, room_id, convener_only=True)
    if ctx.housekeep(room) == "access_lost":
        return _refuse(403, "access_lost")
    if room.state == "open":
        _adjourn(ctx, room, "person")
    return JSONResponse(_view(ctx, room))


def _turn_lock(room_id: str) -> threading.Lock:
    return _lock_of(_LOCKS, room_id)


@router.post("/{room_id}/turns")
def ask(
    room_id: str,
    body: Annotated[Any, Depends(_body)],
    ctx: Annotated[Ctx, Depends(get_ctx)],
    model: Annotated[RoomModel, Depends(get_room_model)],
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    work_mode: Annotated[deps.Mode, Depends(deps.get_work_mode)],
    switches: Annotated[Any, Depends(deps.get_switches)],
) -> JSONResponse:
    room = _find(ctx, room_id, convener_only=True)
    if ctx.housekeep(room) == "access_lost":
        return _refuse(403, "access_lost")
    if ctx.world.paused:
        return _refuse(409, "world_paused")
    if room.state != "open":
        return _refuse(409, "room_closed", reason=room.reason)
    if not conforms(_ROOM_SCHEMA + "ask_request", body) or body["to"] not in [room.lead, *room.agents]:
        return _refuse(422, "bad_request")
    lock = _turn_lock(room_id)
    if not lock.acquire(blocking=False):
        return _refuse(409, "turn_in_flight")
    try:
        room = rebuild(ctx.stream())[room_id]  # fresh, inside the lock
        if room.turns and room.turns[-1]["reply"] is None:
            return _refuse(409, "turn_in_flight")
        return _turn(ctx, room, model, safety, body, _Mode(work_mode, switches))
    finally:
        lock.release()


def _data(turn: int, mode: str, reply: Reply, words: str | None) -> dict:
    proposal = None
    if reply.proposal is not None:
        units, arts = reply.proposal
        proposal = {
            "proposal_id": events.new_part_id(),
            "units": list(units),
            "artifacts": [{"artifact_id": a, "version": v} for a, v in arts],
        }
    return {
        "turn": turn,
        "mode": mode,
        "outcome": reply.outcome,
        "message_ref": words,
        "units": list(reply.units),
        "artifacts": [{"artifact_id": a, "version": v} for a, v in reply.artifacts],
        "proposal": proposal,
    }


def _finish(ctx: Ctx, room: Room, asked: dict, to: str, turn: int, mode: str, reply: Reply, archive: Any) -> bool:
    """Archives the reply text and writes `meeting.replied`; False when the room closed or the world paused while the
    call ran (nothing is written: no meeting event follows adjourned or world.paused, HR-1, MR-05). A reply that would
    not validate against the event schema is written as `failed`, its credits kept."""
    probe = {"room_id": room.room_id, **_data(turn, mode, reply, "r_x/1" if reply.text else None)}
    if not conforms(_REPLIED, probe):
        reply = Reply("failed", None, credits=reply.credits, trace=reply.trace)
    text = {"room_id": room.room_id, "turn": turn, "from": to, "text": reply.text, "outcome": reply.outcome}
    words = archive.append("channel_out", text) if reply.text is not None else None
    trace = {**reply.trace, "archive_ref": words} if reply.trace else None
    summary = {"failed": "No reply was recorded.", "declined": "The agent has nothing to say to that."}.get(
        reply.outcome, "The agent replied."
    )
    data = _data(turn, mode, reply, words)
    part = _part("meeting.replied", room, to, room.convener, summary, data, credits=reply.credits, cause=asked["id"])
    with _lock_of(_WRITES, room.room_id):
        fresh = rebuild(ctx.stream()).get(room.room_id)
        if (
            ctx.world.paused
            or fresh is None
            or fresh.state != "open"
            or _closing_queued(ctx.store, ctx.world_id, room.room_id)
        ):
            _drop_locks(room.room_id)
            return False
        _write(ctx.writer, room, {**part, "trace": trace} if trace else part)
    return True


@dataclass
class _Mode:
    mode: str
    switches: Any


class _RoomLimit(Exception):
    """The room's pseudo run has no unit left on the ledger (`run_minor`): answered 409 `room_limit`."""


@dataclass
class _Held:
    """One model call's hold on the uid ledger (SEC-16): the guard, its plan and the unit it reserved."""

    guard: spend.SpendGuard
    plan: spend.UnitPlan
    unit_minor: int


def _hold(ctx: Ctx, room: Room, turn: int, how: _Mode) -> _Held | None:
    """SEC-16, as `deps._spend_mode` and Quick do: live only, the uid cap lowered by the team limits (unreadable is 0),
    one unit reserved on the room's pseudo run before the call. Raises what the run path raises (403 spend_cap_reached,
    503 replay-only) before anything is written. Replay makes no paid call, so it holds nothing."""
    if how.mode != "live":
        return None
    caps, uid = deps.caps_for(ctx.request), ctx.principal.user_id
    if not (isinstance(how.switches, spend.Switches) and how.switches.ledger is not None and caps is not None):
        raise deps.ReplayOnly
    try:
        cap = team_access.user_cap_minor(ctx.team(), uid, caps.uid_lifetime_minor)
    except Exception as exc:
        logger.warning("team limits unreadable, so the room call is denied: %s", type(exc).__name__)
        cap = 0
    if cap <= 0:
        raise spend.SpendCapReached
    guard = spend.SpendGuard(
        how.switches.ledger,
        how.switches.flags,
        dataclasses.replace(caps, uid_lifetime_minor=min(cap, caps.uid_lifetime_minor)),
    )
    if guard.uid_capped(uid) or not guard.live_allowed(uid):  # the team-lowered cap is the guard's, not the ledger's
        raise spend.SpendCapReached
    plan = guard.begin_unit(
        "live",
        uid=uid,
        run_id=room_run(room.room_id),
        org_id=deps.ORG_ID,
        estimate_minor=caps.unit_reserve_minor,
        at=datetime.now(UTC),
    )
    if plan.reservation is None:
        if plan.reason == "run":  # the room's pseudo run is full: the room's own limit, not a replay-only switch
            raise _RoomLimit
        raise spend.SpendCapReached if plan.reason == "uid_lifetime" else deps.ReplayOnly
    return _Held(guard, plan, caps.unit_reserve_minor)


def room_run(room_id: str) -> str:
    return f"r_room_{room_id}"  # the room's own pseudo run on the ledger: the run's budget pays for none of it


def _charge(ctx: Ctx, room: Room, turn: int, held: _Held | None, reply: Reply) -> None:
    """Settles the hold and writes one ledger row, with the credits actually spent (also after an error)."""
    called = reply.credits > 0 or reply.trace is not None
    if held is not None:
        (held.guard.settle_unit(held.plan, held.unit_minor) if called else held.guard.abort_unit(held.plan))
    writer = deps.ledger_writer_for(ctx.request)
    if writer is None or reply.credits <= 0:
        return
    t = reply.trace or {}
    ok = (
        isinstance(t.get("profile"), str)
        and isinstance(t.get("tokens_in"), int)
        and isinstance(t.get("tokens_out"), int)
    )
    usage = Usage(t["profile"], max(t["tokens_in"], 0), max(t["tokens_out"], 0)) if ok else None
    entry = LedgerEntry(
        "commit", room_run(room.room_id), ctx.principal.user_id, deps.ORG_ID, datetime.now(UTC),
        step=f"turn_{turn}", credits=float(reply.credits), usage=usage,
    )  # fmt: skip
    try:
        writer.append(entry)
    except Exception as exc:
        logger.warning("room ledger write failed: %s", type(exc).__name__)


def _turn(ctx: Ctx, room: Room, model: RoomModel, safety: SafetyProvider, body: dict, how: _Mode) -> JSONResponse:
    stream, to, mode = ctx.stream(), body["to"], body["mode"]
    try:
        quote = model.quote(mode)
    except RoomModelUnavailable:
        raise HTTPException(status_code=503, detail="not_configured") from None
    left = room.credit_cap - room.spent
    if len(room.turns) >= room.max_turns or quote > left + _EPS:  # MR-08: refused before any call, and the room closes
        _adjourn(ctx, room, "capped")
        return _refuse(409, "room_closed", reason="capped")
    grounding = ground(ctx.world.layout, stream, to)
    if grounding is None:
        return _refuse(422, "bad_request")
    redact = _seam(ctx.request, deps.get_redactor)
    archive = _seam(ctx.request, deps.get_run_archive)(org_id=deps.ORG_ID, run_id=room.run_id)
    turn = len(room.turns) + 1
    try:
        held = _hold(ctx, room, turn, how)
    except _RoomLimit:
        return _refuse(409, "room_limit")
    try:
        ref = archive.append(
            "channel_in", {"room_id": room.room_id, "turn": turn, "to": to, "mode": mode, "text": redact(body["text"])}
        )
        summary = "A person asked an agent something in the Meeting Hall."
        data = {"turn": turn, "to": to, "mode": mode, "message_ref": ref}
        asked = _write(ctx.writer, room, _part("meeting.asked", room, room.convener, to, summary, data))
    except BaseException as exc:  # nothing was sent to a model: the hold is released
        if held is not None:
            held.guard.abort_unit(held.plan)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="write_failed") from None
    try:
        reply = answer(model, grounding, body["text"], mode, safety=safety, redact=redact, budget=left)
    except BaseException as exc:
        if held is not None:
            held.guard.abort_unit(held.plan)
        if not isinstance(exc, RoomCapped):
            raise
        _adjourn(ctx, room, "capped")
        return _refuse(409, "room_closed", reason="capped")
    _charge(ctx, room, turn, held, reply)  # before the write: a failed write still leaves the call charged
    try:
        written = _finish(ctx, room, asked, to, turn, mode, reply, archive)
    except Exception:  # decision 10: the turn closes `failed` with no text; if even that fails, so does the room
        try:
            written = _finish(ctx, room, asked, to, turn, mode, Reply("failed", None, credits=reply.credits), archive)
        except Exception:
            try:
                _adjourn(ctx, room, "failed")
            except Exception:
                logger.warning("room %s could not be closed after a write error", room.room_id)
            raise HTTPException(status_code=503, detail="write_failed") from None
    if not written:
        return _refuse(409, "world_paused" if ctx.world.paused else "room_closed")
    return JSONResponse(_view(ctx, rebuild(ctx.stream())[room.room_id])["turns"][-1], status_code=202)


def _proposal_of(room: Room, proposal_id: str) -> tuple[dict, str] | None:
    for t in room.turns:
        r = t["reply"]
        if r and r["data"]["outcome"] == "proposed_change" and r["data"]["proposal"]["proposal_id"] == proposal_id:
            return r["data"]["proposal"], r["from"]
    return None


@router.post("/{room_id}/changes")
def confirm_change(
    room_id: str,
    body: Annotated[Any, Depends(_body)],
    ctx: Annotated[Ctx, Depends(get_ctx)],
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    planner: Annotated[Callable[[dict], Any] | None, Depends(deps.get_change_planner)],
) -> JSONResponse:
    """MR-07: the person confirms the proposal an agent showed, in its words or their own. Units, artifacts and
    the agent come from the proposal's `meeting.replied`, never from the body. Not a side effect (MR-11): no
    `world.requested`, no `plan.revised` (the revision planner is MR-H2; without one: `planning: pending`)."""
    room = _find(ctx, room_id, convener_only=True)
    if ctx.housekeep(room) == "access_lost":
        return _refuse(403, "access_lost")
    if ctx.world.paused:
        return _refuse(409, "world_paused")
    if room.state != "open":
        return _refuse(409, "room_closed", reason=room.reason)
    if not conforms(_ROOM_SCHEMA + "change_request", body):
        return _refuse(422, "bad_request")
    text = body["text"]
    try:
        clean = neutralise(text, limit=2000)
        if _flagged(safety, text) or (clean != text and _flagged(safety, clean)):
            return _refuse(422, "declined")
    except Exception:  # an outage is never "not flagged"
        return _refuse(503, "screen_unavailable")
    redact = _seam(ctx.request, deps.get_redactor)
    archive = _seam(ctx.request, deps.get_run_archive)(org_id=deps.ORG_ID, run_id=room.run_id)
    with _lock_of(_WRITES, room_id):  # check, archive and write as one step: a proposal is confirmed once
        fresh = rebuild(ctx.stream()).get(room_id)
        if (
            ctx.world.paused
            or fresh is None
            or fresh.state != "open"
            or _closing_queued(ctx.store, ctx.world_id, room_id)
        ):
            return _refuse(409, "world_paused" if ctx.world.paused else "room_closed")
        found = _proposal_of(fresh, body["proposal_id"])
        if found is None:
            return _refuse(409, "not_a_proposal")
        proposal, agent = found
        done = [
            (e.get("data") or {}).get("proposal_id")
            for e in ctx.stream()
            if e["type"] == "meeting.change_requested" and (e.get("data") or {}).get("room_id") == room_id
        ]
        if proposal["proposal_id"] in done:
            return _refuse(409, "already_confirmed")
        if len(done) >= ctx.cfg.max_changes:
            return _refuse(409, "max_changes")
        ref = archive.append(
            "channel_in",
            {"room_id": room_id, "proposal_id": proposal["proposal_id"], "to": agent, "text": redact(text)},
        )
        data = {
            "proposal_id": proposal["proposal_id"],
            "to": agent,
            "units": proposal["units"],
            "artifacts": proposal["artifacts"],
            "as_role": fresh.as_role,
            "message_ref": ref,
        }
        summary = "The convener confirmed a change; it goes to planning."
        event = _write(
            ctx.writer, fresh, _part("meeting.change_requested", fresh, fresh.convener, agent, summary, data)
        )
    started = False
    if planner is not None:  # MR-H2's hook; it writes plan.revised itself. A failure leaves the request recorded
        try:
            planner(event)
            started = True
        except Exception as exc:
            logger.warning("change planner failed for room %s: %s", room_id, type(exc).__name__)
    answer_ = {"proposal_id": proposal["proposal_id"], "to": agent, "units": proposal["units"]}
    return JSONResponse(
        {**answer_, "artifacts": proposal["artifacts"], "planning": "started" if started else "pending"},
        status_code=202,
    )
