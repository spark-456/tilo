import csv as csvlib
import io
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, NewVersion, Origin, Scope
from tilo_people.stores import PeopleStores
from tilo_providers.safety import FakeSafetyProvider

OWNER, OTHER, WORLD, RUN = "u_owner", "u_other", "w_apps", "r_apps"
HTML = b"<!doctype html><html><body><h1>Customer survey</h1></body></html>"


@pytest.fixture
def app_case():
    from tilo_api.app_response_store import InMemoryAppStore
    from tilo_api.app_responses import get_app_store, router

    artifacts = ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: datetime(2026, 10, 18, tzinfo=UTC),
        redactor=lambda value: value,
        archive_lookup=lambda *_: None,
        alert_sink=lambda _: None,
        screener=FakeSafetyProvider(),
    )
    item = artifacts.put(
        Scope(deps.ORG_ID, WORLD, OWNER),
        NewVersion("text/html", HTML, RUN, Origin("unit", "U1", "A_writer"), idempotency_key=f"{RUN}:U1:0:0"),
    )
    state = deps.Store(worlds={WORLD: deps.WorldRecord(OWNER, {}, run_id=RUN)})
    state.events[WORLD] = [
        {"type": "artifact.created", "data": {"artifact": item.ref}},
        {"type": "artifact.delivered", "data": {"artifact": item.ref, "format": "website"}},
    ]
    state.runs[WORLD] = type("Run", (), {"titles": {item.artifact_id: "Customer survey"}})()
    people, apps = PeopleStores.in_memory(), InMemoryAppStore()
    people.persons.create(
        {
            "id": OWNER,
            "org_id": deps.ORG_ID,
            "display_name": "Jo Smith",
            "aliases": [],
            "email": "jo@example.com",
            "time_zone": "Asia/Kolkata",
            "preferred_channel": "web",
            "org_role": "owner",
            "memberships": [],
            "created_by": {"by": OWNER, "at": "2026-10-18T00:00:00.000Z"},
        }
    )
    api = FastAPI()
    api.include_router(router)
    api.dependency_overrides.update(
        {
            deps.get_store: lambda: state,
            deps.get_artifact_store: lambda: artifacts,
            deps.get_people_stores: lambda: people,
            get_app_store: lambda: apps,
            deps.get_current_principal: lambda: deps.Principal(OWNER, "owner", WORLD),
            deps.get_clock: lambda: lambda: "2026-10-18T12:00:00.000Z",
        }
    )
    return api, apps, item.artifact_id


def test_P0_TILO_APPS_publish_public_submit_owner_csv_and_unpublish(app_case):
    api, _, artifact = app_case
    with TestClient(api) as client:
        published = client.post(f"/v1/artifacts/{artifact}/publish", json={}).json()["app"]
        assert published["path"] == "/u/jo-smith/customer-survey" and published["published"] is True
        public = client.get("/public/apps/jo-smith/customer-survey")
        assert public.json() == {"title": "Customer survey", "html": HTML.decode()}
        saved = client.post(
            "/public/apps/jo-smith/customer-survey/responses",
            json={
                "fields": {
                    "name": "Ada\u0000",
                    "formula": "=2+2",
                    "choice": "+yes",
                    "=header": "safe",
                    "bad\u0000key": "clean",
                },
                "website": "",
            },
        )
        assert saved.status_code == 201 and saved.json()["count"] == 1
        trapped = client.post(
            "/public/apps/jo-smith/customer-survey/responses", json={"fields": {"name": "Bot"}, "website": "spam"}
        )
        assert trapped.status_code == 201
        listing = client.get(f"/v1/artifacts/{artifact}/responses").json()
        assert listing["count"] == 1 and listing["responses"][0]["fields"]["name"] == "Ada"
        csv = client.get(f"/v1/artifacts/{artifact}/responses.csv")
        assert csv.status_code == 200 and "'=2+2" in csv.text and "'+yes" in csv.text
        assert next(csvlib.reader(io.StringIO(csv.text)))[3:] == ["name", "formula", "choice", "'=header", "badkey"]
        assert client.delete(f"/v1/artifacts/{artifact}/publish").json()["app"]["published"] is False
        assert client.get("/public/apps/jo-smith/customer-survey").status_code == 404


def test_P0_TILO_APPS_signed_artifact_reader_requires_access(app_case):
    api, _, artifact = app_case
    with TestClient(api) as client:
        result = client.get(f"/v1/artifacts/{artifact}")
        assert result.status_code == 200
        assert result.json() == {"title": "Customer survey", "html": HTML.decode()}
        api.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(OTHER, "owner", "elsewhere")
        assert client.get(f"/v1/artifacts/{artifact}").status_code == 404


def test_P0_TILO_APPS_owner_can_reload_publication_status(app_case):
    api, _, artifact = app_case
    with TestClient(api) as client:
        assert client.get(f"/v1/artifacts/{artifact}/publish").status_code == 404
        published = client.post(f"/v1/artifacts/{artifact}/publish", json={}).json()["app"]
        assert client.get(f"/v1/artifacts/{artifact}/publish").json()["app"]["path"] == published["path"]
        client.delete(f"/v1/artifacts/{artifact}/publish")
        assert client.get(f"/v1/artifacts/{artifact}/publish").json()["app"]["published"] is False


def test_P0_TILO_APPS_signed_in_editor_capture_and_owner_delete(app_case):
    api, _, artifact = app_case
    with TestClient(api) as client:
        made = client.post(f"/v1/artifacts/{artifact}/responses", json={"fields": {"answer": "yes"}})
        assert made.status_code == 201 and made.json()["count"] == 1
        response_id = made.json()["response_id"]
        assert client.delete(f"/v1/artifacts/{artifact}/responses/{response_id}").status_code == 204
        assert client.get(f"/v1/artifacts/{artifact}/responses").json()["count"] == 0
        api.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(OTHER, "viewer", WORLD)
        viewed = client.post(f"/v1/artifacts/{artifact}/responses", json={"fields": {"answer": "viewer"}})
        assert viewed.status_code == 201
        api.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(OTHER, "team_lead", WORLD)
        assert client.get(f"/v1/artifacts/{artifact}/responses").status_code == 404
        assert client.get(f"/v1/artifacts/{artifact}/responses.csv").status_code == 404
        assert client.delete(f"/v1/artifacts/{artifact}/responses/{viewed.json()['response_id']}").status_code == 404
        assert client.delete(f"/v1/artifacts/{artifact}/publish").status_code == 404


def test_P0_TILO_APPS_caps_access_and_public_route_shape(app_case):
    from tilo_api import access

    api, apps, artifact = app_case
    with TestClient(api) as client:
        client.post(f"/v1/artifacts/{artifact}/publish", json={})
        assert (
            client.post(
                "/public/apps/jo-smith/customer-survey/responses",
                content=b'{"fields":{"x":"' + b"x" * 17000 + b'"}}',
                headers={"content-type": "application/json"},
            ).status_code
            == 413
        )
        api.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(OTHER, "owner", WORLD)
        assert client.get(f"/v1/artifacts/{artifact}/responses").status_code == 404
    assert access.public_link("GET", "/public/apps/jo-smith/customer-survey")
    assert access.public_link("POST", "/public/apps/jo-smith/customer-survey/responses")
    assert not access.public_link("GET", "/public/apps/jo-smith/customer-survey/responses")
    apps.seed_count(artifact, 5000)
    with TestClient(api) as client:
        capped = client.post("/public/apps/jo-smith/customer-survey/responses", json={"fields": {"x": "y"}})
        assert capped.status_code == 409
