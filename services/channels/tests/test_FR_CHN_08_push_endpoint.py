"""FR-CHN-08: the Gmail push endpoint authenticates Pub/Sub's OIDC token before anything else.

PRD 6.3 (Pub/Sub carries Gmail push notifications), 16.2 and SEC-08 (signed webhooks: forged or replayed
requests rejected), services/channels/CLAUDE.md (public ingress for verified webhooks only; never log
bodies, secrets or tokens; log exception types, not messages). The OIDC signature and expiry are checked
by the injected verifier; the endpoint itself checks audience, issuer, service account and
email_verified, then parses. A refused push reaches no model and no side effect: `on_notification` is
never called and nothing is emitted. API_FR_CHN_08.md "GmailPushEndpoint".
"""

from __future__ import annotations

import base64
import json
import logging

import pytest
from _channels_lib import FakeClock
from _chn08_lib import (
    ADDRESS,
    AUDIENCE,
    PUSH_SA,
    RIYA,
    USER_FOR_ADDRESS,
    EventLog,
    FakeOidcVerifier,
    NotificationRecorder,
    bearer,
    drop,
    push_body,
)


def _endpoint(clock: FakeClock | None = None):
    from tilo_channels.gmail_watch import GmailPushEndpoint

    clock = clock or FakeClock()
    verifier = FakeOidcVerifier(clock)
    notified = NotificationRecorder()
    events = EventLog()
    endpoint = GmailPushEndpoint(
        verifier=verifier,
        audience=AUDIENCE,
        service_account=PUSH_SA,
        accounts=USER_FOR_ADDRESS.get,
        on_notification=notified,
        emit=events,
    )
    return endpoint, verifier, notified, events, clock


def _assert_refused_quietly(response, notified, events, *secrets_seen: str) -> None:
    assert not 200 <= response.status < 300
    assert notified.calls == [], "a refused push never reaches the watcher (no model, no side effect)"
    assert events.parts == []
    body = str(getattr(response, "body", ""))
    assert len(body) <= 64, "a short generic reason only"
    for secret in secrets_seen:
        assert secret not in body


def test_FR_CHN_08_authenticated_push_notifies_the_watcher_with_user_and_history_id():
    endpoint, verifier, notified, _, _ = _endpoint()

    response = endpoint.receive(bearer(verifier.issue()), push_body(ADDRESS[RIYA], 1234567))

    assert 200 <= response.status < 300
    assert notified.calls == [(RIYA, "1234567")], "history id handed on as a decimal string"


def test_FR_CHN_08_history_id_may_arrive_as_a_decimal_string():
    endpoint, verifier, notified, _, _ = _endpoint()

    response = endpoint.receive(bearer(verifier.issue()), push_body(ADDRESS[RIYA], "98765"))

    assert 200 <= response.status < 300
    assert notified.calls == [(RIYA, "98765")]


def test_FR_CHN_08_authorization_header_name_is_case_insensitive():
    endpoint, verifier, notified, _, _ = _endpoint()
    token = verifier.issue()

    response = endpoint.receive({"authorization": f"Bearer {token}"}, push_body(ADDRESS[RIYA], 42))

    assert 200 <= response.status < 300
    assert notified.calls == [(RIYA, "42")]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "bearer-without-space"},
    ],
    ids=["missing", "empty", "no-token", "blank-token", "basic", "garbled"],
)
def test_FR_CHN_08_push_without_a_bearer_token_is_refused_401(headers):
    endpoint, _, notified, events, _ = _endpoint()

    response = endpoint.receive(headers, push_body(ADDRESS[RIYA], 42))

    assert response.status == 401
    _assert_refused_quietly(response, notified, events)


def test_FR_CHN_08_forged_token_is_refused_without_leaking_the_verifier_error():
    endpoint, verifier, notified, events, _ = _endpoint()
    forged = "fake-oidc-forged-" + "x" * 20

    response = endpoint.receive(bearer(forged), push_body(ADDRESS[RIYA], 42))

    assert response.status in (401, 403)
    _assert_refused_quietly(response, notified, events, forged, verifier.detail_marker)


def test_FR_CHN_08_expired_token_is_refused():
    clock = FakeClock()
    endpoint, verifier, notified, events, _ = _endpoint(clock)
    token = verifier.issue()
    clock.advance(3601)

    response = endpoint.receive(bearer(token), push_body(ADDRESS[RIYA], 42))

    assert response.status in (401, 403)
    _assert_refused_quietly(response, notified, events, token, verifier.detail_marker)


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "https://evil.example.net/gmail/push"},
        {"aud": AUDIENCE + "/extra"},
        {"aud": drop()},
        {"iss": "https://evil.example.net"},
        {"iss": drop()},
        {"email": "someone-else@demo-tilo.iam.gserviceaccount.com"},
        {"email": PUSH_SA.upper() + ".evil.example.net"},
        {"email": drop()},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email_verified": drop()},
    ],
    ids=[
        "wrong-aud",
        "aud-suffix",
        "no-aud",
        "wrong-iss",
        "no-iss",
        "wrong-sa",
        "sa-lookalike",
        "no-email",
        "email-unverified",
        "email-verified-string",
        "no-email-verified",
    ],
)
def test_FR_CHN_08_validly_signed_token_with_wrong_claims_is_refused(claims):
    """The verifier checked the signature only; audience, issuer and service account are the endpoint's job."""
    endpoint, verifier, notified, events, _ = _endpoint()
    token = verifier.issue(**claims)

    response = endpoint.receive(bearer(token), push_body(ADDRESS[RIYA], 42))

    assert response.status in (401, 403)
    _assert_refused_quietly(response, notified, events, token, PUSH_SA, AUDIENCE)


def test_FR_CHN_08_accounts_google_issuer_without_scheme_is_accepted():
    """Google signs ID tokens with iss "https://accounts.google.com" or "accounts.google.com"."""
    endpoint, verifier, notified, _, _ = _endpoint()

    response = endpoint.receive(bearer(verifier.issue(iss="accounts.google.com")), push_body(ADDRESS[RIYA], 7))

    assert 200 <= response.status < 300
    assert notified.calls == [(RIYA, "7")]


def test_FR_CHN_08_unauthenticated_malformed_body_is_refused_as_unauthenticated_not_parsed():
    endpoint, _, notified, events, _ = _endpoint()

    response = endpoint.receive({}, b"{not json")

    assert response.status == 401, "authentication runs before parsing"
    _assert_refused_quietly(response, notified, events)


def _b64(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{not json",
        b"[]",
        json.dumps({"subscription": "projects/demo-tilo/subscriptions/gmail-push"}).encode(),
        json.dumps({"message": "text"}).encode(),
        json.dumps({"message": {"messageId": "1"}}).encode(),
        push_body(ADDRESS[RIYA], 1, raw_data="%%%not-base64%%%"),
        push_body(ADDRESS[RIYA], 1, raw_data=base64.b64encode(b"not json").decode()),
        push_body(ADDRESS[RIYA], 1, raw_data=_b64(["list"])),
        push_body(ADDRESS[RIYA], 1, data={"historyId": 5}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA]}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": 7, "historyId": 5}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA], "historyId": -5}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA], "historyId": 1.5}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA], "historyId": True}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA], "historyId": "12a"}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA], "historyId": ""}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA], "historyId": "1" * 30}),
        push_body(ADDRESS[RIYA], 1, data={"emailAddress": ADDRESS[RIYA], "historyId": 2**64}),
    ],
    ids=[
        "empty",
        "not-json",
        "array",
        "no-message",
        "message-not-object",
        "no-data",
        "data-not-base64",
        "data-not-json",
        "data-not-object",
        "no-address",
        "no-history-id",
        "address-not-string",
        "history-negative",
        "history-float",
        "history-bool",
        "history-non-digit",
        "history-empty",
        "history-too-long",
        "history-over-uint64",
    ],
)
def test_FR_CHN_08_authenticated_but_malformed_push_is_refused_400(body):
    endpoint, verifier, notified, events, _ = _endpoint()
    token = verifier.issue()

    response = endpoint.receive(bearer(token), body)

    assert response.status == 400
    _assert_refused_quietly(response, notified, events, token, ADDRESS[RIYA])


def test_FR_CHN_08_push_for_an_address_tilo_does_not_watch_is_acknowledged_and_ignored():
    """Nothing a redelivery could fix, so it is acknowledged (2xx) and dropped."""
    endpoint, verifier, notified, events, _ = _endpoint()

    response = endpoint.receive(bearer(verifier.issue()), push_body("stranger@example.org", 42))

    assert 200 <= response.status < 300
    assert notified.calls == []
    assert events.parts == []
    assert "stranger@example.org" not in str(getattr(response, "body", ""))


def test_FR_CHN_08_downstream_failure_answers_5xx_so_pubsub_redelivers():
    endpoint, verifier, notified, _, _ = _endpoint()
    notified.raise_next = 1

    response = endpoint.receive(bearer(verifier.issue()), push_body(ADDRESS[RIYA], 42))

    assert response.status >= 500
    assert "downstream" not in str(getattr(response, "body", "")), "no exception text in the response"


def test_FR_CHN_08_endpoint_logs_no_token_address_payload_or_error_text(caplog):
    endpoint, verifier, notified, _, _ = _endpoint()
    caplog.set_level(logging.DEBUG)
    good = verifier.issue()
    wrong_aud = verifier.issue(aud="https://evil.example.net/x")
    forged = "fake-oidc-forged-" + "y" * 20
    body = push_body(ADDRESS[RIYA], 42)
    data_blob = json.loads(body)["message"]["data"]

    endpoint.receive(bearer(good), body)
    endpoint.receive(bearer(wrong_aud), body)
    endpoint.receive(bearer(forged), body)
    endpoint.receive(bearer(good), push_body(ADDRESS[RIYA], 1, raw_data="%%%"))
    notified.raise_next = 1
    endpoint.receive(bearer(good), body)

    text = "\n".join([r.getMessage() for r in caplog.records] + [repr(r.args) for r in caplog.records] + [caplog.text])
    for secret in (good, wrong_aud, forged, ADDRESS[RIYA], data_blob, verifier.detail_marker, "downstream unavailable"):
        assert secret not in text
