"""tilo_api.sharing -- Approver share links (FR-HIL-12; PRD 10.1, 10.3, 16.2, SEC-06; BQ-32, ADR-0006).

The owner shares one open gate with one named Approver: the gate is re-raised as a NEW proposal (`CardStore.share_gate`:
a new card, one `approval.requested` naming the owner's assignment) and the owner gets a bearer link. The link alone
answers nothing: the Approver must be signed in as the named user, in the link's world, before it expires or is
revoked. The answer goes through the cards store (first answer wins) as `approval.resolved`, channel from the session,
`authz` the Approver; `tilo_policy.open_gate` decides whether it opens the gate, and this module never writes an
outbox entry. The token is a secret: only its SHA-256 is kept, it is compared in constant time, it enters no event, no
stored card and no log (the access log masks it), and sign-in is checked before any token lookup. A non-named user, the
wrong world and an unknown token all get one 404 body. The link record is API-internal (BQ-HIL12-1).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import inspect
import logging
import math
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from tilo_api import deps
from tilo_api.cards import (
    _STATUS,
    _USER_RE,
    _WEB_CHANNELS,
    CardStore,
    ShareRefused,
    _derived_id,
    _parse_ts,
    session_allows,
)
from tilo_api.deps import Principal, get_current_principal

logger = logging.getLogger("tilo_api.sharing")
SHARING_CONFIG = Path(__file__).resolve().parents[4] / "config" / "sharing.yaml"
_DEFAULT_TTL_H, _MAX_TTL_H = 24.0, 168.0
_NOT_FOUND = {"outcome": "rejected", "reason": "not_found"}  # one body for a stranger, a wrong world, an unknown token
_GONE = {"outcome": "rejected", "reason": "link_gone"}  # expired or revoked: said only to the named Approver
_TOKEN_IN_PATH = re.compile(r"^(/share/)[^/?\s]+")


def link_ttl() -> datetime.timedelta:
    """The lifetime of a link from config/sharing.yaml, read on each call; unreadable or out of range, the default."""
    try:
        hours = float(yaml.safe_load(SHARING_CONFIG.read_text(encoding="utf-8"))["sharing"]["link_ttl_hours"])
    except Exception:
        hours = _DEFAULT_TTL_H
    return datetime.timedelta(hours=hours if math.isfinite(hours) and 0 < hours <= _MAX_TTL_H else _DEFAULT_TTL_H)


class _MaskToken(logging.Filter):
    """uvicorn's access log records the request path, and the token is in it: log `/share/<redacted>` instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and isinstance(args[2], str):
            record.args = (*args[:2], _TOKEN_IN_PATH.sub(r"\1<redacted>", args[2]), *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_MaskToken())


@dataclass
class _Link:
    share_id: str
    token_hash: str
    world_id: str
    card_id: str
    approver: str
    assigned_at: datetime.datetime
    expires_at: datetime.datetime
    revoked: bool = False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class WorldView:
    """What the share routes need of one world: its cards, and whether Pause all has stopped it (BQ-90)."""

    cards: CardStore
    paused: bool = False


class _ShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no assigned_by, by, authz or outbox_id: the owner is the session

    approver: str = Field(pattern=_USER_RE.pattern)


class _AnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no identity, channel, pin_verified or authz: all from the session

    option: str


def _in_directory(request: Request, user_id: str) -> bool:
    """Whether `user_id` is a person of this org in the people directory (PEOPLE-SEAMS-1, BQ-PEOPLESEAMS1-6). Deny by
    default: a directory that is not wired, cannot be read or raises answers False, whatever the reason."""
    try:
        seam = request.app.dependency_overrides.get(deps.get_people_stores, deps.get_people_stores)
        stores = seam(request) if inspect.signature(seam).parameters else seam()
        return stores.persons.get(deps.ORG_ID, user_id) is not None  # type: ignore[no-any-return]
    except Exception:
        return False


def build_router(worlds: CardStore | Callable[..., Callable[[str], WorldView]]) -> APIRouter:
    """`worlds` is one CardStore (every world), or a dependency returning a `world_id -> WorldView` resolver."""
    router = APIRouter()
    get_worlds = (lambda: lambda _w: WorldView(worlds)) if isinstance(worlds, CardStore) else worlds
    by_hash: dict[str, _Link] = {}
    by_id: dict[str, _Link] = {}
    lock = threading.Lock()

    def owner_view(world_id: str, principal: Principal, resolve: Callable[[str], WorldView]) -> WorldView:
        if principal.world_id != world_id or principal.role != "owner" or principal.channel not in _WEB_CHANNELS:
            raise HTTPException(status_code=404)  # same as an unknown world
        view = resolve(world_id)
        if principal.user_id != view.cards.owner_of(world_id):
            raise HTTPException(status_code=404)
        return view

    def named_link(token: str, principal: Principal) -> _Link | None:
        """The link `token` opens for this signed-in person, or None for anyone else (stranger or unknown token)."""
        digest = _digest(token)
        with lock:
            link = by_hash.get(digest)
        if link is None or not hmac.compare_digest(link.token_hash, digest):
            return None
        named = (principal.role, principal.user_id, principal.world_id) == ("approver", link.approver, link.world_id)
        return link if named else None

    def usable(link: _Link, view: WorldView) -> bool:
        return not link.revoked and _parse_ts(view.cards.now()) < link.expires_at

    @router.post("/worlds/{world_id}/cards/{card_id}/share", status_code=201)
    def create_share(
        world_id: str,
        card_id: str,
        body: _ShareBody,
        request: Request,
        principal: Principal = Depends(get_current_principal),
        resolve: Callable[[str], WorldView] = Depends(get_worlds),
    ) -> JSONResponse:
        view = owner_view(world_id, principal, resolve)
        if body.approver == principal.user_id:
            return JSONResponse(status_code=422, content={"outcome": "rejected", "reason": "owner_needs_no_link"})
        if not _in_directory(request, body.approver):  # one body for unknown, other-org and unreadable alike
            return JSONResponse(status_code=403, content={"outcome": "rejected", "reason": "not_allowed"})
        expires = _parse_ts(view.cards.now()) + link_ttl()
        stamp = expires.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        try:
            new_id, assigned_at, ended = view.cards.share_gate(world_id, card_id, approver=body.approver, until=stamp)
        except ShareRefused as exc:
            reason = str(exc)
            return JSONResponse(
                status_code=404 if reason == "card_not_found" else 409,
                content={"outcome": "rejected", "reason": reason},
            )
        except Exception as exc:  # the proposal could not be written: nothing was shared
            logger.warning("a share could not be written: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"outcome": "error", "reason": "event_write_failed"})
        token = secrets.token_urlsafe(32)
        link = _Link(
            _derived_id(secrets.token_hex(16)),
            _digest(token),
            world_id,
            new_id,
            body.approver,
            _parse_ts(assigned_at),
            expires,
        )
        with lock:
            by_hash[link.token_hash], by_id[link.share_id] = link, link
            for earlier in by_id.values():  # one live share per gate: the store ended the earlier ones' assignment
                earlier.revoked |= earlier.card_id in ended
        return JSONResponse(
            status_code=201, content={"share_id": link.share_id, "token": token, "card_id": new_id, "expires_at": stamp}
        )

    @router.delete("/worlds/{world_id}/shares/{share_id}", status_code=204)
    def revoke_share(
        world_id: str,
        share_id: str,
        principal: Principal = Depends(get_current_principal),
        resolve: Callable[[str], WorldView] = Depends(get_worlds),
    ) -> Response:
        view = owner_view(world_id, principal, resolve)
        with lock:
            link = by_id.get(share_id)
            if link is None or link.world_id != world_id:
                raise HTTPException(status_code=404)
            link.revoked = True
        view.cards.unassign(world_id, link.card_id)  # the assignment ends with the link; the owner keeps the gate
        return Response(status_code=204)

    @router.get("/share/{token}")
    def open_share(
        token: str,
        principal: Principal = Depends(get_current_principal),  # sign-in first: no token lookup before it
        resolve: Callable[[str], WorldView] = Depends(get_worlds),
    ) -> JSONResponse:
        if not session_allows(principal, principal.channel, False):  # a gate opens only in a signed-in web session
            return JSONResponse(status_code=400, content={"outcome": "rejected", "reason": "invalid_channel"})
        link = named_link(token, principal)
        if link is None:
            return JSONResponse(status_code=404, content=_NOT_FOUND)
        view = resolve(link.world_id)
        if not usable(link, view) or not view.cards.is_open(link.world_id, link.card_id):
            return JSONResponse(status_code=410, content=_GONE)  # expired, revoked, or answered elsewhere
        card = view.cards.get(link.world_id, link.card_id)
        return (
            JSONResponse(status_code=200, content={"card": card})
            if card
            else JSONResponse(status_code=404, content=_NOT_FOUND)
        )

    @router.post("/share/{token}/answer")
    def answer_share(
        token: str,
        body: _AnswerBody,
        principal: Principal = Depends(get_current_principal),
        resolve: Callable[[str], WorldView] = Depends(get_worlds),
    ) -> JSONResponse:
        if not session_allows(principal, principal.channel, False):  # a gate opens only in a signed-in web session
            return JSONResponse(status_code=400, content={"outcome": "rejected", "reason": "invalid_channel"})
        link = named_link(token, principal)
        if link is None:
            return JSONResponse(status_code=404, content=_NOT_FOUND)
        view = resolve(link.world_id)
        if not usable(link, view):
            return JSONResponse(status_code=410, content=_GONE)
        if view.paused:
            return JSONResponse(status_code=409, content={"outcome": "rejected", "reason": "world_paused"})
        if _parse_ts(view.cards.now()) < link.assigned_at:  # BQ-32: the assignment must be no later than the answer
            return JSONResponse(status_code=403, content={"outcome": "rejected", "reason": "assignment_not_in_force"})
        try:
            result = view.cards.answer(
                link.world_id, link.card_id, option=body.option, channel=principal.channel, principal=principal
            )
        except Exception as exc:  # the event write failed; the card stays open and the answer can be sent again
            logger.warning("a share answer could not be written: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"outcome": "error", "reason": "event_write_failed"})
        if result.outcome == "answered":
            return JSONResponse(status_code=200, content={"outcome": "answered"})
        content: dict[str, Any] = {"outcome": "rejected", "reason": result.reason}
        return JSONResponse(status_code=_STATUS.get(result.reason or "", 400), content=content)

    return router
