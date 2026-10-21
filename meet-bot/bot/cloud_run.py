"""Private, request-bound guest sessions. Meeting capabilities stay in memory."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from tilo_connectors.host_auth import GOOGLE_ISSUERS, CertsUnavailable, GoogleOidcVerifier
from tilo_contracts import MeetingJoin, Transcript

from .browser import BrowserStartFailed, JoinFailed, NotLoggedIn
from .events import remove_meet_links
from .meeting_actions import ACTIONS_HEADER
from .voice_meter import CLAIM_HEADER, CLAIM_RE

logger = logging.getLogger(__name__)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_SECRET = re.compile(r"(?i)\b(cookie|authorization|bearer|token|sid|oauth)\b(?:\s+|\s*=\s*)\S+")
_OPAQUE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


def _safe_reason(exc: BaseException) -> str:
    """One operational line with capabilities, credentials and opaque values removed."""
    reason = " ".join(str(exc).split())
    reason = _URL.sub("[url]", reason)
    reason = _SECRET.sub(lambda found: f"{found.group(1)}=[redacted]", reason)
    reason = _OPAQUE.sub("[redacted]", reason)
    return (reason or "no detail")[:200]


def _log_refusal(status: int, reason: str, exc: BaseException | None = None) -> None:
    if exc is None:
        logger.warning("meeting attend refused status=%s reason=%s", status, reason)
    else:
        logger.warning(
            "meeting attend refused status=%s reason=%s error=%s detail=%s",
            status,
            reason,
            type(exc).__name__,
            _safe_reason(exc),
        )


async def attend_while_connected(request: Request, attendance):
    async def disconnected():
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return

    worker = asyncio.create_task(attendance)
    connection = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait({worker, connection}, timeout=3450, return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            return await worker
        if connection in done:
            raise ConnectionError("Caller disconnected")
        raise TimeoutError
    finally:
        # A lost request must not leave a browser running while request-based CPU is suspended.
        worker.cancel()
        connection.cancel()
        await asyncio.gather(worker, connection, return_exceptions=True)


def create_app(*, attend=None, verifier=None, clock=None) -> FastAPI:
    if attend is None:
        from .cloud_worker import attend_meeting

        attend = attend_meeting
    verifier = verifier or GoogleOidcVerifier()
    clock = clock or (lambda: datetime.now(UTC))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    busy = asyncio.Lock()

    def reply(status: int, detail: str) -> JSONResponse:
        return JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/internal/meetings/{meeting_id}/attend")
    async def launch(meeting_id: str, request: Request):
        audience = os.environ.get("TILO_MEET_BOT_AUDIENCE", "")
        caller = os.environ.get("TILO_MEET_BOT_CALLER", "")
        if not audience or not caller or os.environ.get("LIVE") != "1":
            return reply(503, "Bot is not enabled")
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            _log_refusal(401, "identity_required")
            return reply(401, "Identity required")
        try:
            claims = await asyncio.to_thread(verifier.verify, authorization[7:], audience)
        except CertsUnavailable:
            return reply(503, "Identity verification unavailable")
        except Exception as exc:
            _log_refusal(401, "invalid_identity", exc)
            return reply(401, "Invalid identity")
        if not (
            claims.get("iss") in GOOGLE_ISSUERS
            and claims.get("aud") == audience
            and claims.get("email_verified") is True
            and claims.get("email") == caller
        ):
            _log_refusal(403, "caller_not_allowed")
            return reply(403, "Caller is not allowed")
        if not re.fullmatch(r"mt_[a-zA-Z0-9_]{1,48}", meeting_id):
            _log_refusal(422, "invalid_meeting")
            return reply(422, "Invalid meeting")
        # A bounded stream avoids collecting arbitrary bodies or validation errors containing the capability.
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 2048:
                return reply(413, "Request is too large")
            raw.extend(chunk)
        try:
            join = MeetingJoin.model_validate_json(raw)
            expires = datetime.fromisoformat(str(join.expires_at).replace("Z", "+00:00"))
            if not 0 < (expires - clock()).total_seconds() <= 60:
                raise ValueError("expired")
        except (ValidationError, ValueError, TypeError) as exc:
            _log_refusal(422, "invalid_join_capability", exc)
            return reply(422, "Invalid or expired join capability")
        if busy.locked():
            return reply(409, "Bot is attending another meeting")
        # ADR-0042 (MV-16): tilo-api's nonce for this attend. Held in memory, handed to the worker only, never logged;
        # absent or malformed (an older caller) means no meter: the call is exactly what it was.
        claim = request.headers.get(CLAIM_HEADER, "")
        extra = {"claim": claim} if CLAIM_RE.fullmatch(claim) else {}
        # ADR-0042 amendment 1: the attend's action nonce (only while tilo-api's TILO_MEETING_ACTIONS=1), never logged.
        action_claim = request.headers.get(ACTIONS_HEADER, "")
        if CLAIM_RE.fullmatch(action_claim):
            extra["action_claim"] = action_claim
        async with busy:
            try:
                # Leave time for cleanup before Cloud Run's 3600s request deadline.
                result = await attend_while_connected(request, attend(meeting_id, join.join_url, **extra))
                transcript = Transcript.model_validate(remove_meet_links(result))
                if transcript.meeting_id != meeting_id:
                    raise ValueError("wrong meeting")
                reason = getattr(result, "reason", "completed")
                if reason not in ("completed", "left_on_request", "removed", "timeout", "failed"):
                    raise ValueError("Invalid end reason")
                return JSONResponse(
                    transcript.model_dump(mode="json"),
                    headers={
                        "Cache-Control": "no-store",
                        "X-Tilo-Meeting-End-Reason": reason,
                    },
                )
            except TimeoutError:
                return reply(504, "Meeting duration exceeded")
            except BrowserStartFailed as exc:
                _log_refusal(502, "browser_unavailable", exc)
                return reply(502, "browser_unavailable")
            except NotLoggedIn as exc:
                _log_refusal(409, "meeting_requires_sign_in", exc)
                return reply(409, "meeting_requires_sign_in")
            except JoinFailed as exc:
                _log_refusal(409, "meeting_join_failed", exc)
                return reply(409, "meeting_join_failed")
            except Exception as exc:
                _log_refusal(502, "worker_failed", exc)
                return reply(502, "Meeting bot failed")

    return app
