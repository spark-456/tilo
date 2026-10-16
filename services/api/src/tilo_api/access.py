"""SEC-15 / OPEN-ACCESS: who may call the deployed API. The owner's order (16 Oct 2026): "Everyone must be able to
access through their mail, lets remove the entire judge and non judge blockers". Every person with a verified
sign-in (Google, or an anonymous demo session) is let in; there is no visitor/judge declaration to make and
nobody is refused for lacking one.

What stays, all deterministic code (a model never decides who gets in): the sign-in itself (401 for nobody), the
per-uid rate limit (SEC-16, 429), the demo session's replay-only models, and, in `deps.spend_mode`, the per-uid
lifetime spend cap, the per-run cap, the daily deployment cap and the NFR-24 kill switch. A signed-in person is
given the allowance the former "judge" had: `OPEN_DECLARATION`, so `provider_mode` returns live only on a
deployment whose owner set `TILO_JUDGE_LIVE=1` (or the owner's own `LIVE=1`), and the caps above bound what each
person can spend.

`AccessGate` runs before any store or world work (only middleware with no I/O, such as the log context and the
no-store headers, wraps it): it resolves the verified `Principal` before any body is read or any world looked up.
Not deployed (no `K_SERVICE` or `CLOUD_RUN_JOB`) nothing is enforced, so CI and `just dev-api` behave as before.

`provider_mode` is the one decision about live models for a request: pure, no I/O, never sets `LIVE`.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from typing import Literal

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("tilo_api.access")

Declaration = Literal["visitor", "judge"]
Mode = Literal["live", "replay"]
# OPEN-ACCESS: what every signed-in person is treated as. Nobody is asked to declare; the former judge's policy (live
# models where the deployment permits it, per-uid rate limit and spend caps) is the one policy for everyone.
OPEN_DECLARATION: Declaration = "judge"

# The only routes a person without access may call. A new public route is an owner decision (the test pins this).
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/healthz"),
        ("GET", "/healthz/deps"),
        ("GET", "/health/deps"),
        ("GET", "/access"),
        ("POST", "/access/declaration"),
        (
            "POST",
            "/internal/schedules/tick",
        ),  # FR-AGT-14b: Cloud Scheduler has no session; the route checks its OIDC caller
        # ADR-0042 (BQ-M2-5, pending the user; inert until `TILO_VOICE_METER=1`): the meeting bot has no session; each
        # route checks its own Google ID token and the attend's nonce.
        ("POST", "/internal/meeting-voice/reserve"),
        ("POST", "/internal/meeting-voice/close"),
    }
)

# FR-PA-06b: the plate digest's emailed Done and Snooze links open in a browser with no session. Only `GET` and `POST`
# of `/l/<token>` (one path segment of token characters, no query); the route itself verifies the signed single-use
# token, and a GET consumes nothing. A new public path is an owner decision (the test pins this).
_LINK_PATH = re.compile(r"/l/[A-Za-z0-9_.-]{1,512}")


def public_link(method: str, path: str) -> bool:
    return method in ("GET", "POST") and _LINK_PATH.fullmatch(path) is not None


RATE_LIMITED = "Too many requests in a short time. Wait a moment, then try again."


def enforced(env: Mapping[str, str] | None = None) -> bool:
    """True when deployed: presence, not truthiness (Cloud Run can set a variable to an empty string), the same
    rule as `tilo_api.dev.refuse_if_unsafe`. Read on every request."""
    env = os.environ if env is None else env
    return "K_SERVICE" in env or "CLOUD_RUN_JOB" in env


def provider_mode(
    declaration: str | None, env: Mapping[str, str], *, replay_only: bool = False, capped: bool = False
) -> Mode:
    """ "live" or "replay" for one request. `replay_only` (NFR-24, the cost kill switch) and `capped` (SEC-16, the
    uid's spend cap) always win; then the user's own global switch (exactly "1"); then a judge on a deployment whose
    owner set `TILO_JUDGE_LIVE=1`. Anything else, including every judge in dev or CI, is replay. Reads only `env`,
    sets nothing."""
    if replay_only or capped:
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
    """None to let the request through (the open declaration and uid are left on `scope["state"]` for
    `deps.get_mode`), or the refusal. 401 for nobody signed in, then the per-uid rate limit (429, SEC-16). No store is
    read: nobody is refused for a missing or "visitor" declaration (OPEN-ACCESS)."""
    from tilo_api import deps  # noqa: PLC0415  (deps imports this module)

    overrides = scope["app"].dependency_overrides
    try:
        # SEC-15 sign-in reads the request's Authorization header; a test double that takes no argument still works
        principal = deps.resolve_principal(scope["app"], HTTPConnection(scope))
    except HTTPException as exc:
        return _refusal(exc.status_code, str(exc.detail), headers=exc.headers)
    except Exception as exc:
        logger.warning("sign-in unavailable, so nothing is let through: %s", type(exc).__name__)
        return _refusal(503, "not_configured")
    try:  # SEC-16: every gated request counts, keyed by the verified uid only
        decision = overrides.get(deps.get_rate_limiter, deps.get_rate_limiter)().check(principal.user_id)
    except Exception as exc:
        logger.warning("rate limiter unavailable, so nothing is let through: %s", type(exc).__name__)
        return _refusal(503, "not_configured")
    if not decision.allowed:
        return _refusal(429, RATE_LIMITED, "rate_limited", {"Retry-After": str(decision.retry_after_s)})
    state = scope.setdefault("state", {})
    state["declaration"], state["uid"] = OPEN_DECLARATION, principal.user_id
    state["principal"] = principal  # resolved once per request: the route's own dependency reuses it (BQ-SIGNIN-9)
    state["demo_session"] = principal.demo_session  # an anonymous demo session: replay models only (BQ-SIGNIN-10)
    return None


class AccessGate:
    """Pure ASGI middleware: runs before routing, so before any body is parsed or world looked up. Only `lifespan`
    passes untouched; a `websocket` scope goes through the same decision and is closed (1008) before it is accepted,
    so a websocket route, today's or a later one, is never open to a visitor. A scope type this gate does not know
    is dropped, never passed on."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "lifespan" or not enforced():
            await self.app(scope, receive, send)
            return
        if kind == "http" and (
            (scope["method"], scope["path"]) in PUBLIC_ROUTES or public_link(scope["method"], scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        if kind not in {"http", "websocket"}:
            return  # fail closed on anything else
        refusal = await run_in_threadpool(_decide, scope)
        if refusal is None:
            await self.app(scope, receive, send)
        elif kind == "http":
            await refusal(scope, receive, send)
        else:
            await receive()  # the connect message; the connection is refused before it is accepted
            await send({"type": "websocket.close", "code": 1008})
