"""SEC-15: deployed access, visitor or Google AI Builder Cup judge, enforced server-side (PRD supplement 4;
services/api/tests/API_SEC_15.md).

Everything here is deterministic code; a model never decides who gets in. The declaration is a record behind a
store seam (`deps.get_access_store`), set once, and read only for the verified `Principal`, never from a header,
query, cookie or body field. `AccessGate` is the first thing a deployed request meets: it refuses every route that
is not in `PUBLIC_ROUTES` before any body is read or any world looked up. Not deployed (no `K_SERVICE` or
`CLOUD_RUN_JOB`) nothing is enforced, so CI and `just dev-api` behave as before.

`provider_mode` is the one decision about live models for a request: pure, no I/O, never sets `LIVE`.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from typing import Literal, Protocol

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("tilo_api.access")

Declaration = Literal["visitor", "judge"]
Mode = Literal["live", "replay"]

# The only routes a person without access may call. A new public route is an owner decision (the test pins this).
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("GET", "/health"), ("GET", "/healthz"), ("GET", "/access"), ("POST", "/access/declaration")}
)

UNDER_CONSTRUCTION = "Tilo is still under construction and not open to the public."
DECLARATION_REQUIRED = "Tell Tilo whether you are a visitor or a Google AI Builder Cup judge."


class AccessStore(Protocol):
    def get(self, user_id: str) -> Declaration | None: ...

    def declare(self, user_id: str, declaration: Declaration) -> Declaration:
        """Atomic, first write wins; returns what is stored (so a second, different call gets the first value)."""
        ...


class InMemoryAccessStore:
    """The process's own store until Firestore is wired (a replacement for this class, not for the gate)."""

    def __init__(self) -> None:
        self._data: dict[str, Declaration] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str) -> Declaration | None:
        with self._lock:
            return self._data.get(user_id)

    def declare(self, user_id: str, declaration: Declaration) -> Declaration:
        with self._lock:
            return self._data.setdefault(user_id, declaration)


def enforced(env: Mapping[str, str] | None = None) -> bool:
    """True when deployed: presence, not truthiness (Cloud Run can set a variable to an empty string), the same
    rule as `tilo_api.dev.refuse_if_unsafe`. Read on every request."""
    env = os.environ if env is None else env
    return "K_SERVICE" in env or "CLOUD_RUN_JOB" in env


def provider_mode(declaration: str | None, env: Mapping[str, str], *, replay_only: bool = False) -> Mode:
    """ "live" or "replay" for one request. `replay_only` (NFR-24, the cost kill switch) always wins; then the
    user's own global switch (exactly "1"); then a judge on a deployment whose owner set `TILO_JUDGE_LIVE=1`.
    Anything else, including every judge in dev or CI, is replay. Reads only `env`, sets nothing."""
    if replay_only:
        return "replay"
    if env.get("LIVE") == "1":
        return "live"
    if enforced(env) and declaration == "judge" and env.get("TILO_JUDGE_LIVE") == "1":
        return "live"
    return "replay"


def _refusal(
    status: int, detail: str, code: str | None = None, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    body = {"detail": detail} if code is None else {"detail": detail, "code": code}
    return JSONResponse(body, status_code=status, headers=dict(headers or {}))


def _decide(scope: Scope) -> JSONResponse | None:
    """None to let the request through (the declaration is left on `scope["state"]` for `deps.get_mode`), or the
    refusal. 401 first (the store is not read for nobody), then fail closed on an unwired or failing store."""
    from tilo_api import deps  # noqa: PLC0415  (deps imports this module)

    overrides = scope["app"].dependency_overrides
    try:
        principal = overrides.get(deps.get_current_principal, deps.get_current_principal)()
        store = overrides.get(deps.get_access_store, deps.get_access_store)()
        declaration = store.get(principal.user_id)
    except HTTPException as exc:
        return _refusal(exc.status_code, str(exc.detail), headers=exc.headers)
    except Exception as exc:
        logger.warning("access store unavailable, so nothing is let through: %s", type(exc).__name__)
        return _refusal(503, "not_configured")
    if declaration is None:
        return _refusal(403, DECLARATION_REQUIRED, "declaration_required")
    if declaration != "judge":  # a visitor, or anything the store should never hold: no access
        return _refusal(403, UNDER_CONSTRUCTION, "under_construction")
    scope.setdefault("state", {})["declaration"] = declaration
    return None


class AccessGate:
    """Pure ASGI middleware: runs before routing, so before any body is parsed or world looked up."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not enforced() or (scope["method"], scope["path"]) in PUBLIC_ROUTES:
            await self.app(scope, receive, send)
            return
        refusal = await run_in_threadpool(_decide, scope)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)
