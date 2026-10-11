"""ASGI entry point for Cloud Run (`tilo-render`, P0-07a, LW-11).

The image runs `uvicorn tilo_render.app:app`. `POST /render` is service-to-service only:
it verifies a Google OIDC Bearer token before reading the request body, fails closed (401
without a valid Bearer token, 403 when unconfigured or for an unauthorized caller), enforces
strict body/time/concurrency/output caps, and returns deterministic PDF or PPTX bytes without
ever echoing untrusted spec text or internal paths in errors or logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from tilo_render.pdf import render_pdf
from tilo_render.pptx import render_pptx
from tilo_render.spec import DeliverableSpec

try:
    from tilo_logging import configure_logging

    configure_logging()
except ImportError:
    pass

log = logging.getLogger("tilo_render")
MAX_BODY_BYTES = 1024 * 1024  # 1 MiB request payload cap before JSON parsing
MAX_OUTPUT_BYTES = 20 * 1024 * 1024  # 20 MiB rendered file cap (matches tilo_harness.outputs.MAX_PDF)
DEFAULT_RENDER_TIMEOUT = 15.0
DEFAULT_MAX_CONCURRENCY = 2
_CONTENT_LENGTH_RE = re.compile(r"^[0-9]+$")
_MIME_BY_FORMAT: dict[str, tuple[str, str, bytes]] = {
    "pdf": ("application/pdf", 'attachment; filename="deliverable.pdf"', b"%PDF-"),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        'attachment; filename="deliverable.pptx"',
        b"PK\x03\x04",
    ),
}


class RenderRequestPayload(BaseModel):
    """Strict request contract for `POST /render` (`manifest` is omitted: provenance is attached by `tilo-harness`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["pdf", "pptx"]
    spec: DeliverableSpec


def service_caller_ok(claims: Mapping[str, Any], *, audience: str, allowed_callers: Sequence[str]) -> bool:
    """Verify Google OIDC claims for a service-to-service caller (e.g. `tilo-harness`)."""
    return (
        bool(audience)
        and bool(allowed_callers)
        and claims.get("iss") in ("https://accounts.google.com", "accounts.google.com")
        and claims.get("aud") == audience
        and claims.get("email_verified") is True
        and isinstance(email := claims.get("email"), str)
        and bool(email)
        and email in set(allowed_callers)
    )


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token and not any(c.isspace() for c in token) else None


def _refuse(status: int, reason: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse({"error": reason, "reason": reason}, status_code=status, headers=headers)


def _no_dup_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError("duplicate key")
    return dict(pairs)


def _no_nan_inf(_name: str) -> Any:
    raise ValueError("NaN and Infinity are not JSON")


def _default_renderer(spec: DeliverableSpec, fmt: Literal["pdf", "pptx"]) -> bytes:
    return render_pdf(spec) if fmt == "pdf" else render_pptx(spec)


def create_app(
    *,
    renderer: Callable[[DeliverableSpec, Literal["pdf", "pptx"]], bytes] | None = None,
    oidc_verifier: Callable[[str, str], Mapping[str, Any]] | None = None,
    audience: str | None = None,
    allowed_callers: Sequence[str] = (),
    max_body_bytes: int = MAX_BODY_BYTES,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    render_timeout: float = DEFAULT_RENDER_TIMEOUT,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> FastAPI:
    if max_body_bytes <= 0 or max_output_bytes <= 0 or max_concurrency <= 0:
        raise ValueError("max_body_bytes, max_output_bytes, and max_concurrency must be positive")
    if not (math.isfinite(render_timeout) and render_timeout > 0):
        raise ValueError("render_timeout must be a positive finite number")

    fastapi_app = FastAPI(title="tilo-render", docs_url=None, redoc_url=None, openapi_url=None)
    eff_renderer = renderer if renderer is not None else _default_renderer
    eff_audience = audience if audience is not None else os.environ.get("TILO_RENDER_AUDIENCE", "").strip()
    env_callers = tuple(c.strip() for c in os.environ.get("TILO_RENDER_ALLOWED_CALLERS", "").split(",") if c.strip())
    callers = tuple(allowed_callers) if allowed_callers else env_callers
    semaphore = threading.BoundedSemaphore(max_concurrency)

    @fastapi_app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
    @fastapi_app.get("/healthz")
    async def healthz() -> dict[str, str]:  # async: runs on the event loop, never blocked by render worker threads
        return {"status": "ok"}

    @fastapi_app.post("/render")
    async def render_endpoint(request: Request) -> Response:
        token = _bearer_token(request)
        if token is None:
            return _refuse(401, "unauthorized")
        if oidc_verifier is None or not eff_audience or not callers:
            return _refuse(403, "forbidden")
        try:
            claims = await run_in_threadpool(oidc_verifier, token, eff_audience)
        except Exception:
            return _refuse(401, "unauthorized")
        if not service_caller_ok(claims, audience=eff_audience, allowed_callers=callers):
            return _refuse(403, "forbidden")
        if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
            return _refuse(415, "unsupported_media_type")

        cl_header = request.headers.get("content-length")
        if cl_header is not None:
            cl_val = cl_header.strip()
            if len(cl_val) > 10 or not _CONTENT_LENGTH_RE.fullmatch(cl_val):
                return _refuse(422, "invalid_spec")
            if int(cl_val) > max_body_bytes:
                log.warning("render refused: reason=too_large content_length=%s", cl_val)
                return _refuse(413, "too_large")

        buf = bytearray()
        async for chunk in request.stream():
            buf.extend(chunk)
            if len(buf) > max_body_bytes:
                log.warning("render refused: reason=too_large body_bytes=%d", len(buf))
                return _refuse(413, "too_large")

        def _parse_and_validate(raw_bytes: bytes) -> RenderRequestPayload:
            text = raw_bytes.decode("utf-8").strip()
            if not (text.startswith("{") and text.endswith("}")):
                raise ValueError("not a JSON object")
            raw_data = json.loads(text, object_pairs_hook=_no_dup_keys, parse_constant=_no_nan_inf)
            return RenderRequestPayload.model_validate(raw_data)

        try:
            req_data = await run_in_threadpool(_parse_and_validate, bytes(buf))
        except (UnicodeDecodeError, ValueError, ValidationError, RecursionError):
            log.warning("render refused: reason=invalid_spec body_bytes=%d", len(buf))
            return _refuse(422, "invalid_spec")

        if not semaphore.acquire(blocking=False):
            log.warning("render refused: reason=busy format=%s", req_data.format)
            return _refuse(429, "busy")

        handover = threading.Lock()
        worker_claimed = False
        abandoned = False

        def _run_worker() -> bytes:
            nonlocal worker_claimed
            with handover:
                if abandoned:
                    return b""
                worker_claimed = True
            try:
                return eff_renderer(req_data.spec, req_data.format)
            finally:
                semaphore.release()

        started = time.monotonic()
        try:
            rendered = await asyncio.wait_for(run_in_threadpool(_run_worker), timeout=render_timeout)
        except TimeoutError:
            log.warning("render refused: reason=timeout format=%s", req_data.format)
            return _refuse(504, "timeout")
        except Exception:
            log.warning("render refused: reason=render_failed format=%s", req_data.format)
            return _refuse(502, "render_failed")
        finally:
            # Timeout and CancelledError also surrender an unclaimed slot. A late
            # thread observes abandoned and cannot render or release it again.
            with handover:
                abandoned = True
                if not worker_claimed:
                    semaphore.release()

        mime_type, disposition, magic = _MIME_BY_FORMAT[req_data.format]
        if not isinstance(rendered, bytes) or not rendered.startswith(magic):
            return _refuse(502, "render_failed")
        out_bytes = bytes(memoryview(rendered))
        if len(out_bytes) > max_output_bytes:
            log.warning("render refused: reason=output_too_large format=%s bytes=%d", req_data.format, len(out_bytes))
            return _refuse(413, "output_too_large")

        elapsed_ms = int((time.monotonic() - started) * 1000)
        log.info("render ok: format=%s in=%d out=%d ms=%d", req_data.format, len(buf), len(out_bytes), elapsed_ms)
        hdrs = {"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
        return Response(content=out_bytes, status_code=200, media_type=mime_type, headers=hdrs)

    return fastapi_app


app = create_app()
