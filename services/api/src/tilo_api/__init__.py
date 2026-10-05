"""tilo-api: sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC (PRD 6.2)."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tilo_api import deps as _deps
from tilo_api import dev as _dev
from tilo_api import runs as _runs
from tilo_api.cards import build_router as _build_cards_router
from tilo_api.console import build_router as _build_console_router
from tilo_api.dispatch import router as _dispatch_router
from tilo_api.intake import router as intake_router
from tilo_api.redaction import router as _redaction_router
from tilo_api.tasks import router as _tasks_router

app = FastAPI(title="tilo-api")


@app.exception_handler(_deps.ReplayOnly)
def _replay_only(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": _deps.REPLAY_ONLY_MESSAGE, "replay_only": True})


app.include_router(intake_router)
app.include_router(_dispatch_router)
app.include_router(_redaction_router)
app.include_router(_tasks_router)
app.include_router(_build_cards_router(_runs.get_card_store, answer_guard=_runs.answer_guard))
app.include_router(_build_console_router(_runs.get_card_store, answer_guard=_runs.answer_guard))
app.include_router(_runs.router)
_dev.install_if_enabled(app)  # only with TILO_API_DEV=1; refuses when deployed or live (CL-INT-4)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
