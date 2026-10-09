"""The person's public connect routes (ADR-0035 decisions 2 and 3, LC-03 to LC-06; FR-CON-02; ticket L4).

`POST /v1/connectors/connect` {connector, capabilities} -> {authorize_url | null}; `POST /v1/connectors/callback`
{state, code | error} -> {connector, scope_lines}; `POST /v1/connectors/disconnect` {connector}. Each calls
tilo-connectors over `MeetingHostRpc` (the one boundary, ADR-0032 HB-01) with the verified principal's own id: no path,
query, header or body value names a person, and only a full sign-in session may call (a demo session is 403).
tilo-api never logs, stores or echoes the one-time `code`, the `state` or any token (LC-03): they go from the body to
the call and nowhere else, and a refused body names fields, never values. A failure is a fixed code, never raw text:
503 `not_configured` when connectors refused before anything acted, else 503 `unknown` (retry); the callback's own
three 400s (`start_again`, `not_granted`, `wrong_account`) pass through as their one fixed word. The answer's parts are
handled as T6 does: only the caller's own connection parts reach the sink (`on_connection_event` abandons a revoked or
expired `meeting_host` grant's unsent entries); `connection.consented` stays tilo-api's card answer. Every POST counts
against the people write limit (it needs the people stores, else 503 `not_configured`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from tilo_connectors.meeting_host import CONNECTOR_ID
from tilo_contracts import MeetingHostRpcAlertPart, MeetingHostRpcConnectorPart

from tilo_api import deps
from tilo_api.meeting_host import abandon_unsent, on_connection_event
from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Refusal, _Closed, json_body

logger = logging.getLogger("tilo_api.connect_routes")
router = APIRouter(route_class=_PeopleRoute)

_Capability = Literal["read", "list", "search", "write", "send", "share", "delete"]
_ConnectorId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")]


class ConnectIn(_Closed):
    connector: _ConnectorId
    capabilities: Annotated[list[_Capability], Field(min_length=1, max_length=7)]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("duplicate")
        return self


class CallbackIn(_Closed):
    state: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")]
    code: Annotated[str, Field(pattern=r"^[A-Za-z0-9/_.~-]{1,512}$")] | None = None
    error: Annotated[str, Field(pattern=r"^[a-z][a-z_]{0,63}$")] | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Self:
        if (self.code is None) == (self.error is None):  # exactly one: the person agreed, or Google's word
            raise ValueError("code or error")
        return self


class DisconnectIn(_Closed):
    connector: _ConnectorId


def _owner(principal: deps.Principal) -> str:
    if not principal.full_session:  # an anonymous demo session connects nothing
        raise Refusal(403, "forbidden")
    return principal.user_id


def _failed(exc: HostRpcError) -> HTTPException:
    if exc.kind == "rejected" and exc.code is not None:
        return HTTPException(status_code=400, detail=exc.code)  # one of the callback's three fixed words
    return HTTPException(status_code=503, detail="not_configured" if exc.kind == "refused" else "unknown")


def _registered(registry: Any, connector: str, capabilities: Sequence[str] | None = None) -> None:
    """An oauth2 connector of the registry, and capabilities it declares: else 422 (connectors would only say 503)."""
    try:
        declared = registry.get(connector)
    except Exception:  # noqa: BLE001 - an unknown id
        declared = None
    if declared is None or declared.get("auth") != "oauth2":
        raise Refusal(422, "invalid_body", fields=[["connector"]])
    if capabilities is not None and not set(capabilities) <= set(declared.get("capabilities", ())):
        raise Refusal(422, "invalid_body", fields=[["capabilities"]])


def _apply(user: str, parts: list[Any], outbox_store: Any) -> list[str]:
    """The answer's parts: the caller's own connection parts go to the sink; anyone else's are dropped; an alert's id
    is returned (ids only; there is no world here to record it in)."""
    alerts: list[str] = []
    for part in parts:
        if isinstance(part, MeetingHostRpcAlertPart):
            alerts.append(part.alert_id)
        elif isinstance(part, MeetingHostRpcConnectorPart) and part.user_id == user:
            on_connection_event(
                {"type": part.type, "authz": None, "data": {"connector": part.connector}, "user_id": user},
                outbox_store=outbox_store,
            )
    return alerts


@router.post("/v1/connectors/connect")
def connect(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    body: Annotated[ConnectIn, Depends(json_body(ConnectIn))],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
    client: Annotated[MeetingHostRpc, Depends(deps.get_meeting_host_client)],
) -> dict[str, Any]:
    user = _owner(principal)
    _registered(registry, body.connector, body.capabilities)
    try:
        url = client.connect_start(user, body.connector, body.capabilities)
    except HostRpcError as exc:
        raise _failed(exc) from None
    return {"authorize_url": url}


@router.post("/v1/connectors/callback")
def callback(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    body: Annotated[CallbackIn, Depends(json_body(CallbackIn))],
    client: Annotated[MeetingHostRpc, Depends(deps.get_meeting_host_client)],
    outbox_store: Annotated[Any, Depends(deps.get_outbox_store)],
) -> dict[str, Any]:
    user = _owner(principal)
    try:
        got = client.connect_callback(user, state=body.state, code=body.code, error=body.error)
    except HostRpcError as exc:
        raise _failed(exc) from None
    alerts = _apply(user, got.parts, outbox_store)
    if alerts:
        logger.warning("connector callback: alert ids %s", ",".join(alerts))
    return {"connector": got.connector, "scope_lines": got.scope_lines}


@router.post("/v1/connectors/disconnect")
def disconnect(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    body: Annotated[DisconnectIn, Depends(json_body(DisconnectIn))],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
    client: Annotated[MeetingHostRpc, Depends(deps.get_meeting_host_client)],
    outbox_store: Annotated[Any, Depends(deps.get_outbox_store)],
) -> dict[str, Any]:
    user = _owner(principal)
    _registered(registry, body.connector)
    if body.connector == CONNECTOR_ID:
        try:
            abandon_unsent(
                user, outbox_store
            )  # first: whatever happens to the call, a reconnect sends nothing for these
        except Exception:  # noqa: BLE001 - the outbox cannot be read, so nothing is disconnected yet
            logger.warning("connector disconnect: the outbox could not be read")
            raise HTTPException(status_code=503, detail="unknown") from None
    try:
        got = client.connect_disconnect(user, body.connector)
    except HostRpcError as exc:
        raise _failed(exc) from None
    alerts = _apply(user, got.parts, outbox_store)
    if alerts:  # the ids find connectors' retry record; nothing here or there retries it on its own
        logger.warning("connector disconnect: revoke at Google not confirmed, alert ids %s", ",".join(alerts))
    return {"disconnected": True, "revoked_at_provider": got.revoked_at_provider, "revoke_pending": bool(alerts)}
