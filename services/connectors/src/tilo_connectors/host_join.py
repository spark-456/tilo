"""API-only host Calendar read: reuse closed receipt/MeetingJoin types, never persist the capability."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from tilo_contracts import MeetingHostRpcReceipt, MeetingJoin

from ._time import format_ts, parse_ts
from .adapters.meeting_host import MeetingHostAdapter
from .errors import MeetingHostRefused, ProviderUnavailable
from .host_auth import CertsUnavailable, caller_status
from .host_broker import BrokerNotConfigured
from .tokens import ConnectionExpired, InsufficientScope, NotConnected

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .host_routes import HostRuntime


def join_router(runtime: HostRuntime) -> APIRouter:
    from .host_routes import _declaration, _OneDraft, _Receipts

    router = APIRouter()

    def refused(status: int, code: str) -> JSONResponse:
        return JSONResponse({"error": code}, status_code=status, headers={"Cache-Control": "no-store"})

    def read(receipt: MeetingHostRpcReceipt) -> dict:
        if runtime._stopped(receipt.owner):
            raise NotConnected("Host disconnected")
        adapter = MeetingHostAdapter(
            declaration=_declaration(),
            broker=runtime._broker.get(),
            transport=runtime._transport.get(),
            artifacts=_OneDraft(("", 0), {}),
            owner_of=lambda _: receipt.owner,
            receipts=_Receipts(),
            clock=runtime._clock,
            emit=lambda _: None,
            sleep=lambda _: None,
        )
        link = adapter.join_link(receipt.owner, receipt.event_ref)
        return MeetingJoin(
            join_url=link,
            expires_at=format_ts(parse_ts(runtime._clock()) + timedelta(seconds=60)),
        ).model_dump(mode="json")

    @router.post("/meeting-host/join")
    async def join(request: Request):
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token or any(char.isspace() for char in token):
            return refused(401, "unauthenticated")
        settings = runtime.settings()
        if settings is None:
            return refused(503, "not_configured")
        audience, caller = settings
        try:
            claims = await run_in_threadpool(runtime.verifier.verify, token, audience)
            status = caller_status(claims, audience=audience, caller=caller)
        except CertsUnavailable:
            return refused(503, "try_again")
        except Exception:
            return refused(401, "unauthenticated")
        if status is not None:
            return refused(status, "forbidden" if status == 403 else "unauthenticated")
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 2048:
                return refused(413, "invalid_request")
            raw.extend(chunk)
        try:
            receipt = MeetingHostRpcReceipt.model_validate_json(raw)
        except ValidationError:
            return refused(422, "invalid_request")
        try:
            answer = await run_in_threadpool(read, receipt)
        except MeetingHostRefused as error:
            return refused(409, "not_joinable" if error.rule == "MH-20" else "no_join_link")
        except (NotConnected, ConnectionExpired, InsufficientScope):
            return refused(409, "host_not_connected")
        except BrokerNotConfigured:
            return refused(503, "not_configured")
        except ProviderUnavailable:
            return refused(503, "try_again")
        except Exception as exc:
            _log.error("a join read failed (%s)", type(exc).__name__)
            return refused(503, "try_again")
        return JSONResponse(answer, headers={"Cache-Control": "no-store"})

    return router
