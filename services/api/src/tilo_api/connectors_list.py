"""`GET /v1/connectors` (LIVE-GAPS-1b; FR-CON-01/02, FR-ACC-03/04; services/api/tests/test_FR_CON_02_LIVE_GAPS_1b_*).

The signed-in person's connectors (the registry's, in its order) with their connection state, read ONLY through the
read-only seam `deps.get_connection_views` (state, scopes, connected_at, nothing else;
ADR-0032a). SEC-02 / ADR-0032: tilo-api never
holds a TokenBroker, token records, a Kms or the OAuth client secret, so this module never touches
`deps.get_token_broker`. The owner is `Principal.user_id` and nothing in the request. A pure read: no store write, no
provider call, no event. An unwired seam (production today, BQ-LIVEGAPS-1), a seam override that needs parameters, or
a failed read is never an error: that connector is `available` and its row `state_known` is false (true only
when that row was read from a wired seam). No error text reaches the body, the headers or the logs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from tilo_connectors._time import format_ts, parse_ts

from tilo_api import deps
from tilo_api.people import _PeopleRoute

# FR-ACC-04 (ADR-0032a decision 7, BQ-ADR32a-2): the view has no expiry. The sign-in expires GRANT_LIFETIME after
# `connected_at` (testing-mode sign-ins, PRD 11.5; drop once the OAuth app is verified); the warning comes WARN_AHEAD
# before that. `expires_at` in a row is this derived instant or null, never an access-token expiry.
GRANT_LIFETIME = timedelta(days=7)
WARN_AHEAD = timedelta(days=3)
_CLOCK_SKEW = timedelta(minutes=5)  # a connected_at further in the future than this is not believed (unknown)


_MAX_SCOPES, _MAX_SCOPE_LEN = 50, 200


def _optional_views(request: Request) -> Any | None:
    """The read-only seam `deps.get_connection_views` (overrides honoured); None when unwired, failing, or an override
    that needs parameters (calling it bare raises TypeError, which is treated as unwired)."""
    provider = request.app.dependency_overrides.get(deps.get_connection_views, deps.get_connection_views)
    try:
        return provider()
    except HTTPException as exc:
        if exc.status_code == 503 and exc.detail == "not_configured":
            return deps._RpcConnectionViews(_not_configured)
        return None
    except Exception:  # noqa: BLE001 - the default is HTTP 503 `not_configured`; any failure means unknown, silently
        return None


def _not_configured(_: str) -> None:
    raise deps.ConnectionViewsNotConfigured


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


def _connected_at(value: Any) -> datetime | None:
    """Only a parsed UTC instant that is not in the future; anything else is unknown (None)."""
    try:
        at = parse_ts(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return None if at > datetime.now(UTC) + _CLOCK_SKEW else at


def _one(views: Any, user_id: str, declared: dict[str, Any]) -> dict[str, Any]:
    stored, scopes, connected_at = views.view(user_id, declared["id"])
    if stored is None:  # no record: never connected
        return _row(declared, "available", [], None, known=True)
    if stored != "connected":  # expired, or a state the contract does not have: the person is warned, never "Connect"
        return _row(declared, "attention", _clean_scopes(scopes), None, known=True)
    at = _connected_at(connected_at)
    if at is None:  # recorded before connected_at existed, or not believable: connected, no warning, no expiry
        return _row(declared, "connected", _clean_scopes(scopes), None, known=True)
    ends = at + GRANT_LIFETIME
    state = "attention" if ends - datetime.now(UTC) <= WARN_AHEAD else "connected"
    return _row(declared, state, _clean_scopes(scopes), format_ts(ends), known=True)


router = APIRouter(route_class=_PeopleRoute)


@router.get("/v1/connectors")
def connectors_route(
    response: Response,
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
            except deps.ConnectionViewsNotConfigured:
                row = _row(declared, "available", [], None, known=False)
                if declared["id"] == "meeting_host":
                    response.headers["X-Tilo-Meeting-Host"] = "not_configured"
                    response.headers["Access-Control-Expose-Headers"] = "X-Tilo-Meeting-Host"
            except Exception:  # noqa: BLE001 - one failing connector is `available`; its error text goes nowhere
                row = None
        if row is None:  # built outside any handler: nothing can chain the failure's text
            row = _row(declared, "available", [], None, known=False)
        rows.append(row)
    return {"connectors": rows}
