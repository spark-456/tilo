"""tilo-api: sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC (PRD 6.2)."""

from fastapi import FastAPI

from tilo_api.intake import router as intake_router

app = FastAPI(title="tilo-api")
app.include_router(intake_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
