"""tilo-api: sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC (PRD 6.2)."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from tilo_api import deps as _deps
from tilo_api import dev as _dev
from tilo_api import people as _people
from tilo_api import runs as _runs
from tilo_api import schedules as _schedules
from tilo_api import skill_proposals as _skill_proposals
from tilo_api.access import AccessGate as _AccessGate
from tilo_api.access_routes import router as _access_router
from tilo_api.assistant.route import router as _assistant_router
from tilo_api.cards import build_router as _build_cards_router
from tilo_api.console import build_router as _build_console_router
from tilo_api.costs import router as _costs_router
from tilo_api.dispatch import router as _dispatch_router
from tilo_api.intake import router as intake_router
from tilo_api.rate_limit import RateLimitGate as _RateLimitGate
from tilo_api.redaction import router as _redaction_router
from tilo_api.sharing import WorldView
from tilo_api.sharing import build_router as _build_sharing_router
from tilo_api.tasks import router as _tasks_router

# Generated docs only in local dev mode: deployed, the service is public and the route list is not for
# strangers (issue #411). `app.openapi()` still works in-process for tests.
_DOCS: dict[str, Any] = {} if _dev.dev_enabled() else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="tilo-api", **_DOCS)
app.add_middleware(_AccessGate)  # SEC-15: deployed, every non-public route needs a stored judge declaration
app.add_middleware(_RateLimitGate, fastapi_app=app)  # SEC-10: per-user and per-IP token-bucket rate limits


@app.exception_handler(_deps.ReplayOnly)
def _replay_only(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": _deps.REPLAY_ONLY_MESSAGE, "replay_only": True})


def _world_views(store: Annotated[_deps.Store, Depends(_deps.get_store)]) -> Callable[[str], WorldView]:
    """FR-HIL-12: each world's own CardStore and its Pause all state, for the share routes."""

    def view(world_id: str) -> WorldView:
        world = store.worlds.get(world_id)
        return WorldView(
            _runs.get_card_store(world_id, store), paused=world is None or world.paused
        )  # no record: closed, like Run.paused

    return view


app.include_router(_access_router)
app.include_router(intake_router)
app.include_router(_dispatch_router)
app.include_router(_redaction_router)
app.include_router(_costs_router)
app.include_router(_tasks_router)
app.include_router(_build_cards_router(_runs.get_card_store, answer_guard=_runs.answer_guard))
app.include_router(_build_console_router(_runs.get_card_store, answer_guard=_runs.answer_guard))
app.include_router(_build_sharing_router(_world_views))
app.include_router(_runs.router)
app.include_router(_assistant_router)
app.include_router(_people.router)
app.include_router(_schedules.router)


def _world_owner(world_id: str) -> str | None:
    """The world's owner from the store the app is wired with (503 `not_configured` when none is)."""
    world = app.dependency_overrides.get(_deps.get_store, _deps.get_store)().worlds.get(world_id)
    return world.owner if world else None


app.include_router(_skill_proposals.build_router(_skill_proposals.get_skill_proposals, owner_of=_world_owner))
_dev.install_if_enabled(app)  # only with TILO_API_DEV=1; refuses when deployed or live (CL-INT-4)


@app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
