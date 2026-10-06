"""Minimal ASGI entry point for Cloud Run (P0-07a): liveness only, no business logic.

The image runs `uvicorn tilo_browser.app:app`. Worker routes land with their own tickets.
"""

from __future__ import annotations

from fastapi import FastAPI

# No generated docs: the service may be public, and the route list is not for strangers (issue #411).
app = FastAPI(title="tilo-browser", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
