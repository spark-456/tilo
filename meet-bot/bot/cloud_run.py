"""Private, request-bound guest sessions. Meeting capabilities stay in memory."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from tilo_connectors.host_auth import GOOGLE_ISSUERS, CertsUnavailable, GoogleOidcVerifier
from tilo_contracts import MeetingJoin, Transcript

from .events import remove_meet_links
from .voice_meter import CLAIM_HEADER, CLAIM_RE


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
            return reply(401, "Identity required")
        try:
            claims = await asyncio.to_thread(verifier.verify, authorization[7:], audience)
        except CertsUnavailable:
            return reply(503, "Identity verification unavailable")
        except Exception:
            return reply(401, "Invalid identity")
        if not (
            claims.get("iss") in GOOGLE_ISSUERS
            and claims.get("aud") == audience
            and claims.get("email_verified") is True
            and claims.get("email") == caller
        ):
            return reply(403, "Caller is not allowed")
        if not re.fullmatch(r"mt_[a-zA-Z0-9_]{1,48}", meeting_id):
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
        except (ValidationError, ValueError, TypeError):
            return reply(422, "Invalid or expired join capability")
        if busy.locked():
            return reply(409, "Bot is attending another meeting")
        # ADR-0042 (MV-16): tilo-api's nonce for this attend. Held in memory, handed to the worker only, never logged;
        # absent or malformed (an older caller) means no meter: the call is exactly what it was.
        claim = request.headers.get(CLAIM_HEADER, "")
        extra = {"claim": claim} if CLAIM_RE.fullmatch(claim) else {}
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
            except Exception:
                return reply(502, "Meeting bot failed")

    return app
