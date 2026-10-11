"""ADR32A_T4B / FR_MTG_09: POST /internal/connections/views of tilo-connectors (ADR-0032a, HB-01, HB-08, HB-09).

Same rig as the T3 route tests: a fake ID-token verifier, an in-memory record store, a spy KMS and a fake Google. The
route is a store read: the rig must record no KMS call, no Google call, no store write and no event. Every token,
secret and caller identity is assembled at runtime.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any

import pytest
from _meeting_host_lib import CALENDAR_EVENTS_OWNED, OWNER
from test_ADR32_T3_host_routes import AUD, BEFORE, CALLER, NOW, Rig, user_body
from tilo_connectors._schema import host_rpc_validator
from tilo_connectors.host_auth import CertsUnavailable
from tilo_connectors.host_broker import BrokerNotConfigured
from tilo_connectors.host_routes import AUDIENCE_VAR, CALLER_VAR, MAX_BODY_BYTES
from tilo_connectors.registry import load_registry

PATH = "/internal/connections/views"
GMAIL_READ = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
CAL_READ = "https://www.googleapis.com/auth/calendar.readonly"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
ALIEN = "https://www.googleapis.com/auth/" + "x" + secrets.token_hex(3)
FORBIDDEN_KEYS = ("token", "ciphertext", "wrapped", "nonce", "expires_at", "email", "address", "secret", "client", "v")


def views_call(rig: Rig, body: Any = None, *, token: str | None = "good", raw: bytes | None = None) -> Any:
    headers = {} if token is None else {"authorization": f"Bearer {rig.good if token == 'good' else token}"}
    data = raw if raw is not None else json.dumps(user_body() if body is None else body).encode()
    return rig.client.post(PATH, content=data, headers=headers)


def oauth_order() -> list[str]:
    from tilo_connectors.host_routes import _CONFIG

    loaded = load_registry(_CONFIG)
    return [cid for cid in loaded.ids() if loaded.get(cid)["auth"] == "oauth2"]


class Watch:
    """What a read-only route must leave alone: KMS, Google, the store's writes and the event sink."""

    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.before = self.snapshot()
        self.reads: list[tuple[str, str]] = []
        inner = rig.env.store.get

        def get(user_id: str, connector: str) -> Any:
            self.reads.append((user_id, connector))
            return inner(user_id, connector)

        rig.env.store.get = get  # type: ignore[method-assign]

    def snapshot(self) -> tuple[Any, ...]:
        env = self.rig.env
        return (env.kms.decrypt_calls, len(env.kms.encrypted), len(env.google.calls), len(env.store.history),
                len(env.emitted), len(self.rig.cal.requests))  # fmt: skip

    def assert_untouched(self) -> None:
        assert self.snapshot() == self.before


def connect_person(rig: Rig, user: str = OWNER) -> None:
    for connector, scopes in (("gmail", [GMAIL_READ, GMAIL_SEND, CAL_READ, ALIEN]), ("google_drive", [DRIVE_FILE])):
        rig.env.connect(user, connector, scopes)


# ---- HB-01 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", [AUDIENCE_VAR, CALLER_VAR])
def test_ADR32A_T4B_FR_MTG_09_unset_audience_or_caller_is_503_not_configured(missing: str) -> None:
    rig = Rig(settings={k: v for k, v in {AUDIENCE_VAR: AUD, CALLER_VAR: CALLER}.items() if k != missing})
    response = views_call(rig)
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert rig.verifier.calls == []


def test_ADR32A_T4B_FR_MTG_09_no_valid_token_is_401_and_the_caller_is_checked_before_the_body() -> None:
    rig = Rig()
    watch = Watch(rig)
    for token in (None, "unknown-" + secrets.token_hex(4)):
        response = views_call(rig, token=token)
        assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
    for header in ("Basic " + rig.good, "Bearer", "Bearer a b", rig.good):
        r = rig.client.post(PATH, content=b"{}", headers={"authorization": header})
        assert r.status_code == 401
    assert views_call(rig, raw=b"x" * (MAX_BODY_BYTES + 1), token=None).status_code == 401
    assert watch.reads == []
    watch.assert_untouched()


def test_ADR32A_T4B_FR_MTG_09_other_accounts_are_403_and_wrong_claims_are_401() -> None:
    rig = Rig()
    other = rig.verifier.add(email="other-" + secrets.token_hex(3) + "@demo-tilo.example.test")
    response = views_call(rig, token=other)
    assert (response.status_code, response.json()) == (403, {"error": "forbidden"})
    for over in (
        {"aud": "https://elsewhere.example.test"},
        {"iss": "https://evil.example.test"},
        {"email_verified": False},
    ):
        response = views_call(rig, token=rig.verifier.add(**over))
        assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
    assert views_call(rig).status_code == 200


def test_ADR32A_T4B_FR_MTG_09_a_certificate_outage_is_502_not_a_401() -> None:
    rig = Rig()
    rig.verifier.verify = lambda t, a: (_ for _ in ()).throw(CertsUnavailable("x"))  # type: ignore[method-assign,assignment]
    response = views_call(rig)
    assert (response.status_code, response.json()) == (502, {"error": "not_configured"})


def test_ADR32A_T4B_FR_MTG_09_an_unconfigured_broker_is_503_and_nothing_is_read() -> None:
    rig = Rig()
    rig.runtime._broker._opener = lambda *a, **k: (_ for _ in ()).throw(BrokerNotConfigured("set TILO_KMS_KEY"))
    watch = Watch(rig)
    response = views_call(rig)
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert watch.reads == []


# ---- request shape ----------------------------------------------------------------------------


def test_ADR32A_T4B_FR_MTG_09_a_bad_request_is_422_with_a_fixed_body() -> None:
    rig = Rig()
    watch = Watch(rig)
    bad = [b"not json", b"[]", b"null", b"{}", json.dumps({**user_body(), "extra": 1}).encode()]
    bad += [json.dumps({"user_id": "../" + OWNER}).encode(), b"x" * (MAX_BODY_BYTES + 1), b"[" * 100_000]
    for raw in bad:
        response = views_call(rig, raw=raw)
        assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert watch.reads == []
    watch.assert_untouched()


def test_ADR32A_T4B_FR_MTG_09_a_query_or_path_cannot_name_another_user() -> None:
    rig = Rig()
    connect_person(rig, "u_other")
    headers = {"authorization": f"Bearer {rig.good}"}
    response = rig.client.post(PATH + "?user_id=u_other", content=json.dumps(user_body()).encode(), headers=headers)
    assert [v["connector"] for v in response.json()["views"]] == ["meeting_host"]
    assert rig.client.post(PATH + "/", content=b"{}", headers=headers).status_code == 404  # redirect_slashes is off
    assert rig.client.post(PATH + "/u_other", content=b"{}", headers=headers).status_code == 404


# ---- the views --------------------------------------------------------------------------------


def test_ADR32A_T4B_FR_MTG_09_views_are_in_registry_order_from_an_allowlist_and_validate() -> None:
    rig = Rig()
    connect_person(rig)
    watch = Watch(rig)
    response = views_call(rig)
    assert response.status_code == 200
    answer = response.json()
    assert host_rpc_validator("views_answer").is_valid(answer)
    assert set(answer) == {"views"} and "parts" not in answer
    assert [v["connector"] for v in answer["views"]] == [c for c in oauth_order() if c in
        ("gmail", "google_drive", "meeting_host")]  # fmt: skip
    by_id = {v["connector"]: v for v in answer["views"]}
    assert all(set(v) == {"connector", "state", "scopes", "connected_at"} for v in answer["views"])
    assert by_id["gmail"]["scopes"] == sorted([GMAIL_READ, GMAIL_SEND])  # only the registry's scopes for gmail
    assert by_id["gmail"]["state"] == "connected" and by_id["gmail"]["connected_at"] == NOW
    assert by_id["google_drive"]["scopes"] == [DRIVE_FILE]
    assert by_id["meeting_host"] == {
        "connector": "meeting_host", "state": "connected", "scopes": [CALENDAR_EVENTS_OWNED], "connected_at": BEFORE,
    }  # fmt: skip
    watch.assert_untouched()
    assert watch.reads and {u for u, _ in watch.reads} == {OWNER}


def test_ADR32A_T4B_FR_MTG_09_no_secret_expiry_or_address_is_ever_in_the_answer() -> None:
    rig = Rig()
    connect_person(rig)
    stored = rig.env.store.live_text()
    text = views_call(rig).text
    lowered = text.lower()
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in lowered
    assert "@" not in text and "expires" not in lowered
    record = rig.env.store.get(OWNER, "gmail") or {}
    for field in ("ct", "ciphertext", "wrapped_key", "nonce", "sealed", "payload"):
        value = record.get(field)
        assert not isinstance(value, str) or value not in text
    assert rig.env.settings.client_secret not in text and rig.env.settings.client_id not in text
    assert stored and stored not in text


def test_ADR32A_T4B_FR_MTG_09_another_users_records_are_never_read_or_shown() -> None:
    rig = Rig()
    connect_person(rig, "u_other")
    rig.env.connect("u_other", "meeting_host", [CALENDAR_EVENTS_OWNED])
    watch = Watch(rig)
    answer = views_call(rig, user_body("u_nobody")).json()
    assert answer == {"views": []}
    answer = views_call(rig).json()  # OWNER holds only the bot grant
    assert [v["connector"] for v in answer["views"]] == ["meeting_host"]
    assert {u for u, _ in watch.reads} <= {"u_nobody", OWNER}


def test_ADR32A_T4B_FR_MTG_09_the_bot_grant_is_listed_to_the_person_who_connected_it_only() -> None:
    rig = Rig()  # OWNER connected meeting_host
    mine = views_call(rig, user_body(OWNER)).json()["views"]
    theirs = views_call(rig, user_body("u_colleague")).json()["views"]
    assert [v["connector"] for v in mine] == ["meeting_host"] and mine[0]["state"] == "connected"
    assert theirs == []
    assert "@" not in json.dumps(mine)


def test_ADR32A_T4B_FR_MTG_09_a_connector_the_registry_does_not_declare_or_not_oauth_is_skipped() -> None:
    rig = Rig()
    connect_person(rig)
    rig.env.store.put(OWNER, "lovable", {"v": 1, "state": "connected", "scopes": [], "connected_at": BEFORE})
    rig.env.store.put(OWNER, "zz_unknown", {"v": 1, "state": "connected", "scopes": [], "connected_at": BEFORE})
    ids = [v["connector"] for v in views_call(rig).json()["views"]]
    assert "lovable" not in ids and "zz_unknown" not in ids
    assert len(ids) == len(set(ids))


def test_ADR32A_T4B_FR_MTG_09_an_expired_grant_has_no_scopes_and_no_connected_at() -> None:
    rig = Rig()
    connect_person(rig)
    rig.env.clock.advance(7200)
    rig.env.google.refresh_mode = "invalid_grant"
    rig.send()  # Google refuses the bot grant at refresh: the broker writes expired
    by_id = {v["connector"]: v for v in views_call(rig).json()["views"]}
    assert by_id["meeting_host"] == {
        "connector": "meeting_host",
        "state": "expired",
        "scopes": [],
        "connected_at": None,
    }
    assert by_id["gmail"]["state"] == "connected"


@pytest.mark.parametrize(
    "record",
    [
        {"v": 1, "state": "revoked", "scopes": [GMAIL_READ], "connected_at": BEFORE},
        {"v": 1, "state": "expiring", "scopes": [GMAIL_READ], "connected_at": BEFORE},
        {"v": 1, "state": ["connected"], "scopes": [GMAIL_READ], "connected_at": BEFORE},
        {"v": 1, "state": "connected", "scopes": "not a list", "connected_at": BEFORE},
        {"v": 1, "state": "connected", "scopes": {"a": 1}, "connected_at": BEFORE},
        {"v": 1, "state": "connected", "scopes": [1, None, ["x"]], "connected_at": BEFORE},
        {"v": 1, "state": "expired", "scopes": [], "expires_at": None},
        {},
        {"state": None},
    ],
)
def test_ADR32A_T4B_FR_MTG_09_a_malformed_or_foreign_record_is_an_expired_view(record: dict[str, Any]) -> None:
    rig = Rig(connect_at=None)
    rig.env.store.put(OWNER, "gmail", record)
    answer = views_call(rig).json()
    assert host_rpc_validator("views_answer").is_valid(answer)
    got = [v for v in answer["views"] if v["connector"] == "gmail"]
    assert got in ([{"connector": "gmail", "state": "expired", "scopes": [], "connected_at": None}],
        [{"connector": "gmail", "state": "connected", "scopes": [], "connected_at": BEFORE}])  # fmt: skip
    if record.get("scopes") in (None, "not a list", {"a": 1}) or record.get("state") != "connected":
        assert got[0]["state"] == "expired"


def test_ADR32A_T4B_FR_MTG_09_a_bad_connected_at_is_null_and_scopes_are_filtered_sorted_unique() -> None:
    rig = Rig(connect_at=None)
    rig.env.store.put(
        OWNER,
        "gmail",
        {
            "v": 1,
            "state": "connected",
            "scopes": [GMAIL_SEND, GMAIL_READ, GMAIL_READ, ALIEN, "x" * 400],
            "connected_at": "yesterday",
        },
    )
    view = views_call(rig).json()["views"][0]
    assert view == {
        "connector": "gmail",
        "state": "connected",
        "scopes": sorted([GMAIL_READ, GMAIL_SEND]),
        "connected_at": None,
    }


def test_ADR32A_T4B_FR_MTG_09_the_route_reads_without_kms_google_or_any_write() -> None:
    rig = Rig()
    connect_person(rig)
    rig.env.clock.advance(7200)  # the access tokens are stale: a token use would refresh, a read does not
    watch = Watch(rig)
    for _ in range(3):
        assert views_call(rig).status_code == 200
    watch.assert_untouched()
    assert rig.env.google.refresh_calls() == [] and rig.env.google.revoke_calls() == []


# ---- failures ---------------------------------------------------------------------------------


def test_ADR32A_T4B_FR_MTG_09_a_failing_store_is_a_fixed_503_that_names_only_a_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    leak = "sk-" + secrets.token_hex(6)

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError(leak)

    rig.env.store.connectors_of = boom  # type: ignore[method-assign]
    rig.env.store.get = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG):
        response = views_call(rig)
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert leak not in response.text + caplog.text and "RuntimeError" in caplog.text


def test_ADR32A_T4B_FR_MTG_09_an_answer_that_breaks_its_contract_is_503() -> None:
    rig = Rig()
    rig.runtime.connection_views = lambda user_id: {"views": [{"connector": "gmail"}]}  # type: ignore[method-assign]
    response = views_call(rig)
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})


def test_ADR32A_T4B_FR_MTG_09_the_route_is_in_the_signed_surface_and_the_other_routes_still_answer() -> None:
    from test_SEC_08_forged_or_replayed_oauth_callback_rejected import SIGNED_ROUTES

    assert ("POST", PATH) in SIGNED_ROUTES
    rig = Rig()
    assert rig.call("status", user_body()).status_code == 200
