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
# /health/deps and /healthz/deps: X-HEALTH-1, public by the owner's decision (14 Oct), booleans and fixed kinds only.
OPEN = {
    "/health",
    "/healthz",
    "/health/deps",
    "/healthz/deps",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

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
# Cloud Scheduler / Cloud Tasks call this one with a Google OIDC token, never a person's sign-in. It checks its
# config first and answers 503 (tilo-api: `not_configured`; harness: `unavailable`) while no audience/caller is set
# (the production default, fail closed). The 401/403 for a missing, bad or wrong-caller token needs a wired verifier and
# store, which no real process has here: the services' own tests drive it (test_FR_AGT_14_schedule_routes.py).
TICK = "/internal/schedules/tick"
# FR-PA-06b (the owner's decision, 13 Oct 2026): the plate digest's mail links are public to the gate, because a mail
# click has no sign-in; the signed single-use token is the credential. Unconfigured (no signing key) the route is 503.
LINK_ROUTES = {("GET", "/l/{token}"), ("POST", "/l/{token}")}


def _refuses_anonymous(method: str, path: str, status: int) -> bool:
    return status in ({401, 403, 503} if path == TICK else {401, 403})


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
            assert _refuses_anonymous(method, path, response.status_code), (
                f"{name} {method} {path} answered {response.status_code}"
            )
            if path == TICK:  # unconfigured means closed, not open: it never reaches the token or any side effect
                assert response.status_code == 503, f"{name} {path} answered {response.status_code}"
    finally:
        server.stop()


def test_SYS_SEC_05_tilo_api_without_dev_mode_serves_nothing_that_needs_a_person(prod_api):
    served = [(m, p) for m, p in _operations("tilo_api:app") if p not in OPEN]
    assert LINK_ROUTES <= set(served), "the mail-link routes are the named exception"
    for method, path in sorted(LINK_ROUTES):  # no signing key here: closed, not open, and never a sign-in 401
        answer = httpx.request(method, prod_api.url + _fill(path), timeout=15)
        assert answer.status_code == 503, f"{method} {path} answered {answer.status_code}"
    ops = [r for r in served if r not in LINK_ROUTES]
    assert ("POST", "/intake") in ops and ("GET", "/worlds/{world_id}/events") in ops, "the route list was read"
    for method, path in ops:
        response = httpx.request(method, prod_api.url + _fill(path), json={} if method == "POST" else None, timeout=15)
        expected = 503 if path == TICK else 401  # the tick has no sign-in to ask for: it fails closed, unconfigured
        assert response.status_code == expected, f"{method} {path} answered {response.status_code} with no sign-in"
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
