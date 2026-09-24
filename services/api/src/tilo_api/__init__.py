"""tilo-api: sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC (PRD 6.2)."""

from fastapi import FastAPI

app = FastAPI(title="tilo-api")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
