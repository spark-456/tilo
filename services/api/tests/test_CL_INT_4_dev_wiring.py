"""CL-INT-4 items 1 and 2 (ADR-0003, PRD 6.6 EFF-01): the local dev wiring behind `just dev-api` and its CORS.
Dev mode is `TILO_API_DEV=1`; it is impossible on Cloud Run (K_SERVICE or CLOUD_RUN_JOB set, as the fake safety
provider does it) and in live mode, it has one fixed owner, and it allows only the configured browser origin."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from _api_lib import WORLD, make_world
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps, dev
from tilo_api.redaction import router as redaction_router

VITE = "http://localhost:5173"
OTHER = "http://evil.example"
LOCAL = f"http://localhost:{dev.PORT}"  # the Host the dev server accepts


def dev_app(env: dict[str, str] | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(redaction_router)
    dev.install(app, {} if env is None else env)
    return app


def dev_store(app: FastAPI) -> deps.Store:
    return app.dependency_overrides[deps.get_store]()


@pytest.mark.parametrize("var", ["K_SERVICE", "CLOUD_RUN_JOB"])
@pytest.mark.parametrize("value", ["tilo-api", ""])
def test_CL_INT_4_dev_wiring_refuses_on_cloud_run(var, value):
    app = FastAPI()
    with pytest.raises(dev.DevModeRefused):
        dev.install(app, {var: value, dev.ENV_FLAG: "1"})
    assert app.dependency_overrides == {}, "a refused install must change nothing"
    assert app.user_middleware == []


def test_CL_INT_4_dev_wiring_refuses_in_live_mode():
    live = "LIVE"
    with pytest.raises(dev.DevModeRefused):
        dev.install(FastAPI(), {live: "1"})


def test_CL_INT_4_dev_wiring_is_off_unless_the_flag_is_exactly_one():
    for env in ({}, {dev.ENV_FLAG: "0"}, {dev.ENV_FLAG: "true"}, {dev.ENV_FLAG: ""}):
        app = FastAPI()
        assert dev.install_if_enabled(app, env) is False
        assert app.dependency_overrides == {}
    app = FastAPI()
    assert dev.install_if_enabled(app, {dev.ENV_FLAG: "1"}) is True


def test_CL_INT_4_app_start_up_fails_loudly_on_cloud_run():
    """The real module: importing tilo_api with dev on and K_SERVICE set must not start."""
    env = {**os.environ, dev.ENV_FLAG: "1", "K_SERVICE": "tilo-api"}
    done = subprocess.run(
        [sys.executable, "-c", "import tilo_api"], env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode != 0
    assert "DevModeRefused" in done.stderr


def test_CL_INT_4_dev_dependencies_recheck_the_environment_on_every_call(monkeypatch):
    app = dev_app()
    monkeypatch.setenv("K_SERVICE", "tilo-api")  # the process turned out to be deployed after all
    response = TestClient(app, base_url=LOCAL, raise_server_exceptions=False).get(f"/worlds/{WORLD}")
    assert response.status_code == 500
    with pytest.raises(dev.DevModeRefused):
        app.dependency_overrides[deps.get_store]()


def test_CL_INT_4_dev_principal_is_the_one_fixed_owner_of_its_own_worlds():
    app = dev_app()
    dev_store(app).worlds[WORLD] = make_world(owner=dev.DEV_OWNER, districts={"D1": deps.DistrictRecord("A", "b")})
    dev_store(app).worlds["w_someone_else"] = make_world(
        owner="u_other", districts={"D1": deps.DistrictRecord("Hidden", "x")}
    )
    client = TestClient(app, base_url=LOCAL)
    assert client.get(f"/worlds/{WORLD}").json()["districts"] == [{"id": "D1", "name": "A", "summary": "b"}]
    assert client.get("/worlds/w_unknown").status_code == 404
    other = client.get("/worlds/w_someone_else").json()  # not its owner, so no owner view
    assert (other["districts"], other["has_hidden_districts"]) == ([], True)


def test_CL_INT_4_dev_event_writer_stamps_validates_and_is_idempotent(registry):
    app = dev_app()
    store = dev_store(app)
    store.worlds[WORLD] = make_world(owner=dev.DEV_OWNER)
    writer = app.dependency_overrides[deps.get_event_writer]()
    part = {
        "id": "01JB5VQ0000000000000000001", "type": "world.started", "actor": "A_director", "target": WORLD,
        "summary": "Work started.", "data": {"budget_cap": 60}, "vis": "all",
    }  # fmt: skip
    first = writer.append(WORLD, part)
    assert (first["v"], first["seq"], first["world_id"], first["run_id"]) == ("1.0", 1, WORLD, "r_village_basic_1")
    assert writer.append(WORLD, part) == first and len(store.events[WORLD]) == 1
    second = writer.append(WORLD, {**part, "id": "01JB5VQ0000000000000000002"})
    assert second["seq"] == 2
    with pytest.raises(deps.EventRejected):
        writer.append(WORLD, {**part, "summary": "Different."})
    with pytest.raises(deps.EventRejected):
        writer.append(WORLD, {**part, "id": "01JB5VQ0000000000000000003", "type": "not.registered"})
    with pytest.raises(deps.EventRejected):
        writer.append("w_unknown", part)
    assert [e["seq"] for e in store.events[WORLD]] == [1, 2]


def preflight(client: TestClient, origin: str):
    return client.options(
        f"/worlds/{WORLD}",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_CL_INT_4_cors_allows_only_the_default_vite_origin():
    client = TestClient(dev_app(), base_url=LOCAL)
    allowed = preflight(client, VITE)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == VITE
    assert allowed.headers["access-control-allow-origin"] != "*"
    denied = preflight(client, OTHER)
    assert "access-control-allow-origin" not in denied.headers
    simple = client.get(f"/worlds/{WORLD}", headers={"Origin": OTHER})
    assert "access-control-allow-origin" not in simple.headers


def test_CL_INT_4_cors_origins_come_from_the_environment():
    client = TestClient(dev_app({dev.ENV_ORIGINS: "http://localhost:4173, http://127.0.0.1:5174/"}), base_url=LOCAL)
    assert preflight(client, "http://localhost:4173").headers["access-control-allow-origin"] == "http://localhost:4173"
    assert preflight(client, "http://127.0.0.1:5174").headers["access-control-allow-origin"] == "http://127.0.0.1:5174"
    assert "access-control-allow-origin" not in preflight(client, VITE).headers, "the default is replaced, not added to"


@pytest.mark.parametrize("bad", ["*", "null", "http://localhost:5173/app", "localhost:5173", "http://a.test, *"])
def test_CL_INT_4_cors_refuses_wildcards_and_malformed_origins(bad):
    with pytest.raises(dev.DevModeRefused):
        dev_app({dev.ENV_ORIGINS: bad})


def test_CL_INT_4_cors_is_absent_when_dev_mode_is_off(client):
    from tilo_api import app

    assert not any(m.cls.__name__ == "CORSMiddleware" for m in app.user_middleware)
