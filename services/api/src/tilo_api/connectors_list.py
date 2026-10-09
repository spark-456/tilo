"""`GET /v1/connectors` (LIVE-GAPS-1b; FR-CON-01/02, FR-ACC-03/04; services/api/tests/test_FR_CON_02_LIVE_GAPS_1b_*).

The signed-in person's connectors (the registry's, in its order) with their connection state, read ONLY through the
read-only seam `deps.get_connection_views` (state, scopes, expiry, nothing else). SEC-02 / ADR-0032: tilo-api never
holds a TokenBroker, token records, a Kms or the OAuth client secret, so this module never touches
`deps.get_token_broker`. The owner is `Principal.user_id` and nothing in the request. A pure read: no store write, no
provider call, no event. An unwired seam (production today, BQ-LIVEGAPS-1), a seam override that needs parameters, or
a failed read is never an error: that connector is `available` and its row `state_known` is false (true only
when that row was read from a wired seam). No error text reaches the body, the headers or the logs.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from tilo_connectors._time import format_ts, parse_ts

from tilo_api import deps
from tilo_api.people import _PeopleRoute

# FR-ACC-04: `attention` keys on the GRANT (the broker's stored state), never on the access token's ~1 h expiry.
_ATTENTION_STATES = frozenset({"expiring", "expired", "revoked", "needs_reconnect"})


_MAX_SCOPES, _MAX_SCOPE_LEN = 50, 200


def _optional_views(request: Request) -> Any | None:
    """The read-only seam `deps.get_connection_views` (overrides honoured); None when unwired, failing, or an override
    that needs parameters (calling it bare raises TypeError, which is treated as unwired)."""
    provider = request.app.dependency_overrides.get(deps.get_connection_views, deps.get_connection_views)
    try:
        return provider()
    except Exception:  # noqa: BLE001 - the default is HTTP 503 `not_configured`; any failure means unknown, silently
        return None


def _row(
    declared: dict[str, Any], state: str, scopes: list[str], expires_at: str | None, *, known: bool
) -> dict[str, Any]:
    return {  # an explicit allowlist: nothing else of a record is ever copied
        "id": declared["id"],
        "name": declared["name"],
        "auth": declared["auth"],
        "state": state,
        "scopes": scopes,
        "expires_at": expires_at,
        "state_known": known,
    }


def _clean_scopes(scopes: Any) -> list[str]:
    if not isinstance(scopes, list):  # a str, dict or other iterable is not a list of scopes
        return []
    seen = [s for s in scopes if isinstance(s, str) and len(s) <= _MAX_SCOPE_LEN]
    return seen[:_MAX_SCOPES]


def _clean_expiry(value: Any) -> str | None:
    """Only a parsed, normalised RFC 3339 UTC string; anything else is null."""
    try:
        return format_ts(parse_ts(value))
    except (ValueError, TypeError, OverflowError):
        return None


def _state(stored: str | None) -> str:
    if stored is None:
        return "available"
    if stored == "connected":
        return "connected"
    return "attention" if stored in _ATTENTION_STATES else "available"


def _one(views: Any, user_id: str, declared: dict[str, Any]) -> dict[str, Any]:
    stored, scopes, expires_at = views.view(user_id, declared["id"])
    if stored is None:
        return _row(declared, "available", [], None, known=True)
    stamp = _clean_expiry(expires_at)
    state = _state(str(stored))
    return _row(
        declared, state, _clean_scopes(scopes), stamp if state in ("connected", "attention") else None, known=True
    )


router = APIRouter(route_class=_PeopleRoute)


@router.get("/v1/connectors")
def connectors_route(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    registry: Annotated[Any, Depends(deps.get_connector_registry)],
    views: Annotated[Any, Depends(_optional_views)],
) -> dict[str, Any]:
    declared_all = [{"id": cid, **registry.get(cid)} for cid in registry.ids()]
    rows: list[dict[str, Any]] = []
    for declared in declared_all:
        row: dict[str, Any] | None = None
        if views is not None:
            try:
                row = _one(views, principal.user_id, declared)
            except Exception:  # noqa: BLE001 - one failing connector is `available`; its error text goes nowhere
                row = None
        if row is None:  # built outside any handler: nothing can chain the failure's text
            row = _row(declared, "available", [], None, known=False)
        rows.append(row)
    return {"connectors": rows}
