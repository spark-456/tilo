"""Exercise the deployed command over a local HTTP server; no cloud or sign-in."""

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("hosted_smoke_dev", SCRIPTS / "smoke_dev.py")
assert spec and spec.loader
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
API = "https://tilo-api-fake-as.a.run.app"
CONFIG = {
    "api_store": "firestore",
    "artifacts_store": "gcs",
    "archive_store": "gcs",
    "skills_store": "firestore",
    "firestore_project_configured": True,
    "artifacts_bucket_configured": True,
    "archive_bucket_configured": True,
    "live_mode": True,
}


@pytest.fixture
def fake_server():
    state = {"config": dict(CONFIG), "deps_status": 200, "requests": [], "bundle_api": API, "google": True}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self):
            state["requests"].append((self.command, self.path, dict(self.headers)))
            headers = {}
            status = 200
            body = "{}"
            if self.path == "/":
                body = '<script src="/assets/main.js"></script>'
            elif self.path == "/assets/main.js":
                body = json.dumps(state["bundle_api"]) + ('; "Continue with Google"' if state["google"] else "")
            elif self.path == "/healthz/deps":
                status, body = state["deps_status"], json.dumps(state["config"])
            elif self.path == "/v1/plate":
                status = 401
            elif self.path == "/intake" and self.command == "OPTIONS":
                headers = {
                    "Access-Control-Allow-Origin": smoke.WEB_ORIGIN,
                    "Access-Control-Allow-Methods": "POST",
                    "Access-Control-Allow-Headers": "authorization,content-type,x-tilo-channel",
                }
            elif self.path != "/healthz":
                status = 404
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body.encode())

        do_GET = respond
        do_OPTIONS = respond

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    transports = []

    class LocalTransport(httpx.BaseTransport):
        def __init__(self):
            # Every request is rewritten to plaintext loopback; no TLS certificates are used.
            self.inner = httpx.HTTPTransport(verify=False)
            transports.append(self.inner)

        def handle_request(self, request):
            url = request.url.copy_with(scheme="http", host="127.0.0.1", port=server.server_port)
            return self.inner.handle_request(httpx.Request(request.method, url, headers=request.headers))

        def close(self):
            pass  # Both sequential smoke clients share this injected transport.

    try:
        yield state, LocalTransport
    finally:
        for inner in transports:
            inner.close()
        server.shutdown()
        thread.join()
        server.server_close()


def test_configured_http_is_not_demo_acceptance(fake_server, capsys, monkeypatch):
    state, transport = fake_server
    monkeypatch.setenv(smoke.TOKEN_ENV, "must.never.send")
    assert smoke.hosted_main([API], transport=transport()) == 0
    output = capsys.readouterr().out
    assert "PASS dependency-configuration" in output
    assert "SKIP demo: Home and recorded world require the existing playwright.hosted.config.ts hosted smoke" in output
    assert "PASS hosted-http (signed-out HTTP checks only; demo unverified)" in output
    assert {"/", "/assets/main.js", "/healthz", "/healthz/deps"} <= {path for _, path, _ in state["requests"]}
    assert all(method in ("GET", "OPTIONS") for method, _, _ in state["requests"])
    assert all("Authorization" not in headers and "Cookie" not in headers for _, _, headers in state["requests"])


@pytest.mark.parametrize("key", list(CONFIG))
def test_missing_dependency_fails_with_plain_reason(fake_server, capsys, key):
    state, transport = fake_server
    del state["config"][key]
    assert smoke.hosted_main([API], transport=transport()) == 1
    assert f"{key} does not report" in capsys.readouterr().out


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_live_flag_requires_boolean_true(fake_server, capsys, value):
    state, transport = fake_server
    state["config"]["live_mode"] = value
    assert smoke.hosted_main([API], transport=transport()) == 1
    assert "live_mode does not report" in capsys.readouterr().out


@pytest.mark.parametrize("status", [302, 404, 503])
def test_dependency_http_failure(fake_server, capsys, status):
    state, transport = fake_server
    state["deps_status"] = status
    assert smoke.hosted_main([API], transport=transport()) == 1
    assert f"HTTP {status}, wanted 200" in capsys.readouterr().out


@pytest.mark.parametrize("field,value", [("bundle_api", "https://wrong.example"), ("google", False)])
def test_hosting_failure_stops_before_dependency_checks(fake_server, capsys, field, value):
    state, transport = fake_server
    state[field] = value
    assert smoke.hosted_main([API], transport=transport()) == 1
    assert "FAIL hosted:" in capsys.readouterr().out
    assert not any(path == "/healthz/deps" for _, path, _ in state["requests"])
