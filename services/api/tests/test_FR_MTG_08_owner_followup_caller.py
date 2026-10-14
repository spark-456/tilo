"""Internal follow-up caller resolves server dependencies and produces offline T3 cards only."""

from typing import Annotated

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from test_FR_MTG_08_owner_followup import followup, replace  # noqa: F401
from tilo_api import deps
from tilo_api.appcheck import AppCheckGate
from tilo_people.stores import meeting_tombstone


@pytest.fixture
def caller_app(followup, monkeypatch):  # noqa: F811
    from tilo_api.owner_followup_caller import (
        OwnerFollowupCaller,
        get_owner_followup_autopilot_factory,
        get_owner_followup_caller,
        get_owner_followup_drafts,
    )
    from tilo_api.owner_minutes_caller import get_owner_minutes_budget

    c = followup
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
        return deps.Principal(c.writer.actor, "owner")

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
            get_owner_minutes_budget: lambda: 2,
            get_owner_followup_drafts: lambda: c.drafts,
            get_owner_followup_autopilot_factory: lambda: c.factory,
        }
    )

    # Only this test app exposes a route; no production route or automatic trigger is requested.
    @app.post("/__test_followup/{meeting_id}")
    def invoke(
        meeting_id: str,
        caller: Annotated[OwnerFollowupCaller, Depends(get_owner_followup_caller)],
        recipients: list[str] | None = None,
    ):
        return caller.draft(meeting_id, recipients=recipients)

    c.app, c.client = app, TestClient(app)
    c.draft_seam, c.factory_seam = get_owner_followup_drafts, get_owner_followup_autopilot_factory
    c.headers = {"Authorization": "Bearer test-owner", "X-Firebase-AppCheck": "test-appcheck"}
    return c


def call(c, meeting_id="mt_q4_plan", recipients=None, headers=None):
    return c.client.post(
        f"/__test_followup/{meeting_id}",
        json=recipients,
        headers=c.headers if headers is None else headers,
    )


@pytest.mark.parametrize("seam", ["draft_seam", "factory_seam"])
def test_FR_MTG_08_caller_default_server_seams_refuse(caller_app, seam):
    c = caller_app
    del c.app.dependency_overrides[getattr(c, seam)]
    response = call(c, recipients=[PRIYA])
    assert response.status_code == 503 and response.json()["detail"] == "not_configured"
    assert response.headers["cache-control"] == "no-store"
    assert c.calls == [] and c.line.bench.cards.dump() == "{}" and c.line.entries() == []


@pytest.mark.parametrize(
    "headers", [{}, {"X-Firebase-AppCheck": "test-appcheck"}, {"Authorization": "Bearer test-owner"}]
)
def test_FR_MTG_08_caller_requires_signin_and_appcheck(caller_app, headers):
    c = caller_app
    c.app.dependency_overrides[c.draft_seam] = lambda: pytest.fail("unauthenticated draft-store read")
    assert call(c, headers=headers).status_code == 401
    assert c.calls == [] and c.line.entries() == []


def test_FR_MTG_08_caller_resolves_directory_and_retries_without_send(caller_app):
    c = caller_app
    first = call(c, recipients=[PRIYA])
    assert first.status_code == 200
    preview = first.json()
    assert preview["tier"] == "T3" and preview["level"] == "L1"
    assert preview["to"] == ["priya@example.com"]
    assert c.line.bench.cards.get(OWNER, preview["card_id"])["thread_id"] is None
    assert call(c, recipients=[PRIYA]).json()["card_id"] == preview["card_id"]
    assert len(c.calls) == 1 and c.line.entries() == [] and c.line.api.sent == []


def test_FR_MTG_08_caller_default_nudges_confirmed_open_items(caller_app):
    c = caller_app
    response = call(c)
    assert response.status_code == 200 and len(response.json()) == 1
    assert response.json()[0]["tier"] == "T3"
    assert response.json()[0]["to"] == ["priya@example.com"]
    assert "Sam drafts" not in c.calls[0][1].prompt
    assert c.line.entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize("recipients", [["priya@example.com"], ["u_meera"]])
def test_FR_MTG_08_caller_rejects_non_directory_recipient(caller_app, recipients):
    c = caller_app
    assert call(c, recipients=recipients).status_code == 422
    assert c.calls == [] and c.line.bench.cards.dump() == "{}" and c.line.entries() == []


@pytest.mark.parametrize("change", ["owner", "expired", "id"])
def test_FR_MTG_08_caller_refuses_before_provider(caller_app, change):
    c = caller_app
    meeting_id = "mt_q4_plan"
    if change == "owner":
        c.writer.actor = SAM
    elif change == "expired":
        c.writer.now = c.meeting["delete_minutes_after"]
    else:
        meeting_id = "mt_" + "x" * 49
    assert call(c, meeting_id, [PRIYA]).status_code == (409 if change == "expired" else 404)
    assert c.calls == [] and c.line.bench.cards.dump() == "{}" and c.line.entries() == []


def test_FR_MTG_08_caller_clock_is_sampled_at_invocation(caller_app):
    from tilo_api.owner_followup_caller import OwnerFollowupCaller
    from tilo_api.owner_minutes_caller import OwnerMinutesCaller
    from tilo_api.people_writes import Refusal

    c = caller_app
    owner = OwnerMinutesCaller(
        c.request,
        deps.Principal(OWNER, "owner"),
        c.rig.real,
        c.rig.event_store,
        c.rig.artifacts,
        lambda: c.writer.now,
        c.writer.redact,
        c.switches,
        c.rig.events,
        2,
    )
    caller = OwnerFollowupCaller(owner, c.drafts, c.factory)
    c.writer.now = c.meeting["delete_minutes_after"]
    with pytest.raises(Refusal):
        caller.draft("mt_q4_plan", recipients=[PRIYA])
    assert c.calls == [] and c.line.entries() == []


def test_FR_MTG_08_caller_meeting_deletion_during_generation_stops_publication(caller_app):
    c = caller_app
    c.during.append(lambda: replace(c, "meetings", "mt_q4_plan", **meeting_tombstone(c.meeting)))
    assert call(c, recipients=[PRIYA]).status_code in {404, 409, 410}
    assert c.line.bench.cards.dump() == "{}" and c.line.entries() == [] and c.line.api.sent == []


def test_FR_MTG_08_caller_is_not_registered_on_production_app():
    from tilo_api import app

    assert all("__test_followup" not in path for path in app.openapi()["paths"])
