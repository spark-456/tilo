"""Minimal ASGI entry point for Cloud Run (P0-07a): liveness only, no business logic.

The image runs `uvicorn tilo_harness.app:app`. Run, event and resume routes land with their own tickets.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="tilo-harness")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
