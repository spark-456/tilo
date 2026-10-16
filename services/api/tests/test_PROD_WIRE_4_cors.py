"""PROD-WIRE-4 (slice 4, deployed edge): production CORS on tilo-api, so the Firebase Hosting web app can call the
Cloud Run API from the browser, and nobody else's page can.

Ticket scope (test-writer brief, PROD-WIRE-4):
  * Only when deployed (`tilo_api.access.enforced()`, `K_SERVICE` present, read per request).
  * Allowed origins are exactly `https://essential-wares-510320-f0.web.app` and
    `https://essential-wares-510320-f0.firebaseapp.com`: no wildcard, no suffix or prefix trick, no `http://`, no
    `null`, no trailing slash, no case variant, no port, no dev origin.
  * Credentials are never allowed (`Access-Control-Allow-Credentials` is never sent).
  * Request headers allowed: `Authorization`, `X-Tilo-Channel`, `X-Firebase-AppCheck`, `Content-Type`,
    `Idempotency-Key` (plus the three
    CORS-safelisted names that Starlette's stock middleware always lists; they grant nothing). Nothing else.
  * Methods: the ones the routers use (GET, POST, PUT, PATCH, DELETE) plus OPTIONS for the preflight.
  * A preflight is answered before the SEC-15 gate and before `_NoStore`: 200/204, never 401/403/503, and neither the
    principal nor the access store is called. The gate's own refusals (401, 403, 503) still carry the CORS headers, so
    the browser can read them.
  * A disallowed origin gets no `Access-Control-Allow-Origin` at all. `Vary: Origin` is on every answer to an allowed
    origin.
  * Not deployed: the production allowlist adds nothing. Dev mode's own CORS (`tilo_api.dev`) is untouched and does
    not grant the production origins.

11 Oct supervisor policy: current routes require PUT and Idempotency-Key, and browsers must read Retry-After.
All origin, credential and gate checks remain enforced.

No network, no cloud: the real app under a TestClient, deployed-style through the SEC-15 harness (`_sec15_lib`).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest
from _sec15_lib import JUDGE, VISITOR, route_table
from tilo_api import app, deps

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

WEB_APP = "https://essential-wares-510320-f0.web.app"
FIREBASE_APP = "https://essential-wares-510320-f0.firebaseapp.com"
ALLOWED = (WEB_APP, FIREBASE_APP)

# Every one of these must get nothing: no Access-Control-Allow-Origin, no grant.
NEVER_ALLOWED = (
    "*",
    "null",
    "https://essential-wares-510320-f0.web.app.evil.test",  # suffix trick
    "https://evil-essential-wares-510320-f0.web.app",  # prefix trick
    "https://evil.test/https://essential-wares-510320-f0.web.app",
    "https://sub.essential-wares-510320-f0.web.app",  # a subdomain is not the site
    "http://essential-wares-510320-f0.web.app",  # http variants
    "http://essential-wares-510320-f0.firebaseapp.com",
    WEB_APP + "/",  # trailing slash
    FIREBASE_APP + "/",
    "https://ESSENTIAL-WARES-510320-F0.WEB.APP",  # case (browsers send lowercase)
    "https://Essential-Wares-510320-F0.firebaseapp.com",
    WEB_APP + ":443",  # a port is never sent for https, so it is never allowed
    "https://web.app",
    "https://tilo-demo.web.app",  # another project's site
    "http://localhost:5173",  # the dev origin is not a production origin
)

# Real gated routes: (method, path, request headers a browser would ask for in the preflight).
GATED = (
    ("GET", "/worlds", ""),
    ("GET", "/cards", ""),
    ("GET", "/v1/plate", "authorization,x-tilo-channel"),  # a `/v1/` path: `_NoStore` wraps it
    ("POST", "/intake", "authorization,x-tilo-channel"),
    ("POST", "/tasks/t_probe/approve", "content-type,authorization,x-tilo-channel,x-firebase-appcheck"),
)

REQUEST_HEADERS = ("authorization", "x-tilo-channel", "x-firebase-appcheck", "content-type", "idempotency-key")
SAFELISTED_EXTRAS = {
    "accept",
    "accept-language",
    "content-language",
}  # Starlette always lists these; they grant nothing
ROUTER_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def preflight(client, path: str, origin: str, method: str = "GET", headers: str = ""):
    request_headers = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers:
        request_headers["Access-Control-Request-Headers"] = headers
    return client.options(path, headers=request_headers)


def tokens(response, name: str) -> set[str]:
    return {t.strip().lower() for t in response.headers.get(name, "").split(",") if t.strip()}


@pytest.fixture()
def deployed(sec15_factory, monkeypatch):
    """The real app, deployed-style (K_SERVICE set), a visitor signed in, with spies on the principal seam and on the
    access store so a test can say what a preflight must not touch."""
    monkeypatch.delenv("TILO_API_STORE", raising=False)
    sec = sec15_factory(declarations={VISITOR: "visitor", JUDGE: "judge"})
    sec.as_user(VISITOR)
    calls: list[str] = []
    real = app.dependency_overrides[deps.get_current_principal]

    def principal_spy():
        calls.append("principal")
        return real()

    app.dependency_overrides[deps.get_current_principal] = principal_spy
    sec.principal_calls = calls
    return sec


# --- allowed origins: a preflight is granted, outside the gate ------------------------------------------------


@pytest.mark.parametrize("origin", ALLOWED)
def test_PROD_WIRE_4_a_preflight_from_each_hosting_origin_is_granted_with_vary_origin(deployed, origin):
    response = preflight(deployed.client, "/worlds", origin, "GET", "authorization")

    assert response.status_code in (200, 204), response.text
    assert response.headers.get("access-control-allow-origin") == origin
    assert "origin" in tokens(response, "vary"), "`Vary: Origin` is on every answer to an allowed origin"
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(("method", "path", "asked"), GATED, ids=[f"{m} {p}" for m, p, _ in GATED])
def test_PROD_WIRE_4_a_preflight_to_a_gated_route_is_answered_before_the_gate_and_calls_nothing(
    deployed, method, path, asked
):
    deployed.sign_out()  # had the gate run, it would answer 401: the preflight must never reach it
    for origin in ALLOWED:
        response = preflight(deployed.client, path, origin, method, asked)

        assert response.status_code in (200, 204), f"{origin} {method} {path}: {response.status_code} {response.text}"
        assert response.headers.get("access-control-allow-origin") == origin
        assert method.lower() in {m.lower() for m in tokens(response, "access-control-allow-methods")}
    assert deployed.principal_calls == [], "a preflight must not resolve the principal"
    assert deployed.access.reads == [] and deployed.access.writes == [], "a preflight must not touch the access store"


# --- disallowed origins ---------------------------------------------------------------------------------------


def test_PROD_WIRE_4_no_other_origin_is_ever_granted_a_preflight_or_an_answer(deployed):
    for origin in ALLOWED:  # anchor: the allowlist exists, so "nothing else is granted" is not vacuous
        assert (
            deployed.client.get("/health", headers={"Origin": origin}).headers.get("access-control-allow-origin")
            == origin
        )
    granted: list[str] = []
    for origin in NEVER_ALLOWED:
        pre = preflight(deployed.client, "/worlds", origin, "GET", "authorization")
        plain = deployed.client.get("/health", headers={"Origin": origin})
        gated = deployed.client.get("/worlds", headers={"Origin": origin})  # the gate's 403: still no grant
        for response in (pre, plain, gated):
            if (
                "access-control-allow-origin" in response.headers
                or "access-control-allow-credentials" in response.headers
            ):
                granted.append(f"{origin!r} -> {response.status_code} {dict(response.headers)}")
    assert not granted, "an origin that is not one of the two hosting origins was granted:\n" + "\n".join(granted)


def test_PROD_WIRE_4_credentials_are_never_allowed_for_any_origin_or_request(deployed):
    assert (
        deployed.client.get("/health", headers={"Origin": WEB_APP}).headers.get("access-control-allow-origin")
        == WEB_APP
    )
    for origin in (*ALLOWED, *NEVER_ALLOWED):
        for response in (
            preflight(deployed.client, "/worlds", origin, "GET", "authorization"),
            deployed.client.get("/health", headers={"Origin": origin}),
            deployed.client.get("/worlds", headers={"Origin": origin}),
        ):
            assert "access-control-allow-credentials" not in response.headers, origin


# --- request headers ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("header", REQUEST_HEADERS)
def test_PROD_WIRE_4_each_required_request_header_is_granted_in_a_preflight(deployed, header):
    response = preflight(deployed.client, "/intake", WEB_APP, "POST", header)

    assert response.status_code in (200, 204), response.text
    assert header in tokens(response, "access-control-allow-headers")


def test_PROD_WIRE_4_the_allowed_header_list_is_exactly_the_required_headers_and_safelisted_extras(deployed):
    response = preflight(deployed.client, "/intake", WEB_APP, "POST", ",".join(REQUEST_HEADERS))

    listed = tokens(response, "access-control-allow-headers")
    assert set(REQUEST_HEADERS) <= listed
    assert listed <= set(REQUEST_HEADERS) | SAFELISTED_EXTRAS, f"headers granted beyond the required set: {listed}"
    assert "*" not in listed


@pytest.mark.parametrize("asked", ["x-evil", "authorization, x-evil", "x-idempotency-key", "cookie"])
def test_PROD_WIRE_4_a_preflight_asking_for_another_header_gets_no_grant_for_it(deployed, asked):
    anchor = preflight(deployed.client, "/intake", WEB_APP, "POST", "authorization")
    assert "authorization" in tokens(anchor, "access-control-allow-headers"), "anchor: the required headers are granted"
    response = preflight(deployed.client, "/intake", WEB_APP, "POST", asked)

    granted = tokens(response, "access-control-allow-headers")
    for name in (t.strip() for t in asked.split(",")):
        if name not in REQUEST_HEADERS:
            assert name not in granted, f"{name} was granted: {dict(response.headers)}"


# --- methods --------------------------------------------------------------------------------------------------


def test_PROD_WIRE_4_the_allowed_methods_are_the_ones_the_routers_use_plus_options(deployed):
    served = {m for m, _ in route_table(app)}
    assert served == ROUTER_METHODS, f"a router now serves {served ^ ROUTER_METHODS}: decide its CORS method here"

    response = preflight(deployed.client, "/worlds", WEB_APP, "GET", "authorization")
    listed = {m.upper() for m in tokens(response, "access-control-allow-methods")}

    assert ROUTER_METHODS | {"OPTIONS"} <= listed
    assert listed <= ROUTER_METHODS | {"OPTIONS", "HEAD"}, f"methods granted beyond the routers': {listed}"


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "PROPFIND"])
def test_PROD_WIRE_4_a_method_no_router_serves_is_not_granted(deployed, method):
    anchor = preflight(deployed.client, "/worlds", WEB_APP, "GET", "authorization")
    assert "get" in tokens(anchor, "access-control-allow-methods"), "anchor: the router methods are granted"
    response = preflight(deployed.client, "/worlds", WEB_APP, method, "authorization")

    assert method not in {m.upper() for m in tokens(response, "access-control-allow-methods")}


# --- the gate's own refusals still carry the headers ----------------------------------------------------------


def test_PROD_WIRE_4_a_signed_in_person_with_no_declaration_is_answered_with_the_cors_headers(deployed):
    """OPEN-ACCESS (16 Oct 2026): the gate no longer refuses a person for lacking a declaration."""
    response = deployed.client.get("/worlds", headers={"Origin": WEB_APP})

    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == WEB_APP
    assert "origin" in tokens(response, "vary")
    assert "access-control-allow-credentials" not in response.headers


def test_PROD_WIRE_4_a_signed_out_401_from_the_gate_carries_the_cors_headers(deployed):
    deployed.sign_out()

    response = deployed.client.get("/worlds", headers={"Origin": FIREBASE_APP})

    assert response.status_code == 401
    assert response.headers.get("access-control-allow-origin") == FIREBASE_APP
    assert "origin" in tokens(response, "vary")


def test_PROD_WIRE_4_an_unwired_access_store_no_longer_closes_the_gate(deployed):
    deployed.as_user(JUDGE)
    del app.dependency_overrides[deps.get_access_store]  # OPEN-ACCESS: the gate never reads it

    response = deployed.client.get("/worlds", headers={"Origin": WEB_APP})

    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == WEB_APP


def test_PROD_WIRE_4_a_gate_refusal_on_a_v1_route_has_both_the_cors_headers_and_no_store(deployed):
    deployed.sign_out()
    response = deployed.client.get("/v1/plate", headers={"Origin": WEB_APP})

    assert response.status_code == 401
    assert response.headers.get("access-control-allow-origin") == WEB_APP
    assert response.headers.get("cache-control") == "no-store"


def test_PROD_WIRE_4_a_public_route_answer_to_an_allowed_origin_carries_the_headers(deployed):
    response = deployed.client.get("/health", headers={"Origin": WEB_APP})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == WEB_APP
    assert "origin" in tokens(response, "vary")


def test_PROD_WIRE_4_retry_after_is_exposed_for_browser_rate_limit_recovery(deployed):
    # 11 Oct policy: the browser needs the existing rate-limit response header.
    for response in (
        deployed.client.get("/health", headers={"Origin": WEB_APP}),
        deployed.client.get("/worlds", headers={"Origin": WEB_APP}),
        preflight(deployed.client, "/worlds", WEB_APP, "GET", "authorization"),
    ):
        assert response.headers.get("access-control-allow-origin") == WEB_APP, "anchor: CORS is on"
        assert "retry-after" in tokens(response, "access-control-expose-headers")


# --- not deployed ---------------------------------------------------------------------------------------------


def test_PROD_WIRE_4_not_deployed_the_production_cors_adds_nothing(sec15_factory):
    sec = sec15_factory(declarations={VISITOR: "visitor"}, deployed=False)  # no K_SERVICE, no CLOUD_RUN_JOB

    for origin in ALLOWED:
        pre = preflight(sec.client, "/worlds", origin, "GET", "authorization")
        plain = sec.client.get("/health", headers={"Origin": origin})
        for response in (pre, plain):
            assert not [h for h in response.headers if h.lower().startswith("access-control-")], dict(response.headers)


def test_PROD_WIRE_4_deployed_is_read_on_every_request_not_once_at_import(sec15_factory, monkeypatch):
    sec = sec15_factory(declarations={VISITOR: "visitor"}, deployed=False)
    assert "access-control-allow-origin" not in sec.client.get("/health", headers={"Origin": WEB_APP}).headers

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    assert sec.client.get("/health", headers={"Origin": WEB_APP}).headers.get("access-control-allow-origin") == WEB_APP

    monkeypatch.delenv("K_SERVICE")
    assert "access-control-allow-origin" not in sec.client.get("/health", headers={"Origin": WEB_APP}).headers


def test_PROD_WIRE_4_dev_mode_not_deployed_grants_the_dev_origin_and_not_the_production_one():
    """A fresh interpreter: dev mode installs once at import of `tilo_api` (TILO_API_DEV=1, no K_SERVICE), so the
    in-process app of this suite cannot show it. Loopback Host, as dev mode demands."""
    code = f"""
import os
os.environ.pop("K_SERVICE", None)
os.environ.pop("CLOUD_RUN_JOB", None)
os.environ["TILO_API_DEV"] = "1"
os.environ["TILO_DEV_UNIT_DELAY_S"] = "0"
os.environ.setdefault("TILO_MODELS_FILE", {str(REPO_ROOT / "config" / "models.dev.yaml")!r})
from fastapi.testclient import TestClient
from tilo_api import app

client = TestClient(app, base_url="http://localhost:8080")
seen = {{}}
for origin in ("http://localhost:5173", {WEB_APP!r}, {FIREBASE_APP!r}):
    plain = client.get("/health", headers={{"Origin": origin}})
    pre = client.options("/worlds", headers={{"Origin": origin, "Access-Control-Request-Method": "GET"}})
    seen[origin] = (plain.headers.get("access-control-allow-origin"), pre.headers.get("access-control-allow-origin"))
assert seen["http://localhost:5173"] == ("http://localhost:5173", "http://localhost:5173"), seen
assert seen[{WEB_APP!r}] == (None, None), seen
assert seen[{FIREBASE_APP!r}] == (None, None), seen
print("DEV-OK")
"""
    env = {k: v for k, v in os.environ.items() if k not in {"K_SERVICE", "CLOUD_RUN_JOB"}}
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=REPO_ROOT, env=env
    )
    assert proc.returncode == 0 and "DEV-OK" in proc.stdout, proc.stdout + proc.stderr


# --- SEC-10 App Check enforced: still outside it --------------------------------------------------------------


class _RefusingVerifier:
    def verify(self, token: str) -> dict[str, str]:
        from tilo_api.appcheck import TokenRefused

        raise TokenRefused("invalid")


def test_PROD_WIRE_4_with_app_check_enforced_a_preflight_is_granted_and_its_401_carries_cors_for_our_origins(
    deployed, monkeypatch
):
    monkeypatch.setenv("TILO_APPCHECK_ENFORCE", "1")
    app.dependency_overrides[deps.get_app_check_verifier] = lambda: _RefusingVerifier()
    try:
        granted = preflight(deployed.client, "/worlds", WEB_APP)
        assert granted.status_code in (200, 204) and granted.headers.get("access-control-allow-origin") == WEB_APP

        for origin in (WEB_APP, FIREBASE_APP):
            refused = deployed.client.get("/worlds", headers={"Origin": origin, "X-Firebase-AppCheck": "bad"})
            assert refused.status_code == 401, refused.text
            assert refused.headers.get("access-control-allow-origin") == origin
            assert "access-control-allow-credentials" not in refused.headers
        stranger = deployed.client.get(
            "/worlds", headers={"Origin": "https://evil.example", "X-Firebase-AppCheck": "bad"}
        )
        assert stranger.status_code == 401 and "access-control-allow-origin" not in stranger.headers
    finally:
        app.dependency_overrides.pop(deps.get_app_check_verifier, None)
