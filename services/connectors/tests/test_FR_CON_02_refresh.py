"""FR-CON-02 (PRD 12.1 "Refresh is automatic", 9.5 connection.expired, 10.2): the broker refreshes an
access token before it expires, from the refresh token, with exactly one provider call however many
callers ask at once; a refresh the provider rejects (invalid_grant) moves the connection to expired
and emits the registered event; a refresh that merely failed to get through does not.

PRD silent: how long before expiry to refresh. Default chosen: `refresh_skew_s = 60`, so a token with
a minute or less left is refreshed; a token with half its life left never is.
"""

from __future__ import annotations

import threading

import pytest
from _oauth_lib import (
    DRIVE_FILE,
    EXPIRES_IN,
    GMAIL_READONLY,
    OWNER,
    TOKEN_URL,
    leaks,
    make_env,
    types_of,
    validate_part,
)
from tilo_connectors.tokens import ConnectionExpired, InsufficientScope, NotConnected, TokenRefreshFailed

SCOPES = [GMAIL_READONLY]


def token(env, user=OWNER, connector="gmail", scopes=SCOPES):
    return env.broker.access_token_for_adapter(user, connector, required_scopes=scopes)


def test_FR_CON_02_a_fresh_token_is_served_without_a_provider_call():
    env = make_env()
    response = env.connect(OWNER, "gmail", SCOPES)

    assert token(env) == response["access_token"]
    assert env.google.calls == []


def test_FR_CON_02_a_token_with_half_its_life_left_is_not_refreshed():
    env = make_env()
    response = env.connect(OWNER, "gmail", SCOPES)
    env.clock.advance(EXPIRES_IN // 2)

    assert token(env) == response["access_token"]
    assert env.google.refresh_calls() == []


def test_FR_CON_02_a_token_about_to_expire_is_refreshed_before_it_does():
    env = make_env()
    response = env.connect(OWNER, "gmail", SCOPES)
    env.clock.advance(EXPIRES_IN - 1)  # one second of life left

    new = token(env)

    assert new != response["access_token"]
    assert new in env.google.issued_access
    assert len(env.google.refresh_calls()) == 1


def test_FR_CON_02_refresh_posts_the_refresh_token_and_the_client_credentials_to_the_token_endpoint():
    env = make_env()
    response = env.connect(OWNER, "gmail", SCOPES)
    env.clock.advance(EXPIRES_IN + 1)

    token(env)

    assert env.google.calls[0].url == TOKEN_URL
    sent = env.google.refresh_calls()[0]
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == response["refresh_token"]
    assert sent["client_id"] == env.settings.client_id
    assert sent["client_secret"] == env.settings.client_secret


def test_FR_CON_02_a_refreshed_token_is_stored_encrypted_and_served_until_it_nears_expiry():
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)
    env.clock.advance(EXPIRES_IN + 1)

    new = token(env)

    assert leaks(env.store.ever_text(), [new]) == []
    env.clock.advance(600)
    assert token(env) == new
    assert len(env.google.refresh_calls()) == 1, "a refreshed token is good for its own lifetime"


def test_FR_CON_02_the_refresh_token_survives_a_refresh_and_is_the_one_revoked_later():
    env = make_env()
    response = env.connect(OWNER, "gmail", SCOPES)
    env.clock.advance(EXPIRES_IN + 1)
    token(env)

    env.broker.disconnect(OWNER, "gmail")

    assert response["refresh_token"] in env.google.revoked


def test_FR_CON_02_a_rotated_refresh_token_replaces_the_old_one():
    env = make_env()
    old = env.connect(OWNER, "gmail", SCOPES)["refresh_token"]
    env.google.rotate_refresh_token = True
    env.clock.advance(EXPIRES_IN + 1)
    token(env)
    rotated = next(iter(env.google.live_refresh))
    assert rotated != old

    env.broker.disconnect(OWNER, "gmail")

    assert rotated in env.google.revoked


def test_FR_CON_02_a_grant_without_a_refresh_token_keeps_the_one_already_stored():
    """Google omits the refresh token on a repeat grant; the incremental grant must not lose it."""
    env = make_env()
    first = env.connect(OWNER, "gmail", SCOPES)
    env.connect(OWNER, "gmail", SCOPES + [DRIVE_FILE], refresh=False)

    env.broker.disconnect(OWNER, "gmail")

    assert first["refresh_token"] in env.google.revoked


# ---- invalid_grant: the connection expires -----------------------------------------------------


def test_FR_CON_02_invalid_grant_on_refresh_moves_the_connection_to_expired_and_emits_the_event():
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)
    env.emitted.clear()
    env.google.refresh_mode = "invalid_grant"
    env.clock.advance(EXPIRES_IN + 1)

    with pytest.raises(ConnectionExpired):
        token(env)

    assert env.broker.connection_state(OWNER, "gmail") == "expired"
    assert types_of(env.emitted) == ["connection.expired"]
    part = env.emitted[0]
    validate_part(part)
    assert part["data"] == {"connector": "gmail"}
    assert part["authz"] is None
    assert part["user_id"] == OWNER


def test_FR_CON_02_an_expired_connection_fails_fast_with_no_more_provider_calls_or_events():
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)
    env.google.refresh_mode = "invalid_grant"
    env.clock.advance(EXPIRES_IN + 1)
    with pytest.raises(ConnectionExpired):
        token(env)
    calls, events = len(env.google.calls), len(env.emitted)

    for _ in range(3):
        with pytest.raises(ConnectionExpired):
            token(env)

    assert len(env.google.calls) == calls
    assert len(env.emitted) == events


def test_FR_CON_02_consenting_again_after_expiry_brings_the_connection_back():
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)
    env.google.refresh_mode = "invalid_grant"
    env.clock.advance(EXPIRES_IN + 1)
    with pytest.raises(ConnectionExpired):
        token(env)
    env.google.refresh_mode = "ok"

    again = env.connect(OWNER, "gmail", SCOPES)

    assert env.broker.connection_state(OWNER, "gmail") == "connected"
    assert token(env) == again["access_token"]


@pytest.mark.parametrize("mode", ["unavailable", "network"])
def test_FR_CON_02_a_refresh_that_could_not_get_through_does_not_expire_the_connection(mode):
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)
    env.emitted.clear()
    env.google.refresh_mode = mode
    env.clock.advance(EXPIRES_IN + 1)

    with pytest.raises(TokenRefreshFailed):
        token(env)

    assert env.broker.connection_state(OWNER, "gmail") == "connected"
    assert env.emitted == []
    env.google.refresh_mode = "ok"
    assert token(env) in env.google.issued_access, "the next call tries again"


# ---- Concurrency -------------------------------------------------------------------------------


def run_concurrently(n, fn):
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def worker(i):
        barrier.wait()
        try:
            results[i] = ("ok", fn())
        except Exception as exc:  # noqa: BLE001 - the test inspects what each caller got
            results[i] = ("err", exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert all(r is not None for r in results), "a caller hung"
    return results


def test_FR_CON_02_concurrent_refreshes_for_one_connection_make_exactly_one_provider_call():
    env = make_env(latency_s=0.05)
    env.connect(OWNER, "gmail", SCOPES)
    env.clock.advance(EXPIRES_IN + 1)

    results = run_concurrently(16, lambda: token(env))

    assert [kind for kind, _ in results] == ["ok"] * 16
    assert len({value for _, value in results}) == 1, "every caller got the one new token"
    assert len(env.google.refresh_calls()) == 1


def test_FR_CON_02_concurrent_callers_of_a_rejected_refresh_make_one_call_and_emit_one_event():
    env = make_env(latency_s=0.05)
    env.connect(OWNER, "gmail", SCOPES)
    env.emitted.clear()
    env.google.refresh_mode = "invalid_grant"
    env.clock.advance(EXPIRES_IN + 1)

    results = run_concurrently(16, lambda: token(env))

    assert all(kind == "err" and isinstance(value, ConnectionExpired) for kind, value in results)
    assert len(env.google.refresh_calls()) == 1
    assert types_of(env.emitted) == ["connection.expired"]


def test_FR_CON_02_a_refresh_for_one_connection_does_not_refresh_another():
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)
    env.connect(OWNER, "google_drive", [DRIVE_FILE])
    env.clock.advance(EXPIRES_IN + 1)

    token(env)

    assert len(env.google.refresh_calls()) == 1


# ---- The adapter hand-off: scope check ---------------------------------------------------------


def test_FR_CON_02_a_token_is_not_handed_out_for_a_scope_that_was_never_granted():
    env = make_env()
    response = env.connect(OWNER, "gmail", SCOPES)

    with pytest.raises(InsufficientScope) as raised:
        token(env, scopes=SCOPES + [DRIVE_FILE])

    assert raised.value.missing == [DRIVE_FILE]
    assert leaks(str(raised.value) + repr(raised.value), [response["access_token"], response["refresh_token"]]) == []
    assert env.google.calls == []


def test_FR_CON_02_the_scope_check_cannot_be_skipped():
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)

    with pytest.raises(TypeError):
        env.broker.access_token_for_adapter(OWNER, "gmail")


def test_FR_CON_02_a_user_with_no_connection_gets_no_token():
    env = make_env()
    env.connect(OWNER, "gmail", SCOPES)

    with pytest.raises(NotConnected):
        token(env, user="u_other")
    with pytest.raises(NotConnected):
        token(env, connector="google_drive", scopes=[DRIVE_FILE])
