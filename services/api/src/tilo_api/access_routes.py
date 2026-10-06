"""SEC-15's two public routes (services/api/tests/API_SEC_15.md): `GET /access` says what the signed-in person is and
may do; `POST /access/declaration` is the sign-up step, set once. Neither takes a password. The declaration is for
`principal.user_id` only; the body names nothing else (`extra="forbid"`), and only `application/json` is read (415:
a cross-site form post needs no CORS preflight)."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from tilo_metering.flags import FlagStore

from tilo_api import deps
from tilo_api.access import AccessStore, Declaration, Mode, provider_mode

router = APIRouter()

Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Store = Annotated[AccessStore, Depends(deps.get_access_store)]
Flags = Annotated[FlagStore, Depends(deps.get_flag_store)]


class DeclarationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    declaration: Declaration


class AccessOut(BaseModel):
    declaration: Declaration | None
    allowed: bool
    models: Mode | None  # "live" or "replay" for an allowed person (NFR-22: an honest label), else null


def _json_only(request: Request) -> None:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")


def _view(declaration: Declaration | None, flags: FlagStore) -> AccessOut:
    allowed = declaration == "judge"
    models = provider_mode(declaration, os.environ, replay_only=bool(flags.get("replay_only"))) if allowed else None
    return AccessOut(declaration=declaration, allowed=allowed, models=models)


@router.get("/access")
def get_access(principal: Principal, store: Store, flags: Flags) -> AccessOut:
    return _view(store.get(principal.user_id), flags)


@router.post("/access/declaration", dependencies=[Depends(_json_only)], response_model=None)
def declare(body: DeclarationIn, principal: Principal, store: Store, flags: Flags) -> AccessOut | JSONResponse:
    stored = store.declare(principal.user_id, body.declaration)  # atomic, first write wins
    if stored != body.declaration:
        return JSONResponse(
            status_code=409,
            content={"detail": "Your answer was already recorded and cannot be changed.", "code": "declaration_locked"},
        )
    return _view(stored, flags)
