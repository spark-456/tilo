"""Team routes on tilo-api (FR-TEAM-02, FR-TEAM-04, FR-ACC-01; issues #621, #629).

`GET /v1/team` and the writes under it. Identity is the verified `deps.Principal` only; the actor's team role is the
STORED roles map's, never the session's or the body's; time is the server clock. A person outside the team gets one
404 body on every route. Only the Owner writes (BQ-TEAMACC-2; PRD 10.1 gives the Approver no policy rights). Writes
read only `application/json` (415), take closed bodies (422), are refused while replay-only (503), and are applied with
the store's compare-and-set, re-checked on the fresh state after a lost race. Every refusal from `team_rules` maps to
a 4xx; a broken store or config is a 503 that never echoes the cause. A change is logged as one ids-only line
(`team_rule_changed`): no registered event fits yet (BQ-TEAMACC-1).
"""

from __future__ import annotations

import logging
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from tilo_metering.flags import FlagStore

from tilo_api import deps
from tilo_api.people_writes import valid_email
from tilo_api.tasks import _json_body
from tilo_api.team_rules import ROLES, MustAskLocked, RoleChangeRefused, load_capabilities, load_switches, set_switch
from tilo_api.team_store import (
    LEVELS,
    TeamRepository,
    TeamState,
    apply_role_change,
    effective_switches,
    get_team_store,
)

logger = logging.getLogger("tilo_api.team_routes")
router = APIRouter()

Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Store = Annotated[TeamRepository, Depends(get_team_store)]
Flags = Annotated[FlagStore, Depends(deps.get_flag_store)]
Clock = Annotated[Callable[[], str], Depends(deps.get_clock)]
_NOT_FOUND = "No such team."
_ATTEMPTS = 5
MAX_LIMIT_MINOR = 10**12  # 10 billion INR: anything above is a typo, never a limit
MAX_INVITES = 100  # pending invites at once
_SESSIONS = frozenset({"web", "mobile_web"})
_REFUSED = {"not_allowed": 403, "own_role": 409, "last_owner": 409, "unknown": 404}


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RoleIn(_Closed):
    role: str


class LimitIn(_Closed):
    limit_minor: Annotated[int, Field(ge=0, le=MAX_LIMIT_MINOR)] | None


class SwitchIn(_Closed):
    on: bool


class ToolIn(_Closed):
    level: str


class InviteIn(_Closed):
    email: Annotated[str, Field(max_length=254)]
    role: str

    @field_validator("email")
    @classmethod
    def _address(cls, value: str) -> str:
        """ASCII only, like the people directory, and no control or format character: a 422 never names it."""
        if any(unicodedata.category(c) in ("Cc", "Cf") for c in value) or not valid_email(value):
            raise ValueError("email")
        return value


class _StoreFailed(Exception):
    """The store could not be read or written: a 503, never a member 404."""


def _session(principal: deps.Principal) -> None:
    """Team settings are admin settings: only a full web or mobile_web sign-in session (server-set, BQ-XWORLD-10)."""
    if not (principal.full_session is True and principal.channel in _SESSIONS):
        raise HTTPException(status_code=403, detail="Sign in on the web to manage the team.")


def _member(state: TeamState, principal: deps.Principal) -> str:
    role = state.roles.get(principal.user_id)
    if role is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return role


def _owner(state: TeamState, principal: deps.Principal) -> None:
    if _member(state, principal) != "Owner":
        raise HTTPException(status_code=403, detail="Only the Owner can change this.")


def _view(state: TeamState, principal: deps.Principal) -> dict[str, Any]:
    try:
        return _view_of(state, principal)
    except Exception as exc:  # a broken config file: closed, never the cause
        logger.warning("team view refused (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="not_configured") from exc


def _view_of(state: TeamState, principal: deps.Principal) -> dict[str, Any]:
    me = state.roles[principal.user_id]
    sees_all = me == "Owner"  # a personal limit is the person's and the Owner's only
    switches, rows = effective_switches(state), [(k, s.must_ask) for k, s in load_switches().items()]
    return {
        "version": state.version,
        "me": {"id": principal.user_id, "role": me},
        "members": [
            {"id": p, "role": r, "limit_minor": state.limits.get(p) if sees_all or p == principal.user_id else None}
            for p, r in sorted(state.roles.items())
        ],
        "switches": [{"key": k, "on": switches[k], "must_ask": must} for k, must in rows],
        "tools": [{"connector": c, "level": state.tools.get(c, "act")} for c in deps.get_connector_registry().ids()],
        "capabilities": [
            {"key": c.key, "label": c.label, "roles": list(c.roles)} for c in load_capabilities().values()
        ],
        "invites": [{"id": i, **v} for i, v in sorted(state.invites.items())] if sees_all else [],
    }


def _write(
    store: TeamRepository, principal: deps.Principal, flags: FlagStore, change: Callable[[TeamState], TeamState]
) -> TeamState:
    """Read, check membership, refuse while replay-only, apply `change` (which checks the actor) and compare-and-set;
    a lost race reads again and re-checks everything on the fresh state."""
    _session(principal)
    try:
        for attempt in range(_ATTEMPTS):
            state = _stored(store.read)
            _member(state, principal)
            if attempt == 0:
                deps.refuse_if_replay_only(flags)
            new = change(state)
            if _stored(lambda: store.compare_and_set(state.version, new)):
                return replace(new, version=state.version + 1)
        raise HTTPException(status_code=409, detail="Someone else changed the team. Try again.")
    except (HTTPException, deps.ReplayOnly):
        raise
    except _StoreFailed as exc:
        logger.warning("team store refused (%s)", type(exc.__cause__).__name__)
        raise HTTPException(status_code=503, detail="not_configured") from exc
    except RoleChangeRefused as exc:
        raise HTTPException(status_code=_REFUSED.get(exc.reason, 409), detail=f"refused: {exc.reason}") from exc
    except MustAskLocked as exc:
        raise HTTPException(status_code=409, detail="A Must-ask rule can't be switched off.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Only the Owner can change this.") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such setting.") from exc
    except Exception as exc:  # a broken store or config: closed, never the cause
        logger.warning("team write refused (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="not_configured") from exc


def _stored[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except Exception as exc:
        raise _StoreFailed from exc


def _audit(principal: deps.Principal, what: str, key: str, at: str) -> None:
    """BQ-TEAMACC-1: no registered event fits, so a plain ids-only line until `team_rule.changed` exists."""
    logger.info("team_rule_changed what=%s key=%s by=%s at=%s", what, key, principal.user_id, at)


def _read(store: TeamRepository) -> TeamState:
    try:
        return store.read()
    except Exception as exc:
        logger.warning("team read refused (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="not_configured") from exc


@router.get("/v1/team")
def get_team(principal: Principal, store: Store) -> dict[str, Any]:
    _session(principal)  # it carries invite emails
    state = _read(store)
    _member(state, principal)
    return _view(state, principal)


@router.put("/v1/team/members/{person_id}/role")
def put_role(
    person_id: str, principal: Principal, body: Annotated[RoleIn, Depends(_json_body(RoleIn))],
    store: Store, flags: Flags, clock: Clock,
) -> dict[str, Any]:  # fmt: skip
    _session(principal)
    if body.role not in ROLES:  # a legacy contract role ("Team Lead") too, until BQ-DSN-01 maps it
        _member(_read(store), principal)
        raise HTTPException(status_code=422, detail="Pick Owner, Approver, Member or Viewer.")

    def change(state: TeamState) -> TeamState:
        _owner(state, principal)
        return apply_role_change(state, actor=principal.user_id, target=person_id, role=body.role)

    state = _write(store, principal, flags, change)
    _audit(principal, "role", person_id, clock())
    return _view(state, principal)


@router.put("/v1/team/members/{person_id}/limit")
def put_limit(
    person_id: str, principal: Principal, body: Annotated[LimitIn, Depends(_json_body(LimitIn))],
    store: Store, flags: Flags, clock: Clock,
) -> dict[str, Any]:  # fmt: skip
    def change(state: TeamState) -> TeamState:
        _owner(state, principal)
        if person_id not in state.roles:
            raise KeyError(person_id)
        limits = {p: v for p, v in state.limits.items() if p != person_id}
        if body.limit_minor is not None:
            limits[person_id] = body.limit_minor
        return replace(state, limits=limits)

    state = _write(store, principal, flags, change)
    _audit(principal, "limit", person_id, clock())
    return _view(state, principal)


@router.delete("/v1/team/members/{person_id}")
def remove_member(person_id: str, principal: Principal, store: Store, flags: Flags, clock: Clock) -> dict[str, Any]:
    def change(state: TeamState) -> TeamState:
        _owner(state, principal)
        if person_id not in state.roles:
            raise KeyError(person_id)
        if person_id == principal.user_id:  # also covers the last Owner: only an Owner gets here
            raise RoleChangeRefused("last_owner")
        roles = {p: r for p, r in state.roles.items() if p != person_id}
        worlds = {w: principal.user_id if p == person_id else p for w, p in state.worlds.items()}
        limits = {p: v for p, v in state.limits.items() if p != person_id}
        return replace(state, roles=roles, worlds=worlds, limits=limits)

    state = _write(store, principal, flags, change)
    _audit(principal, "remove", person_id, clock())
    return _view(state, principal)


@router.post("/v1/team/invites", status_code=201)
def invite(
    principal: Principal, body: Annotated[InviteIn, Depends(_json_body(InviteIn))], store: Store, flags: Flags,
    clock: Clock,
) -> dict[str, Any]:  # fmt: skip
    invite_id = "inv_" + secrets.token_hex(8)

    def change(state: TeamState) -> TeamState:
        _owner(state, principal)
        if body.role not in ROLES or body.role == "Owner":
            raise HTTPException(status_code=422, detail="Invite as Approver, Member or Viewer.")
        if any(i["email"].lower() == body.email.lower() for i in state.invites.values()):
            raise HTTPException(status_code=409, detail="That address is already invited.")
        if len(state.invites) >= MAX_INVITES:
            raise HTTPException(status_code=409, detail="Too many pending invites.")
        invites = {**state.invites, invite_id: {"email": body.email, "role": body.role}}
        return replace(state, invites=invites)

    _write(store, principal, flags, change)
    _audit(principal, "invite", invite_id, clock())
    return {"invite_id": invite_id}


@router.put("/v1/team/switches/{key}")
def put_switch(
    key: str, principal: Principal, body: Annotated[SwitchIn, Depends(_json_body(SwitchIn))],
    store: Store, flags: Flags, clock: Clock,
) -> dict[str, Any]:  # fmt: skip
    at = clock()

    def change(state: TeamState) -> TeamState:
        switches, _record = set_switch(
            effective_switches(state), key, body.on, actor=principal.user_id, actor_role=state.roles[principal.user_id],
            at=at,
        )  # fmt: skip
        return replace(state, switches=switches)

    state = _write(store, principal, flags, change)
    _audit(principal, "switch", key, at)
    return _view(state, principal)


@router.put("/v1/team/tools/{connector}")
def put_tool(
    connector: str, principal: Principal, body: Annotated[ToolIn, Depends(_json_body(ToolIn))],
    store: Store, flags: Flags, clock: Clock,
) -> dict[str, Any]:  # fmt: skip
    def change(state: TeamState) -> TeamState:
        if state.roles[principal.user_id] != "Owner" or "Owner" not in load_capabilities()["change_tool_access"].roles:
            raise PermissionError(connector)
        if connector not in deps.get_connector_registry():
            raise KeyError(connector)
        if body.level not in LEVELS:
            raise HTTPException(status_code=422, detail="Pick off, read, draft or act.")
        return replace(state, tools={**state.tools, connector: body.level})

    state = _write(store, principal, flags, change)
    _audit(principal, "tool", connector, clock())
    return _view(state, principal)
