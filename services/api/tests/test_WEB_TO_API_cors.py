"""WEB-TO-API: CORS for the deployed web app, only when the owner configures it (docs/deploy-dev.md, BQ-WEBAPI-1).

`TILO_API_CORS_ORIGINS` is a comma-separated list of exact https origins. Unset, empty or with any invalid entry
there is no CORS at all (never a wildcard, never credentials). The middleware is the outermost one, so a preflight
passes the access, App Check and sign-in gates without a token while a real request still needs a principal.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from tilo_api import app as real_app
from tilo_api import cors
from tilo_api.access import AccessGate
from tilo_api.appcheck import AppCheckGate

WEB = "https://essential-wares-510320-f0.web.app"
ALT = "https://essential-wares-510320-f0.firebaseapp.com"


def test_WEB_TO_API_parses_exact_https_origins() -> None:
    assert cors.cors_origins({cors.ENV: f"{WEB}, {ALT}"}) == [WEB, ALT]
    assert cors.cors_origins({cors.ENV: "https://example.test:8443"}) == ["https://example.test:8443"]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "*",
        "http://example.test",
        "https://example.test/",
        "https://example.test/path",
        "https://*.example.test",
        "https://example.test?x=1",
        "https://user@example.test",
        "null",
        "example.test",
        f"{WEB},*",
        f"{WEB},http://example.test",
        f"{WEB},,{ALT}",
    ],
)
def test_WEB_TO_API_any_invalid_entry_means_no_origins(raw: str) -> None:
    assert cors.cors_origins({cors.ENV: raw}) == []


def test_WEB_TO_API_unset_means_no_origins_and_no_middleware() -> None:
    assert cors.cors_origins({}) == []
    app = FastAPI()
    assert cors.install_cors(app, {}) is False
    assert not [m for m in app.user_middleware if m.cls is CORSMiddleware]


def _gated_app(env: dict[str, str]) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/thing")
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(AppCheckGate)
    app.add_middleware(AccessGate)
    cors.install_cors(app, env)  # last added = outermost
    return app


def test_WEB_TO_API_cors_is_the_outermost_middleware_and_never_wildcard_or_credentialed() -> None:
    app = _gated_app({cors.ENV: f"{WEB},{ALT}"})
    first = app.user_middleware[0]
    assert first.cls is CORSMiddleware
    assert first.kwargs["allow_origins"] == [WEB, ALT]
    from tilo_api import app as real_app

    used = {m.upper() for path in real_app.openapi()["paths"].values() for m in path}
    assert set(first.kwargs["allow_methods"]) == used | {"OPTIONS"}, "exactly the methods the API's routes use"
    assert {"PATCH", "DELETE"} <= used
    assert set(first.kwargs["allow_headers"]) == {
        "Content-Type",
        "Idempotency-Key",
        "X-Firebase-AppCheck",
        "Authorization",
        "X-Tilo-Channel",
    }
    assert first.kwargs["expose_headers"] == ["Retry-After"]
    assert not first.kwargs.get("allow_credentials")
    assert "*" not in str(first.kwargs)


def _preflight(client: TestClient, origin: str) -> object:
    return client.options(
        "/v1/thing",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-firebase-appcheck",
        },
    )


def test_WEB_TO_API_preflight_passes_the_gates_for_an_allowed_origin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "tilo-api")  # deployed: the access gate is enforcing
    client = TestClient(_gated_app({cors.ENV: WEB}))
    ok = _preflight(client, WEB)
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == WEB
    assert "access-control-allow-credentials" not in ok.headers
    other = _preflight(client, "https://evil.example")
    assert "access-control-allow-origin" not in other.headers
    assert other.status_code == 400


def test_WEB_TO_API_a_real_request_still_needs_a_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    client = TestClient(_gated_app({cors.ENV: WEB}))
    res = client.get("/v1/thing", headers={"Origin": WEB})
    assert res.status_code == 401
    assert res.headers["access-control-allow-origin"] == WEB  # the browser can read the refusal


def test_WEB_TO_API_the_real_app_adds_cors_only_when_configured() -> None:
    # The import-time wiring: with TILO_API_CORS_ORIGINS unset in the test run there is none, and the module wires
    # `install_cors` last in tilo_api/__init__.py (outermost).
    assert not [m for m in real_app.user_middleware if m.cls is CORSMiddleware]
    import inspect

    import tilo_api

    source = inspect.getsource(tilo_api)
    assert source.index("_cors.install_cors(app)") > source.index("app.add_middleware(_LogContext)")


def test_WEB_TO_API_a_phone_preflight_with_the_channel_header_is_allowed() -> None:
    client = TestClient(_gated_app({cors.ENV: WEB}))
    response = client.options(
        "/health",
        headers={
            "Origin": WEB,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-tilo-channel",
        },
    )
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == WEB


def test_WEB_TO_API_dev_mode_never_gets_the_second_cors_layer() -> None:
    app = FastAPI()
    assert cors.install_cors(app, {cors.ENV: WEB, "TILO_API_DEV": "1"}) is False
