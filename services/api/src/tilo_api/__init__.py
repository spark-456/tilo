"""tilo-api: sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC (PRD 6.2)."""

from fastapi import FastAPI

from tilo_api import deps  # noqa: F401  (re-exported: tests import `tilo_api.deps` directly)
from tilo_api.routes import router as _kill_switch_and_roles_router

app = FastAPI(title="tilo-api")
app.include_router(_kill_switch_and_roles_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
