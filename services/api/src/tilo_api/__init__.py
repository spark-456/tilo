"""tilo-api: sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC (PRD 6.2)."""

from fastapi import FastAPI

from tilo_api.dispatch import router as _dispatch_router
from tilo_api.redaction import router as _redaction_router

app = FastAPI(title="tilo-api")
app.include_router(_dispatch_router)
app.include_router(_redaction_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
