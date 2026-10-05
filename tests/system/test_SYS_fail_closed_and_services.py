"""SYS (SEC-05, PRD 6.2, ADR-0003): every service starts the way its Dockerfile starts it, and
`tilo-api` without dev mode refuses every call that needs a person, the way the deployed one must.

The deployed check (a Cloud Run service's ingress and Ready condition) is a read-only walk against
tilo-dev, documented in docs/system-test.md; this file is its local twin."""

from __future__ import annotations

import importlib

import httpx
import pytest
from _sys_lib import Server, free_port

pytestmark = pytest.mark.system

# Not behind a sign-in by design: liveness, the generated API description and the docs.
OPEN = {"/health", "/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

# service name -> (ASGI app, the routes besides OPEN it serves, with who may call them)
SERVICES = {
    "harness": "tilo_harness.app:app",
    "channels": "tilo_channels.app:app",
    "connectors": "tilo_connectors.app:app",
    "browser": "tilo_browser.app:app",
    "render": "tilo_render.app:app",
    "sandbox-web": "tilo_sandbox_web.app:app",
}
# sandbox-web is the public practice site the browser worker drives (PRD 6.5): its pages are open on purpose.
PUBLIC_BY_DESIGN = {"sandbox-web": {"/manifest.json"}}


def _operations(app: str) -> list[tuple[str, str]]:
    """The routes an app serves, read in-process: no service publishes /openapi.json any more (#411)."""
    module, name = app.split(":")
    spec = getattr(importlib.import_module(module), name).openapi()
    return [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops if m.upper() != "HEAD"]


def _fill(path: str) -> str:
    return path.replace("{", "x_").replace("}", "")


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_SYS_P0_07a_each_service_starts_and_answers_both_health_paths(name):
    server = Server(SERVICES[name], free_port()).start(ready_path="/health")
    try:
        for path in ("/health", "/healthz"):
            response = httpx.get(server.url + path)
            assert (response.status_code, response.json()) == (200, {"status": "ok"}), path
        assert httpx.get(server.url + "/no-such-route").status_code == 404
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert httpx.get(server.url + path).status_code == 404, f"{name} publishes {path} (#411)"
    finally:
        server.stop()


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_SYS_SEC_05_a_service_route_that_is_not_public_by_design_refuses_an_anonymous_call(name):
    server = Server(SERVICES[name], free_port()).start(ready_path="/health")
    try:
        if name == "sandbox-web":
            ops = [("GET", "/manifest.json"), ("GET", "/s/x/x")]
        else:
            ops = _operations(SERVICES[name])
        for method, path in ops:
            if path in OPEN or path in PUBLIC_BY_DESIGN.get(name, set()) or path.startswith("/s/"):
                continue
            response = httpx.request(method, server.url + _fill(path), json={} if method == "POST" else None)
            assert response.status_code in {401, 403}, f"{name} {method} {path} answered {response.status_code}"
    finally:
        server.stop()


def test_SYS_SEC_05_tilo_api_without_dev_mode_serves_nothing_that_needs_a_person(prod_api):
    ops = [(m, p) for m, p in _operations("tilo_api:app") if p not in OPEN]
    assert ("POST", "/intake") in ops and ("GET", "/worlds/{world_id}/events") in ops, "the route list was read"
    for method, path in ops:
        response = httpx.request(method, prod_api.url + _fill(path), json={} if method == "POST" else None, timeout=15)
        assert response.status_code == 401, f"{method} {path} answered {response.status_code} with no sign-in"
        assert "Traceback" not in response.text and "NotImplementedError" not in response.text, (
            f"{method} {path} leaks a server error body"
        )


def test_SYS_SEC_05_an_anonymous_call_to_tilo_api_is_a_clean_401_not_a_500(prod_api):
    for method, path in [("POST", "/intake"), ("GET", "/worlds/w_x/events"), ("POST", "/worlds/w_x/pause")]:
        response = httpx.request(method, prod_api.url + path, json={} if method == "POST" else None, timeout=15)
        assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


def test_SYS_SEC_05_tilo_api_without_dev_mode_does_not_publish_its_route_list(prod_api):
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert httpx.get(prod_api.url + path).status_code == 404, f"tilo-api publishes {path} (#411)"
