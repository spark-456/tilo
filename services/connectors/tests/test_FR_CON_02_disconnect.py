"""FR-CON-02 (PRD 12.1 "disconnecting revokes the token at the provider and deletes it", 16.5
"account deletion removes data from every store", 9.5 connection.revoked). Acceptance: disconnect
revokes at the provider and leaves no token in any store.

Fail toward deletion: if the provider cannot be reached or refuses, the local copy is still deleted
and the failure is recorded. PRD silent on user deletion and revoking; chosen: deleting a user
disconnects each of their connections the same way (revoke, then delete), so a live grant is never
left at Google after the account is gone.
"""

from __future__ import annotations

import logging

import pytest
from _oauth_lib import (
    DRIVE_FILE,
    EXPIRES_IN,
    GMAIL_READONLY,
    OTHER,
    OWNER,
    REVOKE_URL,
    graph_contains,
    leaks,
    make_env,
    types_of,
    validate_part,
)
from tilo_connectors.tokens import ConnectionExpired, DisconnectResult, NotConnected


def plaintexts(*responses):
    return [t for r in responses for t in (r["access_token"], r.get("refresh_token")) if t]


def broker_is_clean(env, secrets_):
    skip = (env.store, env.kms, env.google, env.emitted, env.clock, env.settings)
    return not graph_contains(env.broker, secrets_, skip=skip)


# ---- Acceptance: revoke at the provider, leave no token anywhere -------------------------------


def test_FR_CON_02_disconnect_revokes_at_the_provider_and_leaves_no_token_in_any_store():
    env = make_env()
    response = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.clock.advance(EXPIRES_IN + 1)  # also holds a refreshed token, the more tokens the better
    refreshed = env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])
    everything = plaintexts(response) + [refreshed]

    result = env.broker.disconnect(OWNER, "gmail")

    assert isinstance(result, DisconnectResult)
    assert result.revoked_at_provider is True
    assert result.provider_error is None
    assert env.google.calls_to(REVOKE_URL) and env.google.revoke_calls()[0]["token"] == response["refresh_token"]
    assert response["refresh_token"] not in env.google.live_refresh, "the provider no longer honours it"
    assert env.store.live_keys() == [], "the record is gone"
    assert env.store.live_text() == ""
    assert leaks(env.store.ever_text(), everything) == [], "and no token was ever written in the clear"
    assert broker_is_clean(env, everything), "and the broker holds no decrypted copy in memory"
    assert env.broker.connection_state(OWNER, "gmail") is None
    assert env.broker.granted_scopes(OWNER, "gmail") == frozenset()
    with pytest.raises(NotConnected):
        env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])


def test_FR_CON_02_disconnect_emits_connection_revoked():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.emitted.clear()

    env.broker.disconnect(OWNER, "gmail")

    assert types_of(env.emitted) == ["connection.revoked"]
    validate_part(env.emitted[0])
    assert env.emitted[0]["data"] == {"connector": "gmail"}
    assert env.emitted[0]["user_id"] == OWNER


def test_FR_CON_02_disconnect_touches_only_that_connection():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    drive = env.connect(OWNER, "google_drive", [DRIVE_FILE])
    other = env.connect(OTHER, "gmail", [GMAIL_READONLY])

    env.broker.disconnect(OWNER, "gmail")

    assert env.store.live_keys() == [(OTHER, "gmail"), (OWNER, "google_drive")]
    assert (
        env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
        == (drive["access_token"])
    )
    assert (
        env.broker.access_token_for_adapter(OTHER, "gmail", required_scopes=[GMAIL_READONLY]) == (other["access_token"])
    )
    assert drive["refresh_token"] in env.google.live_refresh and other["refresh_token"] in env.google.live_refresh


def test_FR_CON_02_disconnecting_twice_is_harmless():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.broker.disconnect(OWNER, "gmail")
    calls, events = len(env.google.calls), len(env.emitted)

    env.broker.disconnect(OWNER, "gmail")

    assert len(env.google.calls) == calls
    assert len(env.emitted) == events


def test_FR_CON_02_a_connection_that_expired_can_still_be_disconnected_and_leaves_nothing():
    env = make_env()
    response = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.google.refresh_mode = "invalid_grant"
    env.clock.advance(EXPIRES_IN + 1)
    with pytest.raises(ConnectionExpired):
        env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])

    env.broker.disconnect(OWNER, "gmail")

    assert env.store.live_keys() == []
    assert leaks(env.store.live_text(), plaintexts(response)) == []
    assert env.broker.connection_state(OWNER, "gmail") is None


# ---- Fail toward deletion ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["unavailable", "network", "rejected"])
def test_FR_CON_02_a_failed_revoke_still_deletes_locally_and_records_the_failure(mode, caplog):
    env = make_env()
    response = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.emitted.clear()
    env.google.revoke_mode = mode
    caplog.set_level(logging.DEBUG)

    result = env.broker.disconnect(OWNER, "gmail")

    assert result.revoked_at_provider is False
    assert isinstance(result.provider_error, str) and result.provider_error
    assert env.store.live_keys() == [], "fail toward deletion"
    assert env.broker.connection_state(OWNER, "gmail") is None
    assert types_of(env.emitted) == ["connection.revoked"], "access is removed on our side either way"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("gmail" in r.getMessage() for r in warnings), "the failure is recorded in a warning naming the connector"
    secrets_ = plaintexts(response)
    assert leaks(result.provider_error, secrets_) == []
    assert leaks("\n".join(r.getMessage() for r in caplog.records), secrets_) == []
    assert leaks(repr(env.emitted), secrets_) == []
    assert broker_is_clean(env, secrets_)


# ---- Deleting a user ---------------------------------------------------------------------------


def test_FR_CON_02_deleting_a_user_deletes_all_their_tokens_and_no_one_elses():
    env = make_env()
    a1 = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    a2 = env.connect(OWNER, "google_drive", [DRIVE_FILE])
    b1 = env.connect(OTHER, "gmail", [GMAIL_READONLY])

    env.broker.delete_user(OWNER)

    assert env.store.live_keys() == [(OTHER, "gmail")]
    assert leaks(env.store.live_text(), plaintexts(a1, a2)) == []
    assert broker_is_clean(env, plaintexts(a1, a2))
    assert env.broker.connection_state(OWNER, "gmail") is None
    assert env.broker.connection_state(OWNER, "google_drive") is None
    revoked = {c["token"] for c in env.google.revoke_calls()}
    assert revoked == {a1["refresh_token"], a2["refresh_token"]}, "revoked at the provider, theirs only"
    assert env.broker.access_token_for_adapter(OTHER, "gmail", required_scopes=[GMAIL_READONLY]) == b1["access_token"]


def test_FR_CON_02_deleting_a_user_deletes_everything_even_when_the_provider_is_down():
    env = make_env()
    a1 = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    a2 = env.connect(OWNER, "google_drive", [DRIVE_FILE])
    env.google.revoke_mode = "network"

    env.broker.delete_user(OWNER)

    assert env.store.live_keys() == []
    assert leaks(env.store.live_text(), plaintexts(a1, a2)) == []


def test_FR_CON_02_deleting_a_user_with_no_connections_is_harmless():
    env = make_env()
    env.connect(OTHER, "gmail", [GMAIL_READONLY])

    env.broker.delete_user(OWNER)

    assert env.store.live_keys() == [(OTHER, "gmail")]
    assert env.google.calls == []
