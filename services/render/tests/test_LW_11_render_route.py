"""LW-11: POST /render on tilo-render with service-to-service auth, hard size/time/concurrency limits, and parity."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tilo_render.pdf import render_pdf
from tilo_render.spec import MAX_SECTIONS, MAX_TABLE_ROWS, DeliverableSpec

AUDIENCE = "https://tilo-render.run.app"
CALLER = "tilo-harness@tilo-dev.iam.gserviceaccount.com"
TOKEN = "-".join(("valid", "harness", "oidc"))
AUTH = {"Authorization": f"Bearer {TOKEN}"}
JSON_AUTH = {**AUTH, "Content-Type": "application/json"}
SAMPLE_SPEC: dict[str, Any] = {
    "title": "Quarterly Market Brief",
    "subtitle": "Asia-Pacific",
    "date": "2026-10-09",
    "tables": [{"id": "t1", "columns": ["Region", "Revenue"], "rows": [["APAC", 120], ["EMEA", 95]]}],
    "charts": [{"id": "c1", "kind": "bar", "table_id": "t1", "x": "Region", "y": "Revenue", "title": "By Region"}],
    "sections": [
        {
            "heading": "Executive Summary",
            "blocks": [
                {"type": "paragraph", "text": "Demand remained resilient across segments."},
                {"type": "bullets", "bullets": ["APAC grew 14%", "Operating margin expanded"]},
                {"type": "table", "table_id": "t1"},
                {"type": "chart", "chart_id": "c1"},
            ],
        }
    ],
}
REQ_PDF = {"format": "pdf", "spec": SAMPLE_SPEC}


def _verifier(token: str, audience: str) -> Mapping[str, Any]:
    if token != TOKEN:
        raise ValueError("bad token")
    return {"iss": "https://accounts.google.com", "aud": audience, "email": CALLER, "email_verified": True}


def _make_app(**kwargs: Any) -> Any:
    from tilo_render.app import create_app

    return create_app(**{"oidc_verifier": _verifier, "audience": AUDIENCE, "allowed_callers": (CALLER,), **kwargs})


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer   "}, {"Authorization": "Bearer a b"}]
)
def test_LW_11_auth_rejects_missing_or_malformed_authorization_with_401(headers: dict[str, str]) -> None:
    resp = TestClient(_make_app()).post("/render", json=REQ_PDF, headers=headers)
    assert resp.status_code == 401 and resp.headers.get("www-authenticate") == "Bearer"
    assert resp.json()["reason"] == "unauthorized"


@pytest.mark.parametrize("kwargs", [{"oidc_verifier": None}, {"audience": ""}, {"allowed_callers": ()}])
def test_LW_11_unconfigured_app_fails_closed_with_403(kwargs: dict[str, Any]) -> None:
    resp = TestClient(_make_app(**kwargs)).post("/render", json=REQ_PDF, headers=AUTH)
    assert resp.status_code == 403 and resp.json()["reason"] == "forbidden"


def test_LW_11_verifier_exception_returns_401_without_leaking_error() -> None:
    canary = "SECRET_VERIFIER_TRACE_881"

    def boom(_t: str, _a: str) -> Mapping[str, Any]:
        raise RuntimeError(canary)

    resp = TestClient(_make_app(oidc_verifier=boom)).post("/render", json=REQ_PDF, headers=AUTH)
    assert resp.status_code == 401 and canary not in resp.text


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": "other@tilo.test", "email_verified": True},
        {"iss": "https://accounts.google.com", "aud": "https://wrong.example", "email": CALLER, "email_verified": True},
        {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": CALLER, "email_verified": False},
        {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": CALLER, "email_verified": "true"},
        {"iss": "https://evil.example.com", "aud": AUDIENCE, "email": CALLER, "email_verified": True},
    ],
)
def test_LW_11_wrong_caller_audience_unverified_email_or_foreign_issuer_returns_403(claims: dict[str, Any]) -> None:
    resp = TestClient(_make_app(oidc_verifier=lambda _t, _a: claims)).post("/render", json=REQ_PDF, headers=AUTH)
    assert resp.status_code == 403 and resp.json()["reason"] == "forbidden"


def test_LW_11_no_body_is_read_before_auth_passes() -> None:
    app, body_reads = _make_app(), 0

    async def tracked_app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal body_reads

        async def counting_receive() -> Any:
            nonlocal body_reads
            body_reads += 1
            return await receive()

        await app(scope, counting_receive, send)

    client = TestClient(tracked_app)
    r_unauth = client.post("/render", content=b"{not-valid-json", headers={"Content-Type": "application/json"})
    assert r_unauth.status_code == 401 and body_reads == 0
    r_authed = client.post("/render", content=b"{not-valid-json", headers=JSON_AUTH)
    assert r_authed.status_code == 422 and body_reads > 0


def test_LW_11_valid_pdf_and_pptx_are_deterministic_with_hardened_headers_and_in_process_parity() -> None:
    client = TestClient(_make_app())
    r1 = client.post("/render", json=REQ_PDF, headers=AUTH)
    r2 = client.post("/render", json=REQ_PDF, headers=AUTH)
    assert r1.status_code == 200 and r2.status_code == 200 and r1.content.startswith(b"%PDF-")
    assert r1.content == r2.content == render_pdf(DeliverableSpec.model_validate(SAMPLE_SPEC))
    assert r1.headers["content-type"] == "application/pdf" and "attachment" in r1.headers["content-disposition"]
    assert r1.headers["x-content-type-options"] == "nosniff" and r1.headers["cache-control"] == "no-store"

    p1 = client.post("/render", json={"format": "pptx", "spec": SAMPLE_SPEC}, headers=AUTH)
    assert p1.status_code == 200 and p1.content.startswith(b"PK\x03\x04")
    assert p1.headers["content-type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert "attachment" in p1.headers["content-disposition"]
    assert p1.headers["x-content-type-options"] == "nosniff" and p1.headers["cache-control"] == "no-store"


def test_LW_11_wrong_content_type_returns_415() -> None:
    resp = TestClient(_make_app()).post("/render", content=b"{}", headers={**AUTH, "Content-Type": "text/plain"})
    assert resp.status_code == 415 and resp.json()["reason"] == "unsupported_media_type"


@pytest.mark.parametrize(
    "raw_body",
    [
        b'{"format":"pdf","spec":{"title":"CANARY_99","date":"not-a-date"}}',
        b'{"format":"pdf","spec":{"title":"CANARY_99","date":"2026-10-09"},"extra_field":"CANARY_99"}',
        b'{"format":"pdf","format":"pptx","spec":{"title":"CANARY_99","date":"2026-10-09"}}',
        b'{"format":"pdf","spec":{"title":"CANARY_99","date":"2026-10-09","tables":[{"id":"t","columns":["a"],"rows":[[NaN]]}]}}',
        b"not json at all CANARY_99",
    ],
)
def test_LW_11_invalid_spec_returns_422_with_fixed_code_and_never_echoes_input(
    raw_body: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        resp = TestClient(_make_app()).post("/render", content=raw_body, headers=JSON_AUTH)
    assert resp.status_code == 422 and resp.json() == {"error": "invalid_spec", "reason": "invalid_spec"}
    assert "CANARY_99" not in resp.text and "CANARY_99" not in caplog.text


def test_LW_11_body_over_cap_rejected_with_413_on_content_length_and_chunked_stream() -> None:
    app = _make_app(max_body_bytes=256)
    big = b'{"format":"pdf","spec":{"title":"' + b"x" * 400 + b'","date":"2026-10-09"}}'
    r_cl = TestClient(app).post("/render", content=big, headers=JSON_AUTH)
    assert r_cl.status_code == 413 and r_cl.json()["reason"] == "too_large"

    async def send_chunked() -> httpx.Response:
        async def chunks():
            for _ in range(10):
                yield b"a" * 50

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://render.test") as ac:
            return await ac.post("/render", content=chunks(), headers=JSON_AUTH)

    r_stream = asyncio.run(send_chunked())
    assert r_stream.status_code == 413 and r_stream.json()["reason"] == "too_large"


def test_LW_11_oversized_output_and_renderer_exception_return_fixed_refusals_without_leaking() -> None:
    r_big = TestClient(_make_app(renderer=lambda _s, _f: b"%PDF-1.4\n" + b"0" * 500, max_output_bytes=100)).post(
        "/render", json=REQ_PDF, headers=AUTH
    )
    assert r_big.status_code == 413 and r_big.json()["reason"] == "output_too_large"

    def bad_renderer(_s: Any, _f: str) -> bytes:
        raise RuntimeError("/app/templates/secret_path_leak")

    r_err = TestClient(_make_app(renderer=bad_renderer)).post("/render", json=REQ_PDF, headers=AUTH)
    assert r_err.status_code == 502 and r_err.json() == {"error": "render_failed", "reason": "render_failed"}
    assert "secret_path_leak" not in r_err.text


def test_LW_11_max_sections_and_table_rows_render_under_time_cap() -> None:
    tbl_blk, para_blk = [{"type": "table", "table_id": "t1"}], [{"type": "paragraph", "text": "ok"}]
    max_spec = {
        "title": "Max Spec",
        "date": "2026-10-09",
        "tables": [{"id": "t1", "columns": ["Idx", "Val"], "rows": [[f"R{i}", i] for i in range(MAX_TABLE_ROWS)]}],
        "sections": [{"heading": f"S{i}", "blocks": tbl_blk if i == 0 else para_blk} for i in range(MAX_SECTIONS)],
    }
    t0 = time.monotonic()
    resp = TestClient(_make_app()).post("/render", json={"format": "pdf", "spec": max_spec}, headers=AUTH)
    assert resp.status_code == 200 and time.monotonic() - t0 < 10.0 and resp.content.startswith(b"%PDF-")


def test_LW_11_health_answers_fast_during_slow_render_and_concurrency_cap_returns_429_then_releases() -> None:
    entered, release = threading.Event(), threading.Event()

    def slow_renderer(_spec: DeliverableSpec, _fmt: str) -> bytes:
        entered.set()
        release.wait(timeout=3.0)
        return b"%PDF-1.4\n%%EOF\n"

    app = _make_app(renderer=slow_renderer, max_concurrency=1)

    async def scenario() -> tuple[float, int, int, int]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://render.test") as ac:
            first = asyncio.create_task(ac.post("/render", json=REQ_PDF, headers=AUTH))
            await asyncio.to_thread(entered.wait, 2.0)
            t0 = time.perf_counter()
            assert (await ac.get("/health")).status_code == 200
            health_elapsed = time.perf_counter() - t0
            busy_resp = await ac.post("/render", json=REQ_PDF, headers=AUTH)
            release.set()
            r1 = await first
            r_after = await ac.post("/render", json=REQ_PDF, headers=AUTH)
            return health_elapsed, busy_resp.status_code, r1.status_code, r_after.status_code

    health_elapsed, busy_code, r1_code, after_code = asyncio.run(scenario())
    assert health_elapsed < 0.2 and (busy_code, r1_code, after_code) == (429, 200, 200)

    to_app = _make_app(
        renderer=lambda _s, _f: (time.sleep(0.4), b"%PDF-1.4\n")[1], render_timeout=0.05, max_concurrency=1
    )
    r_to = TestClient(to_app).post("/render", json=REQ_PDF, headers=AUTH)
    assert r_to.status_code == 504 and r_to.json()["reason"] == "timeout"
