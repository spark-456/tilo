"""The owner's own meeting-host connection routes (FR-MTG-09, ADR-0032 decisions 5 to 7, ADR-0024; ticket T6).

`GET /v1/meeting-host/connection`: the signed-in person's grant state from connectors' `status` (state, scope_ok; no
address, token or link). `POST /v1/meeting-host/disconnect`: abandon first, then connectors' `disconnect`, then the
returned parts. The person is the verified principal on a full sign-in session and nothing else: no path, query or body
value names one, so one person can never read or end another's connection. A failure is a fixed 503 (`not_configured`
when connectors refused before anything acted, else `unknown`: retry), never success and never raw error text. The
disconnect is idempotent at connectors and here: the entries are abandoned (`failed`, never sent) before the call, so
a reconnect later sends nothing for them, whatever happens to the call.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from tilo_connectors.meeting_host import CONNECTOR_ID
from tilo_contracts import MeetingHostRpcAlertPart, MeetingHostRpcConnectionPart

from tilo_api import deps
from tilo_api.meeting_host import abandon_unsent
from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Empty, Refusal, json_body

logger = logging.getLogger("tilo_api.meeting_host_routes")
router = APIRouter(route_class=_PeopleRoute)


def _owner(principal: deps.Principal) -> str:
    if not principal.full_session:  # an anonymous demo session has no connection to read or end
        raise Refusal(403, "forbidden")
    return principal.user_id


def _failed(exc: HostRpcError) -> HTTPException:
    return HTTPException(status_code=503, detail="not_configured" if exc.kind == "refused" else "unknown")


async def _empty_or_none(request: Request) -> None:
    """No body at all, or the closed `{}`; anything else is the usual 415 or 422."""
    if request.headers.get("content-length") in (None, "0") and "transfer-encoding" not in request.headers:
        return None
    await json_body(Empty)(request)


@router.get("/v1/meeting-host/connection")
def connection_status(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    client: Annotated[MeetingHostRpc, Depends(deps.get_meeting_host_client)],
) -> dict[str, Any]:
    user = _owner(principal)
    try:
        got = client.status(user)
    except HostRpcError as exc:
        raise _failed(exc) from None
    return {"state": got.state, "scope_ok": got.scope_ok}


@router.post("/v1/meeting-host/disconnect")
def disconnect(
    _: Annotated[None, Depends(_empty_or_none)],
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    client: Annotated[MeetingHostRpc, Depends(deps.get_meeting_host_client)],
    outbox_store: Annotated[Any, Depends(deps.get_outbox_store)],
) -> dict[str, Any]:
    user = _owner(principal)
    try:
        abandon_unsent(user, outbox_store)  # first: whatever happens to the call, a reconnect sends nothing for these
    except Exception:  # noqa: BLE001 - the outbox cannot be read, so nothing is disconnected yet
        logger.warning("meeting-host disconnect: the outbox could not be read")
        raise HTTPException(status_code=503, detail="unknown") from None
    try:
        got = client.disconnect(user)
    except HostRpcError as exc:
        raise _failed(exc) from None
    alerts = 0
    for part in got.parts:
        if isinstance(part, MeetingHostRpcAlertPart):
            alerts += 1  # ids only; there is no world here to record it in (a kept revoke is retried by a disconnect)
        elif isinstance(part, MeetingHostRpcConnectionPart) and part.user_id == user and part.connector == CONNECTOR_ID:
            try:  # a lease that held an entry before is gone now: this pass takes it
                abandon_unsent(user, outbox_store)
            except Exception:  # noqa: BLE001 - the answer is already true; the entry stays for the next event
                logger.warning("meeting-host disconnect: the second pass could not read the outbox")
    if alerts:
        logger.warning("meeting-host disconnect: %d revoke(s) kept for a retry", alerts)
    return {"disconnected": True, "revoked_at_provider": got.revoked_at_provider}
