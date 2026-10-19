"""ASGI entry point for Cloud Run (`tilo-browser`, P0-07a, LW-08).

The image runs `uvicorn tilo_browser.app:app`. `POST /fetch` is service-to-service only:
it verifies a Bearer token before parsing the request and fails closed (401 without a
Bearer token, 403 when unconfigured or for an unauthorized caller).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tilo_logging import configure_logging

from tilo_browser.egress import EgressBlocked
from tilo_browser.fetch import FetchBlocked, FetchService, service_caller_ok
from tilo_browser.login import CredentialEntryRefused
from tilo_browser.playwright_engine import PlaywrightEngine
from tilo_browser.session import BrowserSessions, SessionRefused
from tilo_browser.worker import ScreenshotRefused

configure_logging()
_BROWSER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tilo-browser")

_STATUS_BY_REASON: dict[str, int] = {
    "file_too_large": 413,
    "html_too_large": 413,
    "unit_file_limit": 413,
    "unit_byte_limit": 413,
    "archive_refused": 415,
    "executable_refused": 415,
    "unsupported_media_type": 415,
    "timeout": 504,
    "upstream_error": 502,
}


class FetchRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=8192)
    allow_hosts: list[str] = Field(default_factory=list)
    task_allowlist: list[str] = Field(default_factory=list)
    org_id: str = "org_local"
    run_id: str = "r_local"
    unit_id: str = "U1"


class SessionStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: str = Field(pattern=r"^bs_[0-7][0-9A-HJKMNP-TV-Z]{25}$")
    world_id: str
    run_id: str
    unit_id: str
    allow_hosts: list[str] = Field(min_length=1, max_length=20)
    start_url: str = Field(pattern=r"^https://", max_length=2048)
    viewport: dict[str, int]


class SessionActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: str
    step: int = Field(ge=1, le=60)
    action: dict[str, Any]
    digest: str | None
    outbox_id: str | None


class SessionInspectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: str
    at: dict[str, int]


def _refuse(status: int, message: str, *, reason: str | None = None, url: str | None = None) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    payload: dict[str, Any] = {"error": message}
    if reason is not None:
        payload["reason"] = reason
    if url is not None:
        payload["url"] = url
    return JSONResponse(payload, status_code=status, headers=headers)


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token and not any(c.isspace() for c in token) else None


def create_app(
    *,
    fetch_service: FetchService | None = None,
    oidc_verifier: Callable[[str, str], Mapping[str, Any]] | None = None,
    audience: str | None = None,
    allowed_callers: Sequence[str] = (),
    browser_engine: Any | None = None,
) -> FastAPI:
    # No generated docs: the service may be public, and the route list is not for strangers (issue #411).
    fastapi_app = FastAPI(title="tilo-browser", docs_url=None, redoc_url=None, openapi_url=None)
    service = fetch_service if fetch_service is not None else FetchService()
    callers = tuple(allowed_callers)
    sessions = BrowserSessions(browser_engine or PlaywrightEngine())

    async def browser_call(fn: Callable[..., Any], *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(_BROWSER_EXECUTOR, partial(fn, *args))

    async def authenticated(request: Request) -> JSONResponse | None:
        token = _bearer_token(request)
        if token is None:
            return _refuse(401, "unauthorized")
        if oidc_verifier is None or not audience or not callers:
            return _refuse(403, "forbidden")
        try:
            claims = await run_in_threadpool(oidc_verifier, token, audience)
        except Exception:
            return _refuse(401, "unauthorized")
        if not service_caller_ok(claims, audience=audience, allowed_callers=callers):
            return _refuse(403, "forbidden")
        return None

    @fastapi_app.post("/sessions")
    async def start_session(request: Request) -> JSONResponse:
        refused = await authenticated(request)
        if refused is not None:
            return refused
        try:
            body = SessionStartPayload.model_validate(await request.json()).model_dump()
            result = await browser_call(sessions.start, body)
        except (ValueError, ValidationError, KeyError, TypeError):
            return _refuse(422, "invalid_request")
        except SessionRefused as exc:
            return _refuse(exc.status, exc.reason, reason=exc.reason)
        except EgressBlocked:
            return _refuse(403, "offsite_host", reason="offsite_host")
        except ScreenshotRefused:
            return _refuse(409, "screenshot_unavailable", reason="screenshot_unavailable")
        except Exception:
            return _refuse(503, "browser_unavailable", reason="browser_unavailable")
        return JSONResponse(result)

    @fastapi_app.post("/sessions/{session}/act")
    async def act_session(session: str, request: Request) -> JSONResponse:
        refused = await authenticated(request)
        if refused is not None:
            return refused
        try:
            body = SessionActionPayload.model_validate(await request.json()).model_dump()
            if body["session"] != session or body["outbox_id"] is not None:
                return _refuse(422, "invalid_request")
            result = await browser_call(sessions.act, session, body)
        except (ValueError, ValidationError, KeyError, TypeError):
            return _refuse(422, "invalid_request")
        except SessionRefused as exc:
            return _refuse(exc.status, exc.reason, reason=exc.reason)
        except EgressBlocked:
            return _refuse(403, "offsite_host", reason="offsite_host")
        except CredentialEntryRefused:
            return _refuse(409, "secure_field", reason="secure_field")
        except ScreenshotRefused:
            return _refuse(409, "screenshot_unavailable", reason="screenshot_unavailable")
        except Exception:
            return _refuse(503, "browser_unavailable", reason="browser_unavailable")
        return JSONResponse(result)

    @fastapi_app.post("/sessions/{session}/inspect")
    async def inspect_session(session: str, request: Request) -> JSONResponse:
        refused = await authenticated(request)
        if refused is not None:
            return refused
        try:
            body = SessionInspectPayload.model_validate(await request.json()).model_dump()
            if body["session"] != session:
                return _refuse(422, "invalid_request")
            result = await browser_call(sessions.inspect, session, body["at"])
        except (ValueError, ValidationError, KeyError, TypeError):
            return _refuse(422, "invalid_request")
        except SessionRefused as exc:
            return _refuse(exc.status, exc.reason, reason=exc.reason)
        return JSONResponse(result)

    @fastapi_app.delete("/sessions/{session}")
    async def end_session(session: str, request: Request) -> JSONResponse:
        refused = await authenticated(request)
        if refused is not None:
            return refused
        try:
            result = await browser_call(sessions.end, session)
        except SessionRefused as exc:
            return _refuse(exc.status, exc.reason, reason=exc.reason)
        except ScreenshotRefused:
            return _refuse(409, "screenshot_unavailable", reason="screenshot_unavailable")
        return JSONResponse(result)

    @fastapi_app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
    @fastapi_app.get("/healthz")
    async def healthz() -> dict[str, str]:  # async: runs on the loop, not in the thread pool fetches use
        return {"status": "ok"}

    @fastapi_app.post("/fetch")
    async def fetch_endpoint(request: Request) -> JSONResponse:
        token = _bearer_token(request)
        if token is None:
            return _refuse(401, "unauthorized")
        if oidc_verifier is None or not audience or not callers:
            return _refuse(403, "forbidden")
        try:
            claims = await run_in_threadpool(oidc_verifier, token, audience)
        except Exception:
            return _refuse(401, "unauthorized")
        if not service_caller_ok(claims, audience=audience, allowed_callers=callers):
            return _refuse(403, "forbidden")

        try:
            raw_json = await request.json()
            req_data = FetchRequestPayload.model_validate(raw_json)
        except (ValueError, ValidationError):
            return _refuse(422, "invalid_request", reason="invalid_request")

        combined_allow = [*req_data.allow_hosts, *req_data.task_allowlist]
        try:
            # Blocking work (DNS, sockets, HTML parsing) runs on a worker thread so /health and other
            # requests keep answering while a fetch is in flight.
            result = await run_in_threadpool(
                service.fetch,
                req_data.url,
                allow_hosts=combined_allow,
                org_id=req_data.org_id,
                run_id=req_data.run_id,
                unit_id=req_data.unit_id,
            )
        except FetchBlocked as exc:
            status = _STATUS_BY_REASON.get(exc.block.reason, 403)
            return _refuse(status, exc.block.reason, reason=exc.block.reason, url=exc.block.url)
        except ValueError:
            return _refuse(422, "invalid_request", reason="invalid_request")

        return JSONResponse(result.to_dict())

    return fastapi_app


app = create_app()
