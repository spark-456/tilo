"""CL-INT-4 hardening (security round 1 on #220): the dev server answers only its own loopback Host (no DNS
rebinding), sends no credentials header, never defaults an event's `vis`, and re-checks the environment on every
dependency call."""

from __future__ import annotations

import pytest
from _api_lib import WORLD, make_world
from fastapi.testclient import TestClient
from test_CL_INT_4_dev_wiring import LOCAL, VITE, dev_app, dev_store, preflight
from tilo_api import deps, dev

PART = {
    "id": "01JB5VQ0000000000000000001", "type": "world.started", "actor": "A_director", "target": WORLD,
    "summary": "Work started.", "data": {"budget_cap": 60},
}  # fmt: skip


@pytest.mark.parametrize("host", ["localhost:8080", "127.0.0.1:8080", "[::1]:8080", "LOCALHOST:8080"])
def test_CL_INT_4_dev_server_answers_only_its_own_loopback_host(host):
    client = TestClient(dev_app(), base_url=f"http://{host}")
    assert client.get("/worlds/w_x").status_code == 404  # reached the route, so not a host refusal


@pytest.mark.parametrize(
    "host",
    ["evil.example:8080", "localhost:9999", "localhost", "127.0.0.1.evil.example:8080", "localhost.evil.example:8080",
     "[::1]", "0.0.0.0:8080", "testserver", ""],
)  # fmt: skip
def test_CL_INT_4_dev_server_refuses_a_rebound_or_foreign_host_before_any_route(host):
    app = dev_app()
    dev_store(app).worlds[WORLD] = make_world(owner=dev.DEV_OWNER)
    response = TestClient(app, base_url=LOCAL).get(f"/worlds/{WORLD}/events", headers={"host": host})
    assert response.status_code == 400
    assert "events" not in response.text and WORLD not in response.text


def test_CL_INT_4_host_check_runs_before_cors():
    client = TestClient(dev_app(), base_url=LOCAL)
    refused = client.options(
        "/worlds/w_x", headers={"host": "evil.example:8080", "Origin": VITE, "Access-Control-Request-Method": "GET"}
    )
    assert refused.status_code == 400 and "access-control-allow-origin" not in refused.headers


def test_CL_INT_4_cors_sends_no_credentials_header():
    client = TestClient(dev_app(), base_url=LOCAL)
    allowed = preflight(client, VITE)
    assert allowed.headers["access-control-allow-origin"] == VITE
    assert "access-control-allow-credentials" not in allowed.headers
    simple = client.get(f"/worlds/{WORLD}", headers={"Origin": VITE})
    assert "access-control-allow-credentials" not in simple.headers


def test_CL_INT_4_dev_event_writer_refuses_an_event_without_vis_and_never_defaults_it():
    app = dev_app()
    store = dev_store(app)
    store.worlds[WORLD] = make_world(owner=dev.DEV_OWNER)
    writer = app.dependency_overrides[deps.get_event_writer]()
    for bad in (PART, {**PART, "vis": None}):
        with pytest.raises(deps.EventRejected):
            writer.append(WORLD, bad)
    assert store.events.get(WORLD, []) == []
    assert writer.append(WORLD, {**PART, "vis": "all"})["vis"] == "all"
    narrower = writer.append(WORLD, {**PART, "id": "01JB5VQ0000000000000000002", "vis": ["D1"], "district": "D1"})
    assert narrower["vis"] == ["D1"], "a stated vis is kept as given, never widened"


def test_CL_INT_4_dev_writer_override_rechecks_the_environment_per_call(monkeypatch):
    app = dev_app()
    monkeypatch.setenv("CLOUD_RUN_JOB", "x")
    with pytest.raises(dev.DevModeRefused):
        app.dependency_overrides[deps.get_event_writer]()


def test_CL_INT_4_the_dev_port_is_8080_unless_an_unprivileged_port_is_named():
    from tilo_api import dev

    assert dev.dev_port({}) == 8080
    assert dev.dev_port({"TILO_API_DEV_PORT": ""}) == 8080
    assert dev.dev_port({"TILO_API_DEV_PORT": "8181"}) == 8181
    for bad in ("80", "99999", "abc", "-8181", "8181 "):
        with pytest.raises(dev.DevModeRefused):
            dev.dev_port({"TILO_API_DEV_PORT": bad})
