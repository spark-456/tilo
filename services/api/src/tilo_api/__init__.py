"""tilo-api: sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC (PRD 6.2)."""

import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from tilo_harness.writer import WriterBusy as _WriterBusy
from tilo_logging import configure_logging as _configure_logging

from tilo_api import appcheck as _appcheck
from tilo_api import byok_routes as _byok_routes
from tilo_api import connect_routes as _connect_routes
from tilo_api import cors as _cors
from tilo_api import deps as _deps
from tilo_api import dev as _dev
from tilo_api import durable_store as _durable_store
from tilo_api import meeting_host_routes as _meeting_host_routes
from tilo_api import meeting_minutes_flag as _meeting_minutes_flag
from tilo_api import meeting_voice_meter as _meeting_voice_meter
from tilo_api import nudge_sweep as _nudge_sweep
from tilo_api import owner_minutes_routes as _owner_minutes_routes
from tilo_api import people as _people
from tilo_api import plate_links as _plate_links
from tilo_api import quiz_apps as _quiz_apps
from tilo_api import results as _results
from tilo_api import runs as _runs
from tilo_api import schedules as _schedules
from tilo_api import skill_proposals as _skill_proposals
from tilo_api import spend as _spend
from tilo_api.access import AccessGate as _AccessGate
from tilo_api.access_routes import router as _access_router
from tilo_api.appcheck import AppCheckGate as _AppCheckGate
from tilo_api.assistant.route import router as _assistant_router
from tilo_api.brief_routes import router as _brief_router
from tilo_api.cards import build_router as _build_cards_router
from tilo_api.cards_feed import router as _cards_feed_router
from tilo_api.connectors_list import router as _connectors_list_router
from tilo_api.console import build_router as _build_console_router
from tilo_api.context_panel import router as _context_panel_router
from tilo_api.costs import router as _costs_router
from tilo_api.dispatch import router as _dispatch_router
from tilo_api.effort import router as _effort_router
from tilo_api.feedback import router as _feedback_router
from tilo_api.health_deps import router as _health_deps_router
from tilo_api.intake import router as intake_router
from tilo_api.item_fields import router as _item_fields_router
from tilo_api.log_context import LogContext as _LogContext
from tilo_api.log_context import LogRunId as _LogRunId
from tilo_api.meeting_room import router as _meeting_room_router
from tilo_api.notifications import router as _notifications_router
from tilo_api.people_limits import NoStore as _NoStore
from tilo_api.people_list import router as _people_list_router
from tilo_api.people_teams import router as _people_teams_router
from tilo_api.push_routes import router as _push_router
from tilo_api.rate_limit import RateLimitGate as _RateLimitGate
from tilo_api.redaction import router as _redaction_router
from tilo_api.sample_world import router as _sample_router
from tilo_api.sharing import WorldView
from tilo_api.sharing import build_router as _build_sharing_router
from tilo_api.skills_capture import router as _skills_capture_router
from tilo_api.skills_feedback import router as _skills_feedback_router
from tilo_api.skills_media import router as _skills_media_router
from tilo_api.skills_routes import router as _skills_router
from tilo_api.tasks import router as _tasks_router
from tilo_api.team_items import router as _team_items_router
from tilo_api.team_routes import router as _team_router
from tilo_api.team_shares import router as _team_shares_router
from tilo_api.user_settings import router as _user_settings_router
from tilo_api.worlds_list import router as _worlds_list_router

# Generated docs only in local dev mode: deployed, the service is public and the route list is not for
# strangers (issue #411). `app.openapi()` still works in-process for tests.
_DOCS: dict[str, Any] = {} if _dev.dev_enabled() else {"docs_url": None, "redoc_url": None, "openapi_url": None}


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    # min-instances 0: every idle period ends in a cold start, and the first sign-in must not meet an empty key cache.
    # A daemon thread, best effort: the start never waits on the keys endpoint and never fails for it.
    threading.Thread(target=_appcheck.warm_up, name="jwks-warm-up", daemon=True).start()
    await run_in_threadpool(_durable_store.recover_deployed)  # X-ORPHAN-1: fail orphan runs before accepting requests
    yield
    await run_in_threadpool(_durable_store.close_deployed)  # SIGTERM: the writers release their leases (ADR-0026 4)


# The two Firebase Hosting origins of the tilo-dev web app (BQ-SIGNIN-7, CL-REACH): exact strings, never a wildcard,
# a suffix match or `allow_origin_regex`. Not credentialed: the API reads a bearer token, no cookie.
PRODUCTION_ORIGINS = _cors.PRODUCTION_ORIGINS


app = FastAPI(title="tilo-api", lifespan=_lifespan, **_DOCS)
app.add_middleware(_LogRunId)  # NFR-26: innermost, so the world is looked up only for a request the gate admitted
app.add_middleware(_AccessGate)  # SEC-15: deployed, every non-public route needs a verified signed-in person
app.add_middleware(_AppCheckGate)  # SEC-10: App Check token, logged only until the owner sets TILO_APPCHECK_ENFORCE=1
app.add_middleware(_NoStore)  # added after the gate, so it is outside it: the gate's 403 on `/v1/` is no-store too
app.add_middleware(_RateLimitGate, fastapi_app=app)  # SEC-10: before AccessGate
app.add_middleware(_LogContext)  # NFR-26: outermost, no I/O: binds the world id and trace id of the request
_cors.install_cors(app)  # WEB-TO-API: only with TILO_API_CORS_ORIGINS; outermost, so a preflight needs no token
_configure_logging()  # NFR-26: a deployed service logs JSON with no further setup


@app.exception_handler(_WriterBusy)
def _writer_busy(_: Request, __: Exception) -> JSONResponse:  # the one retry is spent: another holds the world
    return JSONResponse(status_code=503, content={"detail": "store_unavailable"})


@app.exception_handler(_deps.ReplayOnly)
def _replay_only(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": _deps.REPLAY_ONLY_MESSAGE, "replay_only": True})


@app.exception_handler(_deps.ModelUnavailable)
def _model_unavailable(_: Request, __: Exception) -> JSONResponse:  # NFR-22: the same labelled replay offer
    return JSONResponse(
        status_code=503,
        content={"detail": _deps.MODEL_UNAVAILABLE_MESSAGE, "replay_only": True, "code": "model_unavailable"},
    )


@app.exception_handler(_spend.SpendCapReached)
def _spend_cap_reached(_: Request, __: Exception) -> JSONResponse:  # SEC-16: new live work over the uid's cap
    return JSONResponse(status_code=403, content={"detail": _spend.CAP_REACHED, "code": "spend_cap_reached"})


def _world_views(store: Annotated[_deps.Store, Depends(_deps.get_store)]) -> Callable[[str], WorldView]:
    """FR-HIL-12: each world's own CardStore and its Pause all state, for the share routes."""

    def view(world_id: str) -> WorldView:
        world = store.worlds.get(world_id)
        return WorldView(
            _runs.get_card_store(world_id, store), paused=world is None or world.paused
        )  # no record: closed, like Run.paused

    return view


app.include_router(_access_router)
app.include_router(_sample_router)  # STARTER-1: ahead of the owner-scoped /worlds/{id} routes
app.include_router(intake_router)
app.include_router(_dispatch_router)
app.include_router(_redaction_router)
app.include_router(_costs_router)
app.include_router(_context_panel_router)
app.include_router(_worlds_list_router)
app.include_router(_cards_feed_router)
app.include_router(_notifications_router)
app.include_router(_tasks_router)
app.include_router(
    _build_cards_router(_runs.get_card_store, answer_guard=_runs.answer_guard, world_owner=_runs.world_owner)
)
app.include_router(_build_console_router(_runs.get_card_store, answer_guard=_runs.answer_guard))
app.include_router(_build_sharing_router(_world_views))
app.include_router(_runs.router)
app.include_router(_item_fields_router)
app.include_router(_meeting_room_router)
app.include_router(_assistant_router)
app.include_router(_people.router)
app.include_router(_plate_links.router)  # FR-PA-06b: /l/<token> (public to the gate; the route checks the link)
app.include_router(_team_shares_router)  # ADR-0040: owner-only PUT/DELETE of a world's team share
app.include_router(_team_items_router)  # ADR-0040: the team view of a shared world's work items
app.include_router(_meeting_host_routes.router)
app.include_router(_byok_routes.router)  # ADR-0041: /v1/org/model-key; 503 not_configured while config/byok.yaml is off
_meeting_minutes_flag.configure_minutes_flag(_deps.get_flag_store())
_owner_minutes_routes.install_owner_minutes_routes(app, _deps.get_flag_store())
app.include_router(_quiz_apps.router)
app.include_router(_results.router)
app.include_router(_connect_routes.router)
app.include_router(_people_list_router)
app.include_router(_people_teams_router)
app.include_router(_skills_router)
app.include_router(_skills_capture_router)
app.include_router(_skills_media_router)
app.include_router(_skills_feedback_router)
app.include_router(_effort_router)
app.include_router(_feedback_router)
app.include_router(_push_router)
app.include_router(_connectors_list_router)
app.include_router(_schedules.router)
app.include_router(_meeting_voice_meter.router)  # ADR-0042: public to the gate, inert until TILO_VOICE_METER=1
app.include_router(_nudge_sweep.router)  # FR-PA-15b: GET /v1/nudges, POST /v1/nudges/{id}/snooze
app.include_router(_team_router)
app.include_router(_user_settings_router)  # FR-SET-01/02: GET and PUT /v1/me/settings
app.include_router(_brief_router)  # ADR-0049: /v1/me/brief and /v1/me/brief-settings (MO-01..04)


def _world_owner(world_id: str) -> str | None:
    """The world's owner from the store the app is wired with (503 `not_configured` when none is)."""
    world = app.dependency_overrides.get(_deps.get_store, _deps.get_store)().load_world(world_id, settle=False)
    return world.owner if world else None


app.include_router(_skill_proposals.build_router(_skill_proposals.get_skill_proposals, owner_of=_world_owner))
app.include_router(_health_deps_router)
_dev.install_if_enabled(app)  # only with TILO_API_DEV=1; refuses when deployed or live (CL-INT-4)


@app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
