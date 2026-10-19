"""ADR35_L3 / FR_CON_02, FR_CON_03: the internal connect routes of tilo-connectors (ADR-0035 decisions 2-4, LC-05/06).

POST /internal/connections/{start,callback,disconnect} over ConsentService and the token broker, behind HB-01.
The rig is ADR-0032 T3's: FakeGoogle, FakeKms, an in-memory token store, no network, no paid call, nothing
reads the live switch.
"""

from __future__ import annotations

import json
import logging
import pathlib
import secrets
from typing import Any

import pytest
from _live_lib import no_external_network as no_external_network  # noqa: F401 - autouse guard
from _meeting_host_lib import CALENDAR_EVENTS_OWNED, OWNER
from _oauth_lib import DRIVE_FILE, GMAIL_COMPOSE, GMAIL_READONLY, GMAIL_SEND, leaks, parse_auth_url, s256
from test_ADR32_T2_host_broker import LIVE_KEY, _env
from test_ADR32_T3_host_routes import AUD, CALLER, FakeVerifier, Rig
from tilo_connectors.host_auth import CertsUnavailable
from tilo_connectors.host_routes import AUDIENCE_VAR, CALLER_VAR, MAX_BODY_BYTES, HostRuntime
from tilo_connectors.tokens import REVOKE_URL

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
OTHER = "u_other"
ROUTES = ("start", "callback", "disconnect")
BODIES: dict[str, dict[str, Any]] = {
    "start": {"user_id": OWNER, "connector": "gmail", "capabilities": ["read"]},
    "callback": {"user_id": OWNER, "state": "s" * 22, "code": "c" * 20},
    "disconnect": {"user_id": OWNER, "connector": "gmail"},
}


def post(rig: Rig, route: str, body: Any = None, *, token: str | None = "good", raw: bytes | None = None) -> Any:
    headers = {} if token is None else {"authorization": f"Bearer {rig.good if token == 'good' else token}"}
    data = raw if raw is not None else json.dumps(BODIES[route] if body is None else body).encode()
    return rig.client.post(f"/internal/connections/{route}", content=data, headers=headers)


def begin(rig: Rig, connector: str = "gmail", capabilities: tuple[str, ...] = ("read",), user: str = OWNER) -> Any:
    response = post(rig, "start", {"user_id": user, "connector": connector, "capabilities": list(capabilities)})
    assert response.status_code == 200, response.text
    url = response.json()["authorize_url"]
    return parse_auth_url(url) if url else None


def code_for(rig: Rig, flow: Any, granted: list[str] | None = None) -> str:
    return rig.env.google.issue_code(
        flow.scopes if granted is None else granted,
        challenge=flow.query["code_challenge"],
        redirect_uri=flow.query["redirect_uri"],
    )


def finish(rig: Rig, flow: Any, *, user: str = OWNER, granted: list[str] | None = None, **over: Any) -> Any:
    body = {"user_id": user, "state": flow.state, "code": code_for(rig, flow, granted)}
    return post(rig, "callback", {**body, **over})


def stored(rig: Rig) -> list[tuple[str, str]]:
    return rig.env.store.live_keys()


def revoked_types(answer: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((p["type"], p["connector"]) for p in answer["parts"])


# ---- HB-01 and the request shape, on all three routes -----------------------------------------


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("missing", [AUDIENCE_VAR, CALLER_VAR])
def test_ADR35_L3_FR_CON_02_unset_audience_or_caller_is_503_not_configured(route: str, missing: str) -> None:
    rig = Rig(
        settings={k: v for k, v in {AUDIENCE_VAR: AUD, CALLER_VAR: CALLER}.items() if k != missing}, connect_at=None
    )
    response = post(rig, route)
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert rig.verifier.calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_ADR35_L3_FR_CON_02_without_the_live_switch_every_route_is_503_and_nothing_is_built(route: str) -> None:
    env = {AUDIENCE_VAR: AUD, CALLER_VAR: CALLER, **_env(**{LIVE_KEY: True})}
    verifier = FakeVerifier()
    token = verifier.add()
    runtime = HostRuntime(env, verifier=verifier)
    from fastapi.testclient import TestClient
    from tilo_connectors.app import create_app

    response = TestClient(create_app(runtime)).post(
        f"/internal/connections/{route}", json=BODIES[route], headers={"authorization": f"Bearer {token}"}
    )
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})


@pytest.mark.parametrize("route", ROUTES)
def test_ADR35_L3_FR_CON_02_no_valid_token_is_401_before_the_body_is_read(route: str) -> None:
    rig = Rig(connect_at=None)
    for token in (None, "unknown-" + secrets.token_hex(4)):
        response = post(rig, route, token=token)
        assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
    for header in ("Basic " + rig.good, "Bearer", "Bearer a b", rig.good):
        r = rig.client.post(f"/internal/connections/{route}", content=b"{}", headers={"authorization": header})
        assert r.status_code == 401
    assert post(rig, route, raw=b"x" * (MAX_BODY_BYTES + 1), token=None).status_code == 401
    assert rig.env.google.calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_ADR35_L3_FR_CON_02_another_account_is_403_and_unavailable_certificates_are_502(route: str) -> None:
    rig = Rig(connect_at=None)
    other = rig.verifier.add(email="harness-" + secrets.token_hex(3) + "@demo-tilo.example.test")
    response = post(rig, route, token=other)
    assert (response.status_code, response.json()) == (403, {"error": "forbidden"})

    class NoCerts(FakeVerifier):
        def verify(self, token: str, audience: str) -> dict[str, Any]:
            raise CertsUnavailable("down")

    rig.runtime.verifier = NoCerts()
    response = post(rig, route)
    assert (response.status_code, response.json()) == (502, {"error": "not_configured"})
    assert rig.env.google.calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_ADR35_L3_FR_CON_02_a_bad_request_is_422_with_a_fixed_body_and_nothing_is_done(route: str) -> None:
    rig = Rig(connect_at=None)
    good = BODIES[route]
    bad = [b"not json", b"[]", b"null", json.dumps({**good, "extra": 1}).encode(), b"{}", b"[" * 100_000]
    bad += [b"x" * (MAX_BODY_BYTES + 1)]
    for raw in bad:
        response = post(rig, route, raw=raw)
        assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.env.google.calls == [] and stored(rig) == []


@pytest.mark.parametrize("fixture", ["callback_request", "start_request"])
def test_ADR35_L3_FR_CON_02_every_invalid_contract_fixture_is_422(fixture: str) -> None:
    rig = Rig(connect_at=None)
    route = fixture.split("_")[0]
    paths = sorted((CONTRACTS / "fixtures" / f"meeting_host_rpc.{fixture}" / "invalid").glob("*.json"))
    assert paths
    for path in paths:
        response = post(rig, route, json.loads(path.read_text(encoding="utf-8")))
        assert (response.status_code, response.json()) == (422, {"error": "invalid_request"}), path.name
    assert rig.env.google.calls == []


# ---- start: scopes, incremental, PKCE and state ----------------------------------------------


def test_ADR35_L3_FR_CON_02_start_asks_only_for_the_named_capabilities_with_pkce_and_a_state() -> None:
    rig = Rig(connect_at=None)
    response = post(rig, "start", {"user_id": OWNER, "connector": "gmail", "capabilities": ["read", "write"]})
    assert response.status_code == 200 and list(response.json()) == ["authorize_url"]
    flow = parse_auth_url(response.json()["authorize_url"])
    assert flow.base == "https://accounts.google.com/o/oauth2/v2/auth"
    assert flow.scopes == [GMAIL_READONLY, GMAIL_COMPOSE]
    q = flow.query
    assert q["client_id"] == rig.env.settings.client_id and q["redirect_uri"] == rig.env.settings.redirect_uri
    assert (q["response_type"], q["code_challenge_method"], q["include_granted_scopes"]) == ("code", "S256", "true")
    assert (
        q["access_type"] == "offline"
        and q["prompt"] == "consent"
        and len(q["state"]) >= 16
        and len(q["code_challenge"]) == 43
    )
    assert "client_secret" not in q and "code_verifier" not in q and rig.env.settings.client_secret not in flow.url
    assert rig.env.google.calls == []  # nothing reaches Google when a flow starts


def test_ADR35_L3_FR_CON_02_start_asks_only_for_what_is_missing_and_null_when_nothing_is() -> None:
    rig = Rig(connect_at=None)
    rig.env.connect(OWNER, "gmail", [GMAIL_READONLY])
    flow = begin(rig, "gmail", ("read", "search", "send"))
    assert flow.scopes == [GMAIL_SEND] and flow.query["include_granted_scopes"] == "true"
    response = post(rig, "start", {"user_id": OWNER, "connector": "gmail", "capabilities": ["read", "search"]})
    assert (response.status_code, response.json()) == (200, {"authorize_url": None})
    assert rig.runtime._consent_service()._flows.keys() == {flow.state}, "no flow was made for the null answer"
    other = begin(rig, "gmail", ("read",), user=OTHER)  # another person's grant is not this person's
    assert other.scopes == [GMAIL_READONLY]


@pytest.mark.parametrize(
    ("connector", "capabilities"),
    [
        ("nosuch", ["read"]),
        ("lovable", ["send"]),
        ("gmail", ["list"]),
        ("meeting_host", ["read"]),
        ("gmail", ["admin"]),
    ],
)
def test_ADR35_L3_FR_CON_02_an_unknown_connector_or_capability_is_422(connector: str, capabilities: list[str]) -> None:
    rig = Rig(connect_at=None)
    response = post(rig, "start", {"user_id": OWNER, "connector": connector, "capabilities": capabilities})
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.runtime._consent_service()._flows == {}


def test_ADR35_L3_FR_CON_02_every_start_has_its_own_state_and_challenge() -> None:
    rig = Rig(connect_at=None)
    a, b = begin(rig), begin(rig)
    assert a.state != b.state and a.query["code_challenge"] != b.query["code_challenge"]


# ---- callback: the happy path, the exchange, the stored grant ---------------------------------


def test_ADR35_L3_FR_CON_02_callback_exchanges_server_side_stores_and_answers_lines_and_parts() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig, "gmail", ("read", "write"))
    response = finish(rig, flow)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert set(answer) == {"connector", "scope_lines", "parts"} and answer["connector"] == "gmail"
    assert answer["parts"] == [{"type": "connection.established", "connector": "gmail", "user_id": OWNER}]
    assert answer["scope_lines"] and all(isinstance(line, str) and line for line in answer["scope_lines"])
    assert stored(rig) == [(OWNER, "gmail")]
    (exchange,) = rig.env.google.exchange_calls()  # PKCE: Google checked the verifier against the challenge
    assert s256(exchange["code_verifier"]) == flow.query["code_challenge"]
    assert exchange["redirect_uri"] == rig.env.settings.redirect_uri
    assert rig.runtime._broker.get().granted_scopes(OWNER, "gmail") == {GMAIL_READONLY, GMAIL_COMPOSE}
    assert not any(p["type"] == "connection.consented" for p in answer["parts"])  # CR-13: tilo-api writes it


def test_ADR35_L3_FR_CON_02_a_partial_grant_connects_only_what_was_granted() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig, "gmail", ("read", "write"))
    answer = finish(rig, flow, granted=[GMAIL_READONLY]).json()
    assert len(answer["scope_lines"]) == 1 and "draft" not in answer["scope_lines"][0].lower()
    assert rig.runtime._broker.get().granted_scopes(OWNER, "gmail") == {GMAIL_READONLY}
    assert begin(rig, "gmail", ("read", "write")).scopes == [GMAIL_COMPOSE]  # a later action asks again


def test_ADR35_L3_FR_CON_02_the_calendar_and_drive_grants_grow_the_one_person_grant() -> None:
    rig = Rig(connect_at=None)
    assert finish(rig, begin(rig, "google_calendar", ("read",))).json()["connector"] == "google_calendar"
    drive = finish(rig, begin(rig, "google_drive", ("write",))).json()
    assert drive["connector"] == "google_drive" and stored(rig) == [(OWNER, "google_calendar"), (OWNER, "google_drive")]
    assert begin(rig, "google_calendar", ("read", "write")).scopes == [CALENDAR_EVENTS_OWNED]
    assert CALENDAR_READONLY in rig.runtime._broker.get().granted_scopes(OWNER, "google_calendar")
    assert DRIVE_FILE in rig.runtime._broker.get().granted_scopes(OWNER, "google_drive")


def test_ADR35_L3_FR_CON_02_incremental_connects_leave_every_record_able_to_refresh() -> None:
    """Review item 4: Google gives a refresh token to a later consent only when asked (`prompt=consent`), so the 2nd
    and 3rd person connector must each hold one. The fake models Google: no prompt, no refresh token."""
    rig = Rig(connect_at=None)
    for connector, capabilities in (("gmail", ("read",)), ("google_drive", ("write",)), ("google_calendar", ("read",))):
        flow = begin(rig, connector, capabilities)
        asked = flow.query.get("prompt") == "consent" or not stored(rig)  # a first consent always gets one
        code = rig.env.google.issue_code(
            flow.scopes, challenge=flow.query["code_challenge"], redirect_uri=flow.query["redirect_uri"], refresh=asked
        )
        assert post(rig, "callback", {"user_id": OWNER, "state": flow.state, "code": code}).status_code == 200
    broker = rig.runtime._broker.get()
    rig.env.clock.advance(4000)  # every access token has lapsed: each record must refresh
    for connector, scope in (
        ("gmail", GMAIL_READONLY),
        ("google_drive", DRIVE_FILE),
        ("google_calendar", CALENDAR_READONLY),
    ):
        assert broker.access_token_for_adapter(OWNER, connector, required_scopes=[scope])
    assert len(rig.env.google.refresh_calls()) == 3


def test_ADR35_L3_FR_CON_02_one_connector_failing_mid_disconnect_never_hides_what_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review item 3: an exception for one connector is caught per connector; the answer carries every part gathered,
    revoked_at_provider is false and an alert part marks the revoke as pending."""
    rig = Rig(connect_at=None)
    person_grant(rig)
    broker = rig.runtime._broker.get()
    real = broker.disconnect

    def flaky(user_id: str, connector: str, **kw: Any) -> Any:
        if connector == "google_drive":
            raise RuntimeError("store down " + user_id)
        return real(user_id, connector, **kw)

    monkeypatch.setattr(broker, "disconnect", flaky)
    response = post(rig, "disconnect", {"user_id": OWNER, "connector": "gmail"})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["revoked_at_provider"] is False
    types = sorted((p["type"], p.get("connector", "")) for p in answer["parts"])
    assert ("connection.revoked", "gmail") in types and ("connection.revoked", "google_calendar") in types
    assert [p["type"] for p in answer["parts"]].count("alert.raised") >= 1
    assert stored(rig) == [(OWNER, "google_drive")]  # what failed is still there for the next disconnect
    assert "store down" not in response.text


def test_ADR35_L3_FR_CON_02_each_distinct_token_of_the_person_group_is_revoked_once() -> None:
    """Review item 2: connectors holding tokens of different consents or accounts are all revoked, none twice."""
    rig = Rig(connect_at=None)
    person_grant(rig)
    held = set(rig.env.google.live_refresh)
    assert len(held) == 3
    post(rig, "disconnect", {"user_id": OWNER, "connector": "gmail"})
    assert sorted(rig.env.google.revoked) == sorted(held) and rig.env.google.live_refresh == {}


# ---- callback: refusals (LC-05) ---------------------------------------------------------------


def assert_start_again(rig: Rig, response: Any) -> None:
    assert (response.status_code, response.json()) == (400, {"error": "start_again"})
    assert stored(rig) == []


def test_ADR35_L3_FR_CON_02_a_state_is_single_use() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig)
    assert finish(rig, flow).status_code == 200
    rig.env.store.delete(OWNER, "gmail")
    assert_start_again(rig, finish(rig, flow))  # a replay of the spent state, with a fresh valid code
    assert len(rig.env.google.exchange_calls()) == 1, "the replay exchanged nothing"


def test_ADR35_L3_FR_CON_02_an_unknown_or_expired_state_is_start_again_and_exchanges_nothing() -> None:
    rig = Rig(connect_at=None)
    assert_start_again(rig, post(rig, "callback", {"user_id": OWNER, "state": "z" * 43, "code": "abc"}))
    flow = begin(rig)
    rig.env.clock.advance(601)
    assert_start_again(rig, finish(rig, flow))
    assert rig.env.google.exchange_calls() == []
    fresh = begin(rig)
    rig.env.clock.advance(599)
    assert finish(rig, fresh).status_code == 200


def test_ADR35_L3_FR_CON_02_another_persons_state_never_binds_a_google_account() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig, user=OWNER)
    stolen = finish(rig, flow, user=OTHER)
    assert_start_again(rig, stolen)
    assert rig.env.google.exchange_calls() == [] and rig.env.emitted == []
    assert_start_again(rig, finish(rig, flow, user=OWNER))  # whoever presents a state spends it (fail closed)
    assert rig.env.google.exchange_calls() == []


def test_ADR35_L3_FR_CON_02_a_flow_lost_with_an_instance_is_start_again() -> None:
    first, second = Rig(connect_at=None), Rig(connect_at=None)
    flow = begin(first)
    assert_start_again(second, finish(second, flow))
    assert second.env.google.exchange_calls() == []


def test_ADR35_L3_FR_CON_02_denial_is_not_granted_and_spends_the_state_without_an_exchange() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig)
    response = post(rig, "callback", {"user_id": OWNER, "state": flow.state, "error": "access_denied"})
    assert (response.status_code, response.json()) == (400, {"error": "not_granted"})
    assert stored(rig) == [] and rig.env.google.calls == []
    assert_start_again(rig, finish(rig, flow))  # the state is spent


def test_ADR35_L3_FR_CON_02_a_grant_of_none_of_the_asked_scopes_is_not_granted_and_the_token_is_revoked() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig, "gmail", ("read",))
    response = finish(rig, flow, granted=[DRIVE_FILE])
    assert (response.status_code, response.json()) == (400, {"error": "not_granted"})
    assert stored(rig) == [] and len(rig.env.google.calls_to(REVOKE_URL)) == 1


def test_ADR35_L3_FR_CON_02_a_failed_exchange_keeps_nothing_and_says_nothing_about_why() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig)
    code = "never-issued-" + secrets.token_hex(6)
    response = post(rig, "callback", {"user_id": OWNER, "state": flow.state, "code": code})
    assert_start_again(rig, response)
    assert code not in response.text and rig.env.google.calls_to(REVOKE_URL) == []


def test_ADR35_L3_FR_CON_02_a_kms_failure_at_store_keeps_nothing_and_discards_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig)
    code = code_for(rig, flow)

    def broken(*args: Any, **kwargs: Any) -> bytes:
        raise RuntimeError("kms unavailable " + code)

    monkeypatch.setattr(rig.env.kms, "encrypt", broken)
    response = post(rig, "callback", {"user_id": OWNER, "state": flow.state, "code": code})
    assert_start_again(rig, response)
    assert code not in response.text and len(rig.env.google.calls_to(REVOKE_URL)) == 1


def test_ADR35_L3_FR_CON_02_a_discarded_token_is_not_revoked_when_a_live_grant_shares_it() -> None:
    rig = Rig(connect_at=None)
    rig.env.connect(OWNER, "gmail", [GMAIL_READONLY])
    flow = begin(rig, "google_drive", ("write",))
    assert finish(rig, flow, granted=[GMAIL_READONLY]).json() == {"error": "not_granted"}
    assert rig.env.google.calls_to(REVOKE_URL) == [] and stored(rig) == [(OWNER, "gmail")]


# ---- meeting_host: the same routes for the bot account (MH-C1) --------------------------------


def test_ADR35_L3_FR_CON_02_meeting_host_connects_through_the_same_routes_with_its_one_scope() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig, "meeting_host", ("send",))
    assert flow.scopes == [CALENDAR_EVENTS_OWNED]
    answer = finish(rig, flow).json()
    assert answer["connector"] == "meeting_host" and len(answer["scope_lines"]) == 1
    assert answer["parts"] == [{"type": "connection.established", "connector": "meeting_host", "user_id": OWNER}]
    assert rig.call("status", {"user_id": OWNER}).json() == {"state": "connected", "scope_ok": True}


def test_ADR35_L3_FR_CON_02_meeting_host_refuses_a_persons_own_account_as_wrong_account() -> None:
    rig = Rig(connect_at=None)
    flow = begin(rig, "meeting_host", ("send",))
    response = finish(rig, flow, granted=[CALENDAR_EVENTS_OWNED, GMAIL_READONLY])  # MH-C1: more than the bot's scope
    assert (response.status_code, response.json()) == (400, {"error": "wrong_account"})
    assert stored(rig) == [] and rig.env.google.calls_to(REVOKE_URL) == []


# ---- disconnect -------------------------------------------------------------------------------


def person_grant(rig: Rig) -> None:
    rig.env.connect(OWNER, "gmail", [GMAIL_READONLY, GMAIL_SEND])
    rig.env.connect(OWNER, "google_drive", [DRIVE_FILE])
    rig.env.connect(OWNER, "google_calendar", [CALENDAR_READONLY, CALENDAR_EVENTS_OWNED])


def test_ADR35_L3_FR_CON_02_disconnecting_one_person_connector_revokes_the_shared_grant_for_all_three() -> None:
    rig = Rig(connect_at=None)
    person_grant(rig)
    response = post(rig, "disconnect", {"user_id": OWNER, "connector": "google_drive"})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["revoked_at_provider"] is True
    assert revoked_types(answer) == [
        ("connection.revoked", "gmail"),
        ("connection.revoked", "google_calendar"),
        ("connection.revoked", "google_drive"),
    ]
    assert all(p["user_id"] == OWNER for p in answer["parts"])
    assert stored(rig) == [] and len(rig.env.google.calls_to(REVOKE_URL)) == 3  # every DISTINCT stored token
    assert rig.runtime.connection_views(OWNER) == {"views": []}
    again = post(rig, "disconnect", {"user_id": OWNER, "connector": "gmail"}).json()
    assert again == {"revoked_at_provider": False, "parts": []}  # idempotent


def test_ADR35_L3_FR_CON_02_disconnect_leaves_the_bot_grant_and_the_bot_disconnect_leaves_the_person() -> None:
    rig = Rig(connect_at=None)
    person_grant(rig)
    rig.env.connect(OWNER, "meeting_host", [CALENDAR_EVENTS_OWNED])
    post(rig, "disconnect", {"user_id": OWNER, "connector": "gmail"})
    assert stored(rig) == [(OWNER, "meeting_host")]
    rig2 = Rig(connect_at=None)
    person_grant(rig2)
    rig2.env.connect(OWNER, "meeting_host", [CALENDAR_EVENTS_OWNED])
    answer = post(rig2, "disconnect", {"user_id": OWNER, "connector": "meeting_host"}).json()
    assert answer["revoked_at_provider"] is True and revoked_types(answer) == [("connection.revoked", "meeting_host")]
    assert len(stored(rig2)) == 3


def test_ADR35_L3_FR_CON_02_disconnect_touches_only_the_requests_user_and_an_unknown_connector_is_422() -> None:
    rig = Rig(connect_at=None)
    person_grant(rig)
    rig.env.connect(OTHER, "gmail", [GMAIL_READONLY])
    post(rig, "disconnect", {"user_id": OWNER, "connector": "gmail"})
    assert stored(rig) == [(OTHER, "gmail")]
    for connector in ("nosuch", "lovable"):
        response = post(rig, "disconnect", {"user_id": OTHER, "connector": connector})
        assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert stored(rig) == [(OTHER, "gmail")]


def test_ADR35_L3_FR_CON_02_a_failed_revoke_is_kept_for_a_retry_and_answers_false_with_an_alert() -> None:
    rig = Rig(connect_at=None)
    person_grant(rig)
    rig.env.google.revoke_mode = "unavailable"
    answer = post(rig, "disconnect", {"user_id": OWNER, "connector": "gmail"}).json()
    assert answer["revoked_at_provider"] is False and stored(rig) == []
    assert [p["type"] for p in answer["parts"]].count("alert.raised") >= 1
    assert all(set(p) <= {"type", "connector", "user_id", "alert_id"} for p in answer["parts"])


# ---- parts, secrecy ---------------------------------------------------------------------------


def test_ADR35_L3_FR_CON_02_parts_of_another_user_or_kind_are_dropped_and_capped() -> None:
    rig = Rig(connect_at=None)
    runtime = rig.runtime
    with runtime.capture(OWNER, wide=True) as parts:
        runtime._emit({"type": "connection.revoked", "authz": None, "data": {"connector": "gmail"}, "user_id": OTHER})
        for kind in ("connection.consented", "connection.requested", "connection.disconnected"):
            runtime._emit({"type": kind, "authz": None, "data": {"connector": "gmail"}, "user_id": OWNER})
        for _ in range(40):
            runtime._emit(
                {"type": "connection.established", "authz": None, "data": {"connector": "gmail"}, "user_id": OWNER}
            )
    assert len(parts.items) == 16 and {p["user_id"] for p in parts.items} == {OWNER}
    with runtime.capture(OWNER) as narrow:  # the meeting-host routes keep the narrow shape
        for connector, kind in (("gmail", "connection.revoked"), ("meeting_host", "connection.established")):
            runtime._emit({"type": kind, "authz": None, "data": {"connector": connector}, "user_id": OWNER})
    assert narrow.items == []


def test_ADR35_L3_FR_CON_02_no_secret_is_in_any_answer_or_log_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    rig = Rig(connect_at=None)
    start = post(rig, "start", {"user_id": OWNER, "connector": "gmail", "capabilities": ["read", "send"]})
    flow = parse_auth_url(start.json()["authorize_url"])
    bad_code = "bad-" + secrets.token_hex(8)
    texts = [post(rig, "callback", {"user_id": OWNER, "state": flow.state, "code": bad_code}).text]
    flow2 = begin(rig, "gmail", ("read", "send"))
    good = finish(rig, flow2)
    texts += [good.text, post(rig, "disconnect", {"user_id": OWNER, "connector": "gmail"}).text]
    exchanges = rig.env.google.exchange_calls()  # the refused one and the good one
    assert len(exchanges) == 2
    verifiers, codes = [e["code_verifier"] for e in exchanges], [e["code"] for e in exchanges]
    tokens = list(rig.env.google.issued_access) + list(rig.env.google.live_refresh) + list(rig.env.google.revoked)
    secret_values = [rig.env.secrets["client_secret"], *verifiers, *codes, bad_code, *tokens]
    assert leaks(start.text, [rig.env.secrets["client_secret"], *verifiers, *tokens]) == []
    blob = "\n".join(texts) + "\n" + caplog.text
    assert leaks(blob, [*secret_values, flow.state, flow2.state]) == []
    assert good.status_code == 200 and caplog.text.count("Traceback") == 0
