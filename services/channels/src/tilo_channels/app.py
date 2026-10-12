"""Minimal ASGI entry point for Cloud Run (P0-07a): liveness only, no business logic.

The image runs `uvicorn tilo_channels.app:app`. Webhook routes land with their own tickets.
"""

from __future__ import annotations

from fastapi import FastAPI

from tilo_channels.push_routes import router as _push_router

# No generated docs: the service may be public, and the route list is not for strangers (issue #411).
app = FastAPI(title="tilo-channels", docs_url=None, redoc_url=None, openapi_url=None)


app.include_router(_push_router)  # FR-CHN-17f: OIDC-checked, tilo-api only


@app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
