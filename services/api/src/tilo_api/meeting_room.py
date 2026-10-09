"""The meeting room (ADR-0028 decision 13, MROOM-A1 slice 1; contracts/meeting_room.rules.md MR-01 to MR-12).

`POST /v1/worlds/{id}/rooms`, `GET .../rooms/{room_id}`, `POST .../turns`, `POST .../adjourn`. A room is nothing but
its `meeting.*` events plus the redacted archive records they point at (rebuilt on every request); the words are only
ever in the archive (MR-12). Access is re-checked at every request (MR-03); a stranger's request is the same 404 as a
missing room. `/changes` is slice 1b. Seams with no production backing (archive, redactor, team store) refuse with
503 `not_configured`."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.router import Router

from tilo_api import deps, events, team_store
from tilo_api.meeting_room_config import RoomConfig, RoomConfigError, load_room_config
from tilo_api.meeting_room_reply import (
    FakeRoomModel,
    RoomCapped,
    RoomModel,
    RoomModelUnavailable,
    RouterRoomModel,
    answer,
    ground,
    locate,
)

logger = logging.getLogger("tilo_api.meeting_room")
router = APIRouter(prefix="/v1/worlds/{world_id}/rooms", tags=["meeting-room"])
_ROOM_SCHEMA = "meeting_room.schema.json#/$defs/"
_TEAM_ROLES = {"Approver": "approver", "Member": "member"}
_WORKERS = ("specialist", "writer", "verifier")
_LOCKS: dict[str, threading.Lock] = {}  # room id -> the one turn in flight (MR-04); this process only
_LOCKS_GUARD = threading.Lock()
_EPS = 1e-9


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


def _adjourn(writer: deps.EventWriter, room: Room, reason: str) -> None:
    actor = room.convener if reason == "person" else "system"
    data = {"reason": reason, "turns": len(room.turns), "credits_spent": room.spent}
    _write(writer, room, _part("meeting.adjourned", room, actor, room.lead, "The Meeting Hall meeting ended.", data))
    room.state, room.reason = "adjourned", reason


def adjourn_open_rooms(store: deps.Store, world_id: str, writer: deps.EventWriter) -> None:
    """Pause all / Stop all (MR-05): every open room of the world closes (`paused`) before `world.paused` is written.
    Best effort: a failed write is logged and never blocks the kill switch (an open room closes on its next access)."""
    try:
        for room in rebuild(list(store.events.get(world_id, []))).values():
            if room.state == "open":
                _adjourn(writer, room, "paused")
    except Exception as exc:
        logger.warning("rooms not adjourned for world %s (%s)", world_id, type(exc).__name__)


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


def get_room_user_cap() -> Callable[[str], float | None]:
    """The convener's remaining per-user credits (SEC-16, lowered by their team role); None = no source wired, so the
    room's own cap is the only limit (BQ-MROOM-A1-4)."""
    return lambda user: None


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
    redact = lambda p: {**p, "text": dev_run.dev_redact(p["text"])} if isinstance(p.get("text"), str) else p  # noqa: E731

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
        """Closes an open room that is idle, paused or whose convener lost access; returns the new reason, if any."""
        if room.state != "open":
            return None
        reason = None
        if self.world.paused:
            reason = "paused"
        elif check_access and self.principal.user_id == room.convener:
            held = _as_role(self.principal, self.world, self.cfg, self.team, self.districts_of(room, self.stream()))
            reason = None if held is not None else "access_lost"
        if reason is None and self.idle(room):
            reason = "idle"
        if reason is not None:
            _adjourn(self.writer, room, reason)
        return reason


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
        raise HTTPException(status_code=404)  # the same 404 as an unknown world: no membership oracle
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
        raise HTTPException(status_code=404)
    return room


@router.post("")
def convene(ctx: Annotated[Ctx, Depends(get_ctx)], body: Annotated[Any, Body()] = None) -> JSONResponse:
    p, layout, stream = ctx.principal, ctx.world.layout, ctx.stream()
    if p.demo_session:
        return _refuse(403, "demo_session")
    if p.role == "viewer":
        return _refuse(403, "not_allowed")
    if not conforms(_ROOM_SCHEMA + "convene_request", body):
        return _refuse(422, "bad_request")
    if layout is None:
        return _refuse(409, "no_layout")
    for open_room in (r for r in rebuild(stream).values() if r.state == "open"):
        ctx.housekeep(open_room, check_access=False)  # sweep on access: an idle or paused room never blocks a new one
    if ctx.world.paused:
        return _refuse(409, "world_paused")
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
    if sum(r.state == "open" for r in rebuild(ctx.stream()).values()) >= ctx.cfg.open_rooms_per_world:
        return _refuse(409, "room_open")
    left = _seam(ctx.request, get_room_user_cap)(p.user_id)
    if left is not None and left <= 0:
        return _refuse(429, "cap_reached")
    vis = "all" if rank == "director" else sorted(d for d in districts if d)
    done = any(e["type"] in ("world.completed", "world.failed") for e in stream)
    room = Room(
        events.new_part_id(),
        ctx.world_id,
        ctx.world.run_id,
        p.user_id,
        lead,
        list(agents),
        as_role,
        vis,
        district,
        float(ctx.cfg.credit_cap if left is None else min(ctx.cfg.credit_cap, left)),
        ctx.cfg.max_turns,
    )
    data = {
        "lead": lead,
        "agents": room.agents,
        "as_role": as_role,
        "run_state": "finished" if done else "live",
        "credit_cap": room.credit_cap,
        "max_turns": room.max_turns,
    }
    _write(
        ctx.writer,
        room,
        _part(
            "meeting.convened",
            room,
            p.user_id,
            lead,
            "A person called the lead and its team into the Meeting Hall.",
            data,
            cause=None,
        ),
    )
    return JSONResponse(_view(ctx, room), status_code=201)


@router.get("/{room_id}")
def read_room(room_id: str, ctx: Annotated[Ctx, Depends(get_ctx)]) -> JSONResponse:
    room = _find(ctx, room_id)
    if ctx.housekeep(room) == "access_lost":
        return _refuse(403, "access_lost")
    return JSONResponse(_view(ctx, room))


@router.post("/{room_id}/adjourn")
def adjourn(room_id: str, ctx: Annotated[Ctx, Depends(get_ctx)]) -> JSONResponse:
    room = _find(ctx, room_id, convener_only=True)
    if ctx.housekeep(room) == "access_lost":
        return _refuse(403, "access_lost")
    if room.state == "open":
        _adjourn(ctx.writer, room, "person")
    return JSONResponse(_view(ctx, room))


def _turn_lock(room_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(room_id, threading.Lock())


@router.post("/{room_id}/turns")
def ask(
    room_id: str,
    ctx: Annotated[Ctx, Depends(get_ctx)],
    model: Annotated[RoomModel, Depends(get_room_model)],
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    body: Annotated[Any, Body()] = None,
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
        return _turn(ctx, room, model, safety, body)
    finally:
        lock.release()


def _turn(ctx: Ctx, room: Room, model: RoomModel, safety: SafetyProvider, body: dict) -> JSONResponse:
    stream, to, mode = ctx.stream(), body["to"], body["mode"]
    try:
        quote = model.quote(mode)
    except RoomModelUnavailable:
        raise HTTPException(status_code=503, detail="not_configured") from None
    left = room.credit_cap - room.spent
    if len(room.turns) >= room.max_turns or quote > left + _EPS:  # MR-08: refused before any call, and the room closes
        _adjourn(ctx.writer, room, "capped")
        return _refuse(409, "room_closed", reason="capped")
    grounding = ground(ctx.world.layout, stream, to)
    if grounding is None:
        return _refuse(422, "bad_request")
    redact = _seam(ctx.request, deps.get_redactor)
    archive = _seam(ctx.request, deps.get_run_archive)(org_id=deps.ORG_ID, run_id=room.run_id)
    turn, target = len(room.turns) + 1, grounding.district
    try:
        ref = archive.append(
            "channel_in", {"room_id": room.room_id, "turn": turn, "to": to, "mode": mode, "text": redact(body["text"])}
        )
    except Exception:
        raise HTTPException(status_code=503, detail="write_failed") from None
    asked = _write(
        ctx.writer,
        room,
        _part(
            "meeting.asked",
            room,
            room.convener,
            to,
            "A person asked an agent something in the Meeting Hall.",
            {"turn": turn, "to": to, "mode": mode, "message_ref": ref},
            district=target,
        ),
    )
    try:
        reply = answer(model, grounding, body["text"], mode, safety=safety, redact=redact, budget=left)
    except RoomCapped:
        _adjourn(ctx.writer, room, "capped")
        return _refuse(409, "room_closed", reason="capped")
    words = None
    if reply.text is not None:
        try:
            words = archive.append(
                "channel_out",
                {"room_id": room.room_id, "turn": turn, "from": to, "text": reply.text, "outcome": reply.outcome},
            )
        except Exception:
            raise HTTPException(status_code=503, detail="write_failed") from None
    proposal = None
    if reply.proposal is not None:
        proposal = {
            "proposal_id": events.new_part_id(),
            "units": list(reply.proposal[0]),
            "artifacts": [{"artifact_id": a, "version": v} for a, v in reply.proposal[1]],
        }
    data = {
        "turn": turn,
        "mode": mode,
        "outcome": reply.outcome,
        "message_ref": words,
        "units": list(reply.units),
        "artifacts": [{"artifact_id": a, "version": v} for a, v in reply.artifacts],
        "proposal": proposal,
    }
    trace = {**(reply.trace or {}), "archive_ref": words} if reply.trace else None
    extra = {"trace": trace} if trace else {}
    summary = {"failed": "No reply was recorded.", "declined": "The agent has nothing to say to that."}.get(
        reply.outcome, "The agent replied."
    )
    _write(
        ctx.writer,
        room,
        _part(
            "meeting.replied",
            room,
            to,
            room.convener,
            summary,
            data,
            district=target,
            credits=reply.credits,
            cause=asked["id"],
            **extra,
        ),
    )
    return JSONResponse(_view(ctx, rebuild(ctx.stream())[room.room_id])["turns"][-1], status_code=202)
