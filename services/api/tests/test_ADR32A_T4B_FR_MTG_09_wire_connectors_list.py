"""ADR-0032a T4b: `deps.get_connection_views` (the seam `GET /v1/connectors` reads) is backed by the one
connection-views RPC call. One call per GET (never one per connector), any failure leaves every row unknown (never an
error), the user id is the signed-in principal's, and no expiry crosses."""

from __future__ import annotations

from types import SimpleNamespace

from _api_lib import as_full_session, as_principal, make_principal
from tilo_api import app, deps

USER = "u_wire"


def _view(connector: str, state: str, scopes: list[str]) -> SimpleNamespace:
    return SimpleNamespace(connector=connector, state=state, scopes=scopes, connected_at=None)


def _install(views, monkeypatch):
    calls: list[str] = []

    def rpc():
        def call(user_id: str):
            calls.append(user_id)
            return views

        return call

    monkeypatch.setattr(deps, "get_connection_views_rpc", rpc)  # the seam resolves it by name, not per request
    as_principal(as_full_session(make_principal(user_id=USER, role="owner", world_id=None)))
    return calls


def _rows(client):
    response = client.get("/v1/connectors")
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()["connectors"]}


def test_ADR32A_T4B_FR_MTG_09_one_rpc_call_serves_the_whole_list_for_the_signed_in_user(client, monkeypatch):
    calls = _install([_view("gmail", "connected", ["https://www.googleapis.com/auth/gmail.readonly"])], monkeypatch)

    rows = _rows(client)

    assert calls == [USER], "one call per GET, with the principal's id"
    assert rows["gmail"]["state"] == "connected" and rows["gmail"]["state_known"] is True
    assert rows["gmail"]["expires_at"] is None
    assert all(r["state_known"] for r in rows.values())
    assert {r["state"] for k, r in rows.items() if k != "gmail"} == {"available"}


def test_ADR32A_T4B_FR_MTG_09_an_expired_grant_needs_attention(client, monkeypatch):
    _install([_view("gmail", "expired", [])], monkeypatch)

    assert _rows(client)["gmail"]["state"] == "attention"


def test_ADR32A_T4B_FR_MTG_09_a_failed_call_makes_every_row_unknown_and_is_not_repeated(client, monkeypatch):
    calls = _install(None, monkeypatch)

    rows = _rows(client)

    assert calls == [USER], "a failure is remembered inside the GET"
    assert all(r["state"] == "available" and r["state_known"] is False for r in rows.values())


def test_ADR32A_T4B_FR_MTG_09_unconfigured_is_503_for_the_seam_and_unknown_rows_for_the_list(client):
    app.dependency_overrides.pop(deps.get_connection_views, None)
    as_principal(as_full_session(make_principal(user_id=USER, role="owner", world_id=None)))
    deps.get_meeting_host_client.cache_clear()

    rows = _rows(client)

    assert all(r["state_known"] is False for r in rows.values())
