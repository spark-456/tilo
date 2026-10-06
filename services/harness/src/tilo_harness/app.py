"""ASGI entry point for Cloud Run (P0-07a): liveness plus the scheduled-run tick (FR-AGT-14).

The image runs `uvicorn tilo_harness.app:app`. Run, event and resume routes land with their own tickets.

`POST /internal/schedules/tick` is called once a minute by Cloud Scheduler as `tilo-schedule-scheduler`. `run.invoker`
on harness is also held by tilo-api, tilo-tasks-invoker and tilo-gmail-scheduler (infra/ACCESS.md), so the route
checks the caller itself, from the verified token only. It reads no body and no query: nothing a caller sends selects
a schedule or sets the time. Nothing wired (the production state until the Firestore store and Cloud Tasks starter
land): 503, whatever token arrives. Bodies never carry a token, an address or an exception text.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tilo_harness.schedule import TickWiring

log = logging.getLogger(__name__)


def _refuse(status: int, message: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse({"error": message}, status_code=status, headers=headers)


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token and not any(c.isspace() for c in token) else None


def create_app(*, schedule_tick: TickWiring | None = None) -> FastAPI:
    # No generated docs: the service may be public, and the route list is not for strangers (issue #411).
    app = FastAPI(title="tilo-harness", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/schedules/tick")
    def tick(request: Request) -> JSONResponse:
        wiring = schedule_tick
        if wiring is None:  # fail closed: nothing to verify against
            return _refuse(503, "unavailable")
        token = _bearer(request)
        if token is None:
            return _refuse(401, "unauthorized")
        try:
            claims = wiring.verifier.verify(token, wiring.audience)
            audience, email, verified = claims.get("aud"), claims.get("email"), claims.get("email_verified")
        except Exception:  # bad signature, expiry, audience or a verifier outage: not an accepted caller
            return _refuse(401, "unauthorized")
        if audience != wiring.audience or email != wiring.service_account or verified is not True:
            return _refuse(403, "forbidden")
        try:
            fired = wiring.ticker.tick().fired
        except Exception as exc:  # fail closed: Scheduler retries; the next tick re-reads the store
            log.error("schedule tick failed (%s)", type(exc).__name__)
            return _refuse(500, "tick failed")
        return JSONResponse({"fired": fired})

    return app


app = create_app()
