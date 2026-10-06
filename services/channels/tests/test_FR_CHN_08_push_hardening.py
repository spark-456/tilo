"""FR-CHN-08 security review r1 of #208: the push endpoint never lets an exception or an address escape.

A failing account lookup answers 500 (Pub/Sub redelivers) and logs only the exception type (BQ-129).
A verifier answer that is not a mapping, or an `iss` that is not a string, is refused 403, not a crash.
"""

from __future__ import annotations

import logging

import pytest
from _channels_lib import FakeClock
from _chn08_lib import (
    ADDRESS,
    AUDIENCE,
    PUSH_SA,
    RIYA,
    USER_FOR_ADDRESS,
    FakeOidcVerifier,
    NotificationRecorder,
    bearer,
    push_body,
)


def _endpoint(accounts, verifier=None):
    from tilo_channels.gmail_watch import GmailPushEndpoint

    notified = NotificationRecorder()
    endpoint = GmailPushEndpoint(
        verifier=verifier or FakeOidcVerifier(FakeClock()),
        audience=AUDIENCE,
        service_account=PUSH_SA,
        accounts=accounts,
        on_notification=notified,
    )
    return endpoint, notified


def test_FR_CHN_08_a_failing_account_lookup_answers_500_without_the_address(caplog):
    def accounts(address: str) -> str | None:
        raise LookupError(f"no row for {address}")

    verifier = FakeOidcVerifier(FakeClock())
    endpoint, notified = _endpoint(accounts, verifier)
    token = verifier.issue()
    with caplog.at_level(logging.DEBUG):
        response = endpoint.receive(bearer(token), push_body(ADDRESS[RIYA], 4242))
    assert response.status == 500
    assert notified.calls == []
    assert ADDRESS[RIYA] not in response.body
    assert ADDRESS[RIYA] not in caplog.text
    assert "LookupError" in caplog.text


class _OddVerifier:
    def __init__(self, claims) -> None:
        self._claims = claims

    def verify(self, token: str, audience: str):
        return self._claims


@pytest.mark.parametrize(
    "claims",
    [
        None,
        ["aud", AUDIENCE],
        {"aud": AUDIENCE, "iss": ["accounts.google.com"], "email": PUSH_SA, "email_verified": True},
        {"aud": AUDIENCE, "iss": {"accounts.google.com": 1}, "email": PUSH_SA, "email_verified": True},
    ],
)
def test_FR_CHN_08_odd_verifier_claims_are_refused_403(claims):
    endpoint, notified = _endpoint(USER_FOR_ADDRESS.get, verifier=_OddVerifier(claims))
    response = endpoint.receive(bearer("fake-oidc-token"), push_body(ADDRESS[RIYA], 4242))
    assert response.status == 403
    assert notified.calls == []
