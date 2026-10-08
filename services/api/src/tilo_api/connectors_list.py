"""`GET /v1/connectors` (LIVE-GAPS-1b; FR-CON-01/02, FR-ACC-03/04; services/api/tests/test_FR_CON_02_LIVE_GAPS_1b_*).

The signed-in person's connectors (the registry's, in its order) with their connection state, read through the token
broker's `connection_view`: state, scopes and expiry, nothing else (SEC-02: no token, ciphertext or key leaves the
broker). The owner is `Principal.user_id` and nothing in the request. A pure read: no store write, no provider call,
no event. An unwired broker (production today, BQ-LIVEGAPS-1) or a failed read is never an error: that connector is
`available` and `state_known` is false. No error text reaches the body, the headers or the logs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from tilo_api import deps
from tilo_api.people import _PeopleRoute

_WARN_AHEAD = timedelta(days=3)  # FR-ACC-04: the warning shows 3 days ahead
_ATTENTION_STATES = frozenset({"expiring", "expired", "revoked", "needs_reconnect"})


def _optional_broker(request: Request) -> Any | None:
    """The token broker through the `deps.get_token_broker` seam (overrides honoured); None when unwired or failing."""
    provider = request.app.dependency_overrides.get(deps.get_token_broker, deps.get_token_broker)
    try:
        return provider()
    except Exception:  # noqa: BLE001 - the default is HTTP 503 `not_configured`; any failure means unknown, silently
        return None


def _row(declared: dict[str, Any], state: str, scopes: list[str], expires_at: str | None) -> dict[str, Any]:
    return {  # an explicit allowlist: nothing else of a record is ever copied
        "id": declared["id"],
        "name": declared["name"],
        "auth": declared["auth"],
        "state": state,
        "scopes": scopes,
        "expires_at": expires_at,
    }


def _state(stored: str | None, expires_at: str | None, now: datetime) -> str:
    if stored is None:
        return "available"
    if stored != "connected":
        return "attention" if stored in _ATTENTION_STATES else "available"
    if expires_at is None:
        return "attention"
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return "connected" if expiry - now > _WARN_AHEAD else "attention"
    except (ValueError, TypeError):
        return "attention"


def _one(broker: Any, user_id: str, declared: dict[str, Any], now: datetime) -> dict[str, Any]:
    stored, scopes, expires_at = broker.connection_view(user_id, declared["id"])
    if stored is None:
        return _row(declared, "available", [], None)
    seen = [s for s in scopes if isinstance(s, str)]
    stamp = expires_at if isinstance(expires_at, str) else None
    return _row(declared, _state(str(stored), stamp, now), seen, stamp)


router = APIRouter(route_class=_PeopleRoute)


@router.get("/v1/connectors")
def connectors_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
    broker: Annotated[Any, Depends(_optional_broker)],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    declared_all = [{"id": cid, **registry.get(cid)} for cid in registry.ids()]
    rows: list[dict[str, Any]] = []
    known = broker is not None
    for declared in declared_all:
        try:
            if broker is None:
                raise LookupError
            rows.append(_one(broker, principal.user_id, declared, now))
        except Exception:  # noqa: BLE001 - one failing connector is `available`; its error text goes nowhere
            known = False
            rows.append(_row(declared, "available", [], None))
    return {"connectors": rows, "state_known": known}
