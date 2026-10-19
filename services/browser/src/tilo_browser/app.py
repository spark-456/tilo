"""ASGI entry point for Cloud Run (`tilo-browser`, P0-07a, LW-08).

The image runs `uvicorn tilo_browser.app:app`. `POST /fetch` is service-to-service only:
it verifies a Bearer token before parsing the request and fails closed (401 without a
Bearer token, 403 when unconfigured or for an unauthorized caller).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tilo_logging import configure_logging

from tilo_browser.fetch import FetchBlocked, FetchService, service_caller_ok

configure_logging()

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
) -> FastAPI:
    # No generated docs: the service may be public, and the route list is not for strangers (issue #411).
    fastapi_app = FastAPI(title="tilo-browser", docs_url=None, redoc_url=None, openapi_url=None)
    service = fetch_service if fetch_service is not None else FetchService()
    callers = tuple(allowed_callers)

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
