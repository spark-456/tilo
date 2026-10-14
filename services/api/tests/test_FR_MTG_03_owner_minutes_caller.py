"""Internal owner caller: offline dependency/auth/refusal integration, no shipped route."""

from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import owner_call  # noqa: F401
from tilo_api import deps, spend
from tilo_api.access import AccessGate
from tilo_api.appcheck import AppCheckGate

REAL_WORK_MODE = deps.get_work_mode


@pytest.fixture
def caller_app(owner_call, monkeypatch):  # noqa: F811
    from tilo_api.owner_minutes_caller import OwnerMinutesCaller, get_owner_minutes_budget, get_owner_minutes_caller

    c = owner_call
    app = FastAPI()
    app.add_middleware(AppCheckGate)
    monkeypatch.setenv("TILO_APPCHECK_ENFORCE", "1")

    class Check:
        def verify(self, token):
            if token != "test-appcheck":
                raise ValueError("refused")
            return {}

    def principal(request: Request):
        if request.headers.get("authorization") != "Bearer test-owner":
            raise HTTPException(401, "sign_in_required")
        return deps.Principal(c.writer.actor, "owner", demo_session=c.demo)

    c.demo = False
    app.dependency_overrides.update(
        {
            deps.get_current_principal: principal,
            deps.get_people_stores: lambda: c.rig.real,
            deps.get_store: lambda: c.rig.event_store,
            deps.get_artifact_store: lambda: c.rig.artifacts,
            deps.get_clock: lambda: lambda: c.writer.now,
            deps.get_redactor: lambda: c.writer.redact,
            deps.get_switches: lambda: c.switches,
            deps.get_event_writer: lambda: c.rig.events,
            deps.get_app_check_verifier: lambda: Check(),
        }
    )

    # Only this isolated harness registers a route; the production app remains unchanged.
    @app.post("/__test_minutes/{meeting_id}")
    def invoke(meeting_id: str, caller: Annotated[OwnerMinutesCaller, Depends(get_owner_minutes_caller)]):
        return caller.analyze(meeting_id)

    c.app, c.client, c.budget_seam = app, TestClient(app), get_owner_minutes_budget
    c.headers = {"Authorization": "Bearer test-owner", "X-Firebase-AppCheck": "test-appcheck"}
    return c


def call(c, meeting_id="mt_q4_plan", headers=None):
    return c.client.post(f"/__test_minutes/{meeting_id}", headers=c.headers if headers is None else headers)


def test_FR_MTG_03_caller_missing_config_refuses_before_store_or_provider(caller_app):
    c = caller_app

    def unavailable_config():
        raise HTTPException(503, "not_configured", headers={"Cache-Control": "no-store"})

    c.app.dependency_overrides[deps.get_assistant_config] = unavailable_config
    c.app.dependency_overrides[deps.get_people_stores] = lambda: pytest.fail("disabled factory read store")
    response = call(c)
    assert response.status_code == 503 and response.json()["detail"] == "not_configured"
    assert response.headers["cache-control"] == "no-store"
    assert not c.router.calls and not c.modes


@pytest.mark.parametrize(
    "headers", [{}, {"X-Firebase-AppCheck": "test-appcheck"}, {"Authorization": "Bearer test-owner"}]
)
def test_FR_MTG_03_caller_requires_signin_and_appcheck(caller_app, headers):
    c = caller_app
    c.app.dependency_overrides[c.budget_seam] = lambda: pytest.fail("unauthenticated budget read")
    assert call(c, headers=headers).status_code == 401
    assert not c.router.calls


@pytest.mark.parametrize("demo", [False, True])
def test_FR_MTG_03_caller_server_dependencies_replay_under_outer_live(caller_app, monkeypatch, demo):
    c = caller_app
    monkeypatch.setenv("LIVE", "1")
    c.demo = demo
    if demo:
        # Even a mode factory reporting live cannot override the verified demo principal.
        monkeypatch.setattr(deps, "get_work_mode", lambda *args: "live")
    else:
        # Actual mode resolution fails closed to replay when the live ledger is unwired.
        monkeypatch.setattr(deps, "get_work_mode", REAL_WORK_MODE)
        c.switches = spend.Switches(c.flags, None)
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    response = call(c)
    assert response.status_code == 200 and response.json()["status"] == "minuted"
    assert response.json()["minutes_confirmed_by"] is None
    assert c.modes == [("router", "replay"), ("safety", "replay")]
    assert c.ledger.spent_minor(c.writer.actor) == 0


@pytest.mark.parametrize("declaration", [None, "visitor"])
def test_FR_MTG_03_caller_retains_deployed_access_gate(caller_app, monkeypatch, declaration):
    c = caller_app
    monkeypatch.setenv("K_SERVICE", "test-only-api")
    c.app.add_middleware(AccessGate)
    c.app.dependency_overrides[deps.get_access_store] = lambda: SimpleNamespace(get=lambda uid: declaration)
    c.app.dependency_overrides[c.budget_seam] = lambda: pytest.fail("access refusal reached budget")
    assert call(c).status_code == 403
    assert not c.router.calls


@pytest.mark.parametrize("change", ["owner", "world", "missing_start", "invalid_start", "future_start"])
def test_FR_MTG_03_caller_refuses_before_provider(caller_app, monkeypatch, change):
    from _ppl11a_lib import SAM

    c = caller_app
    c.app.dependency_overrides[c.budget_seam] = lambda: 2
    if change == "owner":
        c.writer.actor = SAM
    elif change == "world":
        c.rig.event_store.worlds[c.scope.world_id].owner = SAM
    else:
        stored = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
        scheduled = (
            None
            if change == "missing_start"
            else {
                "start": "invalid" if change == "invalid_start" else "2099-01-01T00:00:00.000Z",
                "end": "2099-01-01T01:00:00.000Z",
            }
        )
        if change == "invalid_start":
            # A corrupt durable read cannot be inserted through the schema-checking memory writer.
            real_get = c.rig.real.meetings.get
            monkeypatch.setattr(
                c.rig.real.meetings,
                "get",
                lambda org, key: (
                    SimpleNamespace(record={**stored.record, "scheduled": scheduled}, version=stored.version)
                    if key == "mt_q4_plan"
                    else real_get(org, key)
                ),
            )
        else:
            c.rig.real.meetings.replace({**stored.record, "scheduled": scheduled}, expected_version=stored.version)
    before = c.rig.snapshot()
    response = call(c)
    # A malformed stored record fails the existing access/schema oracle with its uniform404.
    assert response.status_code == (404 if change in {"owner", "world", "invalid_start"} else 409)
    assert not c.router.calls and not c.modes and c.rig.snapshot() == before


@pytest.mark.parametrize("budget", [True, 0, -1, float("nan"), float("inf")])
def test_FR_MTG_03_caller_refuses_invalid_server_budget(caller_app, budget):
    c = caller_app
    c.app.dependency_overrides[c.budget_seam] = lambda: budget
    assert call(c).status_code == 503
    assert not c.router.calls


def test_FR_MTG_03_caller_is_not_registered_on_production_app():
    from tilo_api import app

    assert all("__test_minutes" not in path for path in app.openapi()["paths"])
