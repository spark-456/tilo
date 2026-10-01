"""FR-CON-03 (PRD 12.1 "oauth2 (user sign-in, PKCE)", 16.1 rule 2 "incremental scopes"): the URL that
the consent card's Connect opens asks Google for exactly the scopes still needed, with PKCE (S256), an
unguessable single-use state, `include_granted_scopes=true` (so earlier grants carry over) and
`access_type=offline` (so there is a refresh token).

ConsentService.authorization_url(user_id=, connector=, capabilities=, card_id=) -> str | None
(None when nothing is needed). Google's endpoints are fixed: AUTH_URL here, TOKEN_URL for the code
exchange. All tokens, ids and secrets are fakes assembled at runtime.
"""

from __future__ import annotations

import re

import pytest
from _oauth_lib import (
    AUTH_URL,
    CARD_ID,
    DEV_REDIRECT_URI,
    DRIVE_FILE,
    DRIVE_READONLY,
    GMAIL_READONLY,
    GMAIL_SEND,
    OTHER,
    OWNER,
    TOKEN_URL,
    finish_flow,
    make_env,
    s256,
    start_flow,
)


def test_FR_CON_03_the_url_asks_google_for_only_the_scope_a_drive_write_needs():
    env = make_env()

    flow = start_flow(env, OWNER, "google_drive", ["write"])

    assert flow.base == AUTH_URL
    assert flow.scopes == [DRIVE_FILE]


def test_FR_CON_03_the_url_leaves_out_what_is_already_granted():
    env = make_env()
    env.connect(OWNER, "google_drive", [DRIVE_READONLY])

    flow = start_flow(env, OWNER, "google_drive", ["read", "write"])

    assert flow.scopes == [DRIVE_FILE], "Google adds the earlier grant through include_granted_scopes"


def test_FR_CON_03_no_url_when_nothing_is_needed():
    env = make_env()
    env.connect(OWNER, "google_drive", [DRIVE_FILE])

    url = env.service.authorization_url(
        user_id=OWNER, connector="google_drive", capabilities=["write"], card_id=CARD_ID
    )

    assert url is None


def test_FR_CON_03_the_url_carries_the_oauth_parameters_incremental_consent_needs():
    env = make_env()

    q = start_flow(env, OWNER, "gmail", ["send"]).query

    assert q["client_id"] == env.settings.client_id
    assert q["redirect_uri"] == DEV_REDIRECT_URI
    assert q["response_type"] == "code"
    assert q["scope"] == GMAIL_SEND
    assert q["include_granted_scopes"] == "true"
    assert q["access_type"] == "offline"


def test_FR_CON_03_the_redirect_uri_follows_the_configured_base_url():
    env = make_env(base_url="https://api.tilo.example")

    q = start_flow(env, OWNER, "gmail", ["send"]).query

    assert q["redirect_uri"] == "https://api.tilo.example/oauth/google/callback"


def test_FR_CON_03_the_url_uses_pkce_s256():
    env = make_env()

    q = start_flow(env, OWNER, "gmail", ["send"]).query

    assert q["code_challenge_method"] == "S256"
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", q["code_challenge"]), "a base64url SHA-256, unpadded"


def test_FR_CON_03_the_code_exchange_proves_the_pkce_verifier_and_uses_the_flows_own_redirect():
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["send"])

    finish_flow(env, flow, OWNER)

    assert env.google.calls[0].url == TOKEN_URL
    sent = env.google.exchange_calls()[0]
    assert sent["grant_type"] == "authorization_code"
    assert 43 <= len(sent["code_verifier"]) <= 128
    assert re.fullmatch(r"[A-Za-z0-9._~-]+", sent["code_verifier"]), "RFC 7636 unreserved characters"
    assert s256(sent["code_verifier"]) == flow.query["code_challenge"]
    assert sent["redirect_uri"] == flow.query["redirect_uri"]
    assert sent["client_id"] == env.settings.client_id
    assert sent["client_secret"] == env.settings.client_secret


def test_FR_CON_03_every_flow_has_its_own_verifier():
    env = make_env()
    first = start_flow(env, OWNER, "gmail", ["send"])
    second = start_flow(env, OWNER, "gmail", ["send"])
    finish_flow(env, first, OWNER)
    finish_flow(env, second, OWNER)

    verifiers = [c["code_verifier"] for c in env.google.exchange_calls()]

    assert len(set(verifiers)) == 2
    assert first.query["code_challenge"] != second.query["code_challenge"]


def test_FR_CON_03_state_values_are_unpredictable_and_never_repeat():
    env = make_env()

    states = [start_flow(env, OWNER, "gmail", ["send"]).state for _ in range(50)]
    states += [start_flow(env, OTHER, "google_drive", ["write"]).state for _ in range(50)]

    assert len(set(states)) == 100, "a fresh nonce every time"
    assert all(len(s) >= 22 for s in states), "at least 128 bits of base64url"
    assert all(re.fullmatch(r"[A-Za-z0-9._~-]+", s) for s in states), "safe in a query string"


def test_FR_CON_03_the_url_holds_no_secret_and_no_user_identifier():
    env = make_env()

    flow = start_flow(env, OWNER, "gmail", ["send"])

    assert env.secrets["client_secret"] not in flow.url
    assert "client_secret" not in flow.query
    assert OWNER not in flow.url, "no personal data in a URL (PRD 16.5)"


def test_FR_CON_03_asking_for_the_url_grants_nothing():
    env = make_env()

    start_flow(env, OWNER, "google_drive", ["write"])

    assert env.google.calls == []
    assert env.store.live_keys() == []
    assert [p["type"] for p in env.emitted if p["type"] in ("connection.consented", "connection.established")] == []


@pytest.mark.parametrize("connector", ["gmail", "google_drive"])
def test_FR_CON_03_the_url_never_asks_for_an_undeclared_capability(connector):
    from tilo_connectors.consent import ConsentRefused

    env = make_env()

    with pytest.raises(ConsentRefused):
        env.service.authorization_url(user_id=OWNER, connector=connector, capabilities=["delete"], card_id=CARD_ID)


def test_FR_CON_03_gmail_read_still_asks_for_read_alone_after_a_send_grant():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_SEND])

    assert start_flow(env, OWNER, "gmail", ["read"]).scopes == [GMAIL_READONLY]
