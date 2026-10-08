"""LIVE-GAPS-1b (FR-CON-02, FR-ACC-03, FR-ACC-04): `GET /v1/connectors`, the signed-in person's connectors with their
connection state, read through the token broker.

PRD sources: FR-CON-01/02 (PRD 12.1: declared connectors; one OAuth connection per person and connector, the broker the
only holder of tokens, SEC-02); docs/prd-supplement-design-2026-10-06.md FR-ACC-03 ("Account, sync status ... scopes")
and FR-ACC-04 ("A warning ... shows 3 days ahead"); SEC-02 (no token leaves the broker), PE-22 (no-store).

Pinned interface (the ticket's decided spec):

    GET /v1/connectors               auth: `deps.get_current_principal`; owner is `Principal.user_id` and nothing else
    200 {"connectors": [{"id", "name", "auth", "state", "scopes", "expires_at"}], "state_known": bool}
        connectors   one per entry of `deps.get_connector_registry()`, in registry order; id/name/auth: the registry's
        state        "connected" (broker state `connected` and expires_at more than 3 days away); "attention" (a stored
                     state other than `connected`: expiring, expired, revoked, needs_reconnect; or expires_at within 3
                     days, past ones included: FR-ACC-04); else "available"
        scopes       the scopes granted to THIS person (list of strings), [] when none
        expires_at   RFC 3339 string of the stored record, null when there is none
        state_known  true when every connector's state was read; false when the broker is unwired
                     (`deps.get_token_broker` raises HTTP 503 today) or a read failed
    Unwired broker: 200, every connector "available", scopes [], expires_at null, state_known false (never 500/503).
    A broker/store error for one connector: that connector "available", the rest as usual, 200, state_known false, and
    no error text in the body, the headers or the logs.
    Allowlist: nothing else of the stored record is ever in the answer (no token, refresh token, sealed ciphertext,
    wrapped key, nonce, client secret). `Cache-Control: no-store`. No query parameter picks another person.

How the tests install a broker (the seam the builder must resolve the broker through): a REAL
`tilo_connectors.tokens.TokenBroker` over a spy `TokenStore` wrapping `InMemoryTokenStore` (a `FakeKms`, a fake HTTP
client that records any call, a real-time clock), installed with
`app.dependency_overrides[deps.get_token_broker] = lambda: broker`. Records are written the way production writes them
(`broker.store_tokens(...)`), or planted straight into the store (`store.put`) for the states the broker only writes in
production on a refresh failure. Failures are injected in the STORE, so they reach the route whichever public broker
method it uses. The route is a pure read: no HTTP call, no store write, no event.

Ambiguities resolved (listed in the report): PRD supplement FR-ACC-04 says "3 days ahead"; the boundary is tested at
3 days plus/minus one hour, never at exactly 3 days. `needs_reconnect` is the stored spelling used for "needs
reconnect". For a broker-connected record near expiry the scopes are the granted ones (the broker's
`granted_scopes`); for a stored state other than `connected` the scopes are not asserted (the broker reports none).

No network, no model, no cloud credentials. Sentinel secrets are assembled at runtime.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from _api_lib import REPO_ROOT
from fastapi import HTTPException
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import app, deps
from tilo_connectors._time import format_ts
from tilo_connectors.registry import ConnectorRegistry, load_registry
from tilo_connectors.tokens import (
    FakeKms,
    InMemoryTokenStore,
    KmsError,
    OAuthSettings,
    TokenBroker,
    TokenError,
)

PATH = "/v1/connectors"
ROW_KEYS = {"id", "name", "auth", "state", "scopes", "expires_at"}
TOP_KEYS = {"connectors", "state_known"}
STATES = {"connected", "attention", "available"}
DAY = 86400
REGISTRY = load_registry(REPO_ROOT / "config" / "connectors.yaml")
ALL_IDS = list(REGISTRY.ids())
OAUTH_IDS = [cid for cid in ALL_IDS if REGISTRY.get(cid)["auth"] == "oauth2"]
ALICE, BOB, CAROL = "u_alice", "u_bob", "u_carol"


def _sentinel(label: str) -> str:
    """A secret-shaped marker assembled at runtime (nothing secret-looking is committed)."""
    return "-".join(["SENTINEL", label, secrets.token_hex(12)])


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(seconds_from_now: float) -> str:
    return format_ts(_now() + timedelta(seconds=seconds_from_now))


def _scope(user: str, connector: str) -> str:
    return f"https://scopes.example.com/{user}/{connector}"  # example.com: a fake host, unique per person and connector


class _Response:
    status_code = 200

    def json(self) -> dict[str, Any]:
        return {}


class _Http:
    """The provider: a recording fake. The list route must never reach it (no refresh, no revoke)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def post(self, url: str, *, data: Any) -> _Response:
        self.calls.append(url)
        return _Response()


class _SpyStore:
    """An `InMemoryTokenStore` that records every call and fails reads of chosen connectors on demand."""

    def __init__(self) -> None:
        self.inner = InMemoryTokenStore()
        self.calls: list[tuple[str, str, str | None]] = []
        self.fail: dict[str, Exception] = {}

    def put(self, user_id: str, connector: str, record: dict[str, Any]) -> None:
        self.calls.append(("put", user_id, connector))
        self.inner.put(user_id, connector, record)

    def get(self, user_id: str, connector: str) -> dict[str, Any] | None:
        self.calls.append(("get", user_id, connector))
        if connector in self.fail:
            raise self.fail[connector]
        return self.inner.get(user_id, connector)

    def delete(self, user_id: str, connector: str) -> None:
        self.calls.append(("delete", user_id, connector))
        self.inner.delete(user_id, connector)

    def connectors_of(self, user_id: str) -> list[str]:
        self.calls.append(("connectors_of", user_id, None))
        return self.inner.connectors_of(user_id)


class Rig:
    """The real `tilo_api.app` with a real token broker over a spy store, the signed-in person set by `user`."""

    def __init__(self) -> None:
        self.client_secret = _sentinel("client-secret")
        self.store, self.http, self.events = _SpyStore(), _Http(), []
        self.broker = TokenBroker(
            store=self.store,
            kms=FakeKms(),
            http=self.http,
            settings=OAuthSettings(client_id="client-example", client_secret=self.client_secret),
            clock=lambda: _ts(0),
            emit=self.events.append,
        )
        self.user = ALICE
        self.secrets: list[str] = [self.client_secret]
        ov = app.dependency_overrides
        ov[deps.get_current_principal] = lambda: deps.Principal(user_id=self.user, role="owner", full_session=True)
        ov[deps.get_token_broker] = lambda: self.broker
        self.client = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        app.dependency_overrides.clear()

    def connect(
        self, user: str, connector: str, *, lifetime_s: int = 30 * DAY, scopes: list[str] | None = None
    ) -> None:
        """What the OAuth callback does: seal a token response and store it for this person and connector."""
        access, refresh = _sentinel("access"), _sentinel("refresh")
        self.secrets += [access, refresh]
        self.broker.store_tokens(
            user,
            connector,
            {
                "access_token": access,
                "refresh_token": refresh,
                "scope": " ".join(scopes if scopes is not None else [_scope(user, connector)]),
                "expires_in": lifetime_s,
            },
        )

    def plant(self, user: str, connector: str, record: dict[str, Any]) -> None:
        self.store.inner.put(user, connector, record)

    def sealed(self, user: str, connector: str) -> dict[str, Any]:
        record = self.store.inner.get(user, connector)
        assert record is not None
        return record

    def settle(self) -> None:
        """Setup done: from here every store call, provider call and event is the route's."""
        self.store.calls.clear()
        self.http.calls.clear()
        self.events.clear()

    def get(self, path: str = PATH, **kwargs: Any) -> Any:
        return self.client.get(path, **kwargs)

    def ask(self, **kwargs: Any) -> dict[str, Any]:
        response = self.get(**kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    def assert_read_only(self) -> None:
        writes = [c for c in self.store.calls if c[0] in ("put", "delete")]
        assert writes == [], "the list route wrote to the token store"
        assert self.http.calls == [], "the list route called the provider (refresh or revoke)"
        assert self.events == [], "the list route emitted an event"


@pytest.fixture(autouse=True)
def _not_deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV", "TILO_JUDGE_LIVE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def rig():
    r = Rig()
    yield r
    r.close()


def rows(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in body["connectors"]}


def whole_answer(response: Any) -> str:
    """Everything a client could read: body, header names and values, cookies."""
    headers = " ".join(f"{k}: {v}" for k, v in response.headers.items())
    return response.text + " " + headers + " " + json.dumps(dict(response.cookies))


def assert_clean(response: Any, needles: list[str]) -> None:
    text = whole_answer(response)
    leaked = [n for n in needles if n and n in text]
    assert leaked == [], "secret material reached the answer"


def assert_all_available(body: dict[str, Any], ids: list[str] | None = None) -> None:
    assert [r["id"] for r in body["connectors"]] == (ids if ids is not None else ALL_IDS)
    for row in body["connectors"]:
        assert row["state"] == "available", row
        assert row["scopes"] == [], row
        assert row["expires_at"] is None, row


# --- shape, order, registry (FR-CON-01/02, FR-ACC-03) -------------------------------------------------------------


def test_FR_CON_02_LIVE_GAPS_1b_shape_and_registry_order(rig: Rig) -> None:
    """Given a signed-in person with no connection, When they GET /v1/connectors, Then 200 with exactly the two top
    keys, one row per registry entry in registry order, each row exactly the six allowlisted keys, id/name/auth the
    registry's own."""
    body = rig.ask()
    assert set(body) == TOP_KEYS
    assert isinstance(body["state_known"], bool)
    assert [r["id"] for r in body["connectors"]] == ALL_IDS
    assert len(ALL_IDS) >= 4  # gmail, google_drive, google_calendar, ... the shipped catalogue
    for row in body["connectors"]:
        assert set(row) == ROW_KEYS
        declared = REGISTRY.get(row["id"])
        assert (row["name"], row["auth"]) == (declared["name"], declared["auth"])
        assert row["state"] in STATES
        assert isinstance(row["scopes"], list)
    rig.assert_read_only()


def test_FR_CON_02_LIVE_GAPS_1b_answer_follows_the_registry_dependency_and_its_order(rig: Rig) -> None:
    """The list is the `deps.get_connector_registry` seam's, in that registry's order (not the file's)."""
    declared = {cid: REGISTRY.get(cid) for cid in ("google_calendar", "gmail")}  # reversed against the file
    app.dependency_overrides[deps.get_connector_registry] = lambda: ConnectorRegistry(declared)
    rig.connect(ALICE, "gmail")
    rig.settle()
    body = rig.ask()
    assert [r["id"] for r in body["connectors"]] == ["google_calendar", "gmail"]
    assert rows(body)["gmail"]["state"] == "connected"
    assert rows(body)["google_calendar"]["state"] == "available"


def test_FR_CON_02_LIVE_GAPS_1b_person_with_no_grant_sees_every_connector_available(rig: Rig) -> None:
    """A person who never connected anything: every row available, scopes [], expires_at null, state read."""
    rig.connect(BOB, "gmail")  # somebody else's grant exists
    rig.settle()
    rig.user = CAROL
    body = rig.ask()
    assert_all_available(body)
    assert body["state_known"] is True
    rig.assert_read_only()


# --- states (FR-ACC-03, FR-ACC-04) ------------------------------------------------------------------------------


def test_FR_CON_02_LIVE_GAPS_1b_connected_row_has_granted_scopes_and_expiry(rig: Rig) -> None:
    """Given gmail connected with two scopes, Then gmail is `connected` with exactly those scopes (no duplicates) and
    the stored `expires_at`; the other connectors stay available."""
    granted = [_scope(ALICE, "gmail") + "/read", _scope(ALICE, "gmail") + "/send"]
    rig.connect(ALICE, "gmail", scopes=granted)
    stored_expiry = rig.sealed(ALICE, "gmail")["expires_at"]
    rig.settle()
    response = rig.get()
    assert response.status_code == 200
    body = response.json()
    gmail = rows(body)["gmail"]
    assert gmail["state"] == "connected"
    assert sorted(gmail["scopes"]) == sorted(granted)
    assert all(isinstance(s, str) for s in gmail["scopes"])
    assert datetime.fromisoformat(gmail["expires_at"].replace("Z", "+00:00")) == datetime.fromisoformat(
        stored_expiry.replace("Z", "+00:00")
    )
    assert all(r["state"] == "available" for cid, r in rows(body).items() if cid != "gmail")
    assert body["state_known"] is True
    rig.assert_read_only()


@pytest.mark.parametrize(
    ("lifetime_s", "state"),
    [
        (30 * DAY, "connected"),
        (3 * DAY + 3600, "connected"),
        (3 * DAY - 3600, "attention"),
        (2 * DAY, "attention"),
        (3600, "attention"),
    ],
)
def test_FR_ACC_04_LIVE_GAPS_1b_expiry_within_3_days_is_attention(rig: Rig, lifetime_s: int, state: str) -> None:
    """FR-ACC-04: 'The warning shows 3 days ahead.' A connected record whose expires_at is within 3 days is
    `attention`; further out it is `connected`. The granted scopes and the expiry are still shown."""
    rig.connect(ALICE, "gmail", lifetime_s=lifetime_s)
    expected_scopes = [_scope(ALICE, "gmail")]
    rig.settle()
    gmail = rows(rig.ask())["gmail"]
    assert gmail["state"] == state
    assert gmail["scopes"] == expected_scopes
    assert gmail["expires_at"] is not None
    rig.assert_read_only()


def test_FR_ACC_04_LIVE_GAPS_1b_a_past_expiry_is_attention_and_is_never_refreshed(rig: Rig) -> None:
    """A connected record whose expires_at has passed is `attention`; reading the list never refreshes it at the
    provider (a list is not an adapter call)."""
    rig.connect(ALICE, "gmail")
    record = rig.sealed(ALICE, "gmail")
    rig.plant(ALICE, "gmail", {**record, "expires_at": _ts(-DAY)})
    rig.settle()
    gmail = rows(rig.ask())["gmail"]
    assert gmail["state"] == "attention"
    rig.assert_read_only()


@pytest.mark.parametrize("stored_state", ["expiring", "expired", "revoked", "needs_reconnect"])
def test_FR_ACC_04_LIVE_GAPS_1b_stored_non_connected_state_is_attention(rig: Rig, stored_state: str) -> None:
    """A record stored in any state other than `connected` (the connection ended or must be redone) is `attention`,
    never `connected`, even when its expires_at is far in the future."""
    rig.plant(ALICE, "gmail", {"v": 1, "state": stored_state, "scopes": [], "expires_at": _ts(30 * DAY)})
    rig.settle()
    gmail = rows(rig.ask())["gmail"]
    assert gmail["state"] == "attention"
    assert gmail["state"] != "connected"
    assert isinstance(gmail["scopes"], list)
    rig.assert_read_only()


def test_FR_ACC_04_LIVE_GAPS_1b_the_brokers_expired_marker_is_attention_with_no_scopes(rig: Rig) -> None:
    """The record the broker leaves when the provider will not refresh a grant (`state: expired`, no scopes, no
    expiry): `attention`, scopes [], expires_at null."""
    rig.plant(ALICE, "google_drive", {"v": 1, "state": "expired", "scopes": [], "expires_at": None})
    rig.settle()
    drive = rows(rig.ask())["google_drive"]
    assert (drive["state"], drive["scopes"], drive["expires_at"]) == ("attention", [], None)


def test_FR_CON_02_LIVE_GAPS_1b_a_disconnected_connector_is_available_again(rig: Rig) -> None:
    """Given gmail connected and then disconnected (the broker revokes and deletes the record), Then gmail is not
    `connected`: it is `available` with no scopes and no expiry."""
    rig.connect(ALICE, "gmail")
    assert rows(rig.ask())["gmail"]["state"] == "connected"
    rig.broker.disconnect(ALICE, "gmail")
    assert rig.store.inner.get(ALICE, "gmail") is None
    rig.settle()
    gmail = rows(rig.ask())["gmail"]
    assert (gmail["state"], gmail["scopes"], gmail["expires_at"]) == ("available", [], None)
    rig.assert_read_only()


# --- whose state (SEC-02, owner = the signed-in person only) ------------------------------------------------------


def test_FR_CON_02_LIVE_GAPS_1b_two_people_never_see_each_others_state_or_scopes(rig: Rig) -> None:
    """Alice has gmail, Bob has google_drive, each with scopes of their own. Each sees only their own row connected and
    only their own scopes; neither answer contains the other's scope strings."""
    rig.connect(ALICE, "gmail")
    rig.connect(BOB, "google_drive")
    rig.settle()
    rig.user = ALICE
    mine = rig.get()
    rig.user = BOB
    his = rig.get()
    assert mine.status_code == his.status_code == 200
    assert {cid: r["state"] for cid, r in rows(mine.json()).items() if r["state"] != "available"} == {
        "gmail": "connected"
    }
    assert {cid: r["state"] for cid, r in rows(his.json()).items() if r["state"] != "available"} == {
        "google_drive": "connected"
    }
    assert rows(mine.json())["gmail"]["scopes"] == [_scope(ALICE, "gmail")]
    assert rows(his.json())["google_drive"]["scopes"] == [_scope(BOB, "google_drive")]
    assert_clean(mine, [_scope(BOB, "google_drive"), BOB])
    assert_clean(his, [_scope(ALICE, "gmail"), ALICE])
    rig.assert_read_only()


@pytest.mark.parametrize(
    "query",
    [
        f"?user_id={BOB}",
        f"?person={BOB}&org=org_other",
        f"?owner={BOB}&user={BOB}&uid={BOB}&principal={BOB}&as={BOB}",
        f"?user_id={BOB}&user_id={CAROL}",
        "?user_id=",
    ],
)
def test_FR_CON_02_LIVE_GAPS_1b_no_query_parameter_names_another_person(rig: Rig, query: str) -> None:
    """The owner is the principal and nothing else: a user/person/org parameter is ignored, never honoured. The answer
    is the plain one, and the store was only ever asked about the signed-in person."""
    rig.connect(ALICE, "gmail")
    rig.connect(BOB, "google_drive")
    rig.settle()
    plain = rig.get()
    rig.store.calls.clear()
    with_query = rig.get(PATH + query)
    assert plain.status_code == with_query.status_code == 200
    assert with_query.json() == plain.json()
    assert rows(with_query.json())["google_drive"]["state"] == "available"
    assert_clean(with_query, [_scope(BOB, "google_drive")])
    assert {c[1] for c in rig.store.calls} == {ALICE}


def test_FR_CON_02_LIVE_GAPS_1b_headers_do_not_pick_a_person_either(rig: Rig) -> None:
    """A user id in a header is no more a way in than one in the query."""
    rig.connect(BOB, "google_drive")
    rig.settle()
    response = rig.get(headers={"X-User-Id": BOB, "X-Tilo-User": BOB, "X-Forwarded-User": BOB})
    assert response.status_code == 200
    assert_all_available(response.json())
    assert {c[1] for c in rig.store.calls} <= {ALICE}


def test_FR_CON_02_LIVE_GAPS_1b_signed_out_is_401_and_reads_nothing(rig: Rig) -> None:
    """No sign-in: 401 (the principal dependency's own refusal), no connector list, no store read."""
    rig.connect(ALICE, "gmail")
    rig.settle()
    del app.dependency_overrides[deps.get_current_principal]
    response = rig.get()
    assert response.status_code == 401
    assert "connectors" not in response.text
    assert rig.store.calls == []
    assert_clean(response, [_scope(ALICE, "gmail")])


# --- nothing but the allowlist leaves (SEC-02, the most important group) -------------------------------------------


def test_FR_CON_02_LIVE_GAPS_1b_no_token_secret_or_sealed_field_is_ever_in_the_answer(rig: Rig) -> None:
    """Plant sentinel secrets everywhere a record can hold one: the real sealed gmail record (access and refresh token
    sentinels inside the ciphertext, plus its wrapped key and nonce), a drive record with plaintext token / refresh /
    client-secret / unknown fields beside the allowed ones, the broker's client secret, and a record of a connector
    that is not in the registry. None of it reaches the body, the headers or the cookies; each row has exactly the six
    allowlisted keys."""
    rig.connect(ALICE, "gmail")
    sealed = rig.sealed(ALICE, "gmail")
    extra = [_sentinel(label) for label in ("plain-access", "plain-refresh", "plain-client", "unknown-field", "ghost")]
    rig.plant(
        ALICE,
        "google_drive",
        {
            "v": 1,
            "state": "connected",
            "scopes": [_scope(ALICE, "google_drive")],
            "expires_at": _ts(30 * DAY),
            "access_token": extra[0],
            "refresh_token": extra[1],
            "client_secret": extra[2],
            "account_email": extra[3] + "@example.com",
            "wrapped_key": extra[3],
            "nonce": extra[3],
            "ciphertext": extra[3],
        },
    )
    rig.plant(ALICE, "ghost_connector", {"v": 1, "state": "connected", "scopes": [extra[4]], "expires_at": _ts(DAY)})
    rig.settle()
    response = rig.get()
    assert response.status_code == 200
    body = response.json()
    assert set(body) == TOP_KEYS
    assert [r["id"] for r in body["connectors"]] == ALL_IDS  # the ghost connector is not listed
    for row in body["connectors"]:
        assert set(row) == ROW_KEYS
    needles = [
        *rig.secrets,
        *extra,
        sealed["ciphertext"],
        sealed["wrapped_key"],
        sealed["nonce"],
        "ghost_connector",
        "access_token",
        "refresh_token",
        "client_secret",
        "wrapped_key",
        "ciphertext",
    ]
    assert_clean(response, needles)
    rig.assert_read_only()


def test_FR_CON_02_LIVE_GAPS_1b_response_is_not_cacheable(rig: Rig) -> None:
    """PE-22: the answer is `Cache-Control: no-store`, with a connection and without one."""
    rig.connect(ALICE, "gmail")
    rig.settle()
    for user in (ALICE, CAROL):
        rig.user = user
        response = rig.get()
        assert response.status_code == 200
        assert "no-store" in response.headers.get("cache-control", "").lower()


# --- unwired broker / failing broker (never 500, never 503) --------------------------------------------------------


def test_FR_CON_02_LIVE_GAPS_1b_unwired_broker_answers_200_all_available_and_not_known(rig: Rig) -> None:
    """Given `deps.get_token_broker` unwired (HTTP 503 today), Then the route still answers 200: every connector
    available, scopes [], expires_at null, state_known false. Never a 500, never a 503."""
    del app.dependency_overrides[deps.get_token_broker]
    with pytest.raises(HTTPException) as unwired:  # the premise: the production default refuses with 503
        deps.get_token_broker()
    assert unwired.value.status_code == 503
    response = rig.get()
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == TOP_KEYS
    assert body["state_known"] is False
    assert_all_available(body)
    for row in body["connectors"]:
        assert set(row) == ROW_KEYS
    assert "no-store" in response.headers.get("cache-control", "").lower()
    assert "not_configured" not in response.text


@pytest.mark.parametrize("error", [RuntimeError, ValueError, OSError, TimeoutError, KeyError, TokenError, KmsError])
def test_FR_CON_02_LIVE_GAPS_1b_one_failing_connector_is_available_and_state_unknown(
    rig: Rig, error: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    """When the broker errors for one connector (any error), Then that connector is `available` with no scopes, the
    other connectors are exactly as without the failure, the answer is 200 with state_known false, and the error text
    (here carrying a sentinel) is nowhere: not in the body, the headers or the logs."""
    caplog.set_level(logging.DEBUG)
    boom = _sentinel("error-text")
    rig.connect(ALICE, "gmail")
    rig.connect(ALICE, "google_calendar")
    rig.connect(ALICE, "google_drive")
    rig.settle()
    healthy = rows(rig.ask())
    rig.store.fail["google_drive"] = error(boom)
    response = rig.get()
    assert response.status_code == 200, response.text
    body = response.json()
    now = rows(body)
    assert body["state_known"] is False
    assert (now["google_drive"]["state"], now["google_drive"]["scopes"], now["google_drive"]["expires_at"]) == (
        "available",
        [],
        None,
    )
    assert healthy["google_drive"]["state"] == "connected"
    for cid in ALL_IDS:
        if cid != "google_drive":
            assert now[cid] == healthy[cid], cid
    assert [r["id"] for r in body["connectors"]] == ALL_IDS
    assert_clean(response, [boom, *rig.secrets])
    assert boom not in caplog.text


def test_FR_CON_02_LIVE_GAPS_1b_every_connector_failing_is_still_200_all_available(rig: Rig) -> None:
    """The whole token store down: 200, every connector available, state_known false, the error text nowhere."""
    boom = _sentinel("store-down")
    rig.connect(ALICE, "gmail")
    rig.settle()
    rig.store.fail = {cid: RuntimeError(boom) for cid in ALL_IDS}
    response = rig.get()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state_known"] is False
    assert_all_available(body)
    assert_clean(response, [boom, *rig.secrets])


# --- invariants (Hypothesis) -------------------------------------------------------------------------------------

_LIFETIMES = st.one_of(st.none(), st.sampled_from([3600, DAY, 2 * DAY, 3 * DAY - 3600, 3 * DAY + 3600, 30 * DAY]))
_GRANTS = st.fixed_dictionaries(
    {u: st.fixed_dictionaries({cid: _LIFETIMES for cid in OAUTH_IDS}) for u in (ALICE, BOB)}
)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(grants=_GRANTS)
def test_FR_CON_02_LIVE_GAPS_1b_property_state_scopes_and_isolation(grants: dict[str, dict[str, int | None]]) -> None:
    """For any grants of two people over the OAuth connectors: ids are always the registry's in order; a person's row is
    `available` iff they have no record, `connected` iff the record expires more than 3 days out, else `attention`;
    scopes are exactly the person's own granted ones (empty when available); nobody ever sees the other's scopes; the
    same request twice gives the same answer; and the route stays read-only."""
    rig = Rig()
    try:
        for user, per_connector in grants.items():
            for cid, lifetime in per_connector.items():
                if lifetime is not None:
                    rig.connect(user, cid, lifetime_s=lifetime)
        rig.settle()
        for user, other in ((ALICE, BOB), (BOB, ALICE)):
            rig.user = user
            response = rig.get()
            assert response.status_code == 200
            body = response.json()
            assert [r["id"] for r in body["connectors"]] == ALL_IDS
            assert body["state_known"] is True
            for row in body["connectors"]:
                assert set(row) == ROW_KEYS
                lifetime = grants[user].get(row["id"])
                if lifetime is None:
                    assert (row["state"], row["scopes"], row["expires_at"]) == ("available", [], None)
                else:
                    assert row["state"] == ("connected" if lifetime > 3 * DAY else "attention")
                    assert row["scopes"] == [_scope(user, row["id"])]
                    assert row["expires_at"] is not None
            assert f"/{other}/" not in response.text
            assert_clean(response, rig.secrets)
            assert rig.get().json() == body
        rig.assert_read_only()
    finally:
        rig.close()
