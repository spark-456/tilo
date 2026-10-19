"""OPEN-ACCESS (16 Oct 2026, the owner's order): everyone who signs in may use Tilo. SEC-15's two public routes
stay only so a web bundle that still calls them keeps working. `GET /access` says what the signed-in person's
next request gets (`allowed` is always true; `models` is "live" or "replay", NFR-22: an honest label). `POST
/access/declaration` accepts the old sign-up body and stores nothing: it answers exactly as `GET /access` and
never refuses an answer (no 409 `declaration_locked`). Neither takes a password; only `application/json` is read
(415: a cross-site form post needs no CORS preflight)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from tilo_metering.flags import FlagStore

from tilo_api import deps
from tilo_api.access import OPEN_DECLARATION, Declaration, Mode

router = APIRouter()

Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Flags = Annotated[FlagStore, Depends(deps.get_switches)]


class DeclarationIn(BaseModel):
    """The retired sign-up answer. Accepted and ignored."""

    model_config = ConfigDict(extra="forbid")
    declaration: Declaration


class AccessOut(BaseModel):
    declaration: Declaration
    allowed: bool
    models: Mode  # "live" or "replay" (NFR-22: an honest label)


def _json_only(request: Request) -> None:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")


def _view(request: Request, principal: deps.Principal, flags: FlagStore) -> AccessOut:
    """`models`: what the person's next request gets (SEC-16)."""
    # these routes are public, so the gate has not flagged the session: the principal says if it is a demo session
    models = deps.spend_mode(request, principal.user_id, OPEN_DECLARATION, flags, demo=principal.demo_session)[0]
    return AccessOut(declaration=OPEN_DECLARATION, allowed=True, models=models)


@router.get("/access")
def get_access(request: Request, principal: Principal, flags: Flags) -> AccessOut:
    return _view(request, principal, flags)


@router.post("/access/declaration", dependencies=[Depends(_json_only)])
def declare(request: Request, body: DeclarationIn, principal: Principal, flags: Flags) -> AccessOut:
    return _view(request, principal, flags)
