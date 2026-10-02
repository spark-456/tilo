"""FR-CON-04 builder tests: the broker's forced refresh, the adapters' 401 path (Google dropped a token
before its expiry). `access_token_for_adapter(..., force_refresh=True)` refreshes that same user and
connector only, after the same connected and scope checks, and never logs or emits a token.
"""

from __future__ import annotations

import json
import logging

import pytest
from _oauth_lib import DRIVE_FILE, GMAIL_READONLY, GMAIL_SEND, OTHER, OWNER, leaks, make_env


def _env():
    env = make_env()
    grant = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.connect(OWNER, "google_drive", [DRIVE_FILE])
    env.connect(OTHER, "gmail", [GMAIL_READONLY])
    return env, grant


def _token(env, user, connector, scope, **kw):
    return env.broker.access_token_for_adapter(user, connector, required_scopes=[scope], **kw)


def test_FR_CON_04_force_refresh_renews_only_that_users_connection_before_expiry():
    env, grant = _env()
    stale = _token(env, OWNER, "gmail", GMAIL_READONLY)
    drive = _token(env, OWNER, "google_drive", DRIVE_FILE)
    other = _token(env, OTHER, "gmail", GMAIL_READONLY)

    fresh = _token(env, OWNER, "gmail", GMAIL_READONLY, force_refresh=True)

    assert fresh != stale and fresh == env.google.issued_access[-1]
    (call,) = env.google.refresh_calls()
    assert call["refresh_token"] == grant["refresh_token"], "it refreshed this user's gmail grant"
    assert _token(env, OWNER, "gmail", GMAIL_READONLY) == fresh, "the new token is stored"
    assert _token(env, OWNER, "google_drive", DRIVE_FILE) == drive
    assert _token(env, OTHER, "gmail", GMAIL_READONLY) == other
    assert len(env.google.refresh_calls()) == 1


def test_FR_CON_04_force_refresh_keeps_the_connection_and_scope_checks():
    from tilo_connectors.tokens import InsufficientScope, NotConnected

    env, _ = _env()
    with pytest.raises(InsufficientScope):
        _token(env, OWNER, "gmail", GMAIL_SEND, force_refresh=True)
    with pytest.raises(NotConnected):
        _token(env, "u_nobody", "gmail", GMAIL_READONLY, force_refresh=True)
    assert env.google.refresh_calls() == []


def test_FR_CON_04_force_refresh_refused_expires_the_connection_once():
    from tilo_connectors.tokens import ConnectionExpired

    env, _ = _env()
    env.google.refresh_mode = "invalid_grant"

    with pytest.raises(ConnectionExpired):
        _token(env, OWNER, "gmail", GMAIL_READONLY, force_refresh=True)
    with pytest.raises(ConnectionExpired):
        _token(env, OWNER, "gmail", GMAIL_READONLY, force_refresh=True)

    assert len(env.google.refresh_calls()) == 1, "an expired connection is not refreshed again"
    assert [p["data"] for p in env.parts_of("connection.expired")] == [{"connector": "gmail"}]
    assert env.broker.connection_state(OWNER, "gmail") == "expired"
    assert env.broker.connection_state(OWNER, "google_drive") == "connected"


def test_FR_CON_04_force_refresh_never_logs_emits_or_raises_a_token(caplog):
    from tilo_connectors.tokens import TokenRefreshFailed

    caplog.set_level(logging.DEBUG)
    env, _ = _env()
    _token(env, OWNER, "gmail", GMAIL_READONLY, force_refresh=True)
    env.google.refresh_mode = "unavailable"

    with pytest.raises(TokenRefreshFailed) as raised:
        _token(env, OWNER, "gmail", GMAIL_READONLY, force_refresh=True)

    tokens = list(env.google.issued_access) + list(env.google.live_refresh)
    assert leaks(caplog.text + json.dumps(env.emitted, default=str), tokens) == []
    assert leaks(repr(raised.value) + str(raised.value), tokens) == []
