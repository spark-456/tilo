"""ASGI entry point for Cloud Run (P0-07a): liveness, and the internal meeting-host routes (ADR-0032 T3).

The image runs `uvicorn tilo_connectors.app:app`. Importing this builds nothing: the broker, the transport and the
certificate cache open on the first meeting-host call, and every route answers 503 `not_configured` until the service
is configured in full (`host_routes`). Other connector routes land with their own tickets.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .host_routes import HostRuntime, host_router


def create_app(runtime: HostRuntime | None = None) -> FastAPI:
    # No generated docs: the service may be public, and the route list is not for strangers (issue #411).
    app = FastAPI(title="tilo-connectors", docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    @app.exception_handler(StarletteHTTPException)
    async def not_found_or_not_allowed(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # a contract-shaped body (meeting_host_rpc error), never a framework page that names the stack
        return JSONResponse({"error": "invalid_request"}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(host_router(runtime or HostRuntime()))
    return app


app = create_app()
