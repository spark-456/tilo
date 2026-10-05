"""Minimal ASGI entry point for Cloud Run (P0-07a): liveness only, no business logic.

The image runs `uvicorn tilo_connectors.app:app`. Connector routes land with their own tickets.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="tilo-connectors")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
