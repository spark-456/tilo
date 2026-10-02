"""FR-CON-02 and FR-CON-03, security fix pass on PR #123 (CON-D10, CON-D11): Google keeps one grant per
account and client, so a token Tilo discards or a connector it disconnects must not be revoked while
another connector is connected; a failure after the record is stored puts the earlier state back; the
KMS-unreadable ciphertext moves to the retry store unchanged; the redirect base needs a host. New tests
only: no pinned test is edited. Tokens and secrets are runtime fakes.
"""

from __future__ import annotations

import pytest
from _oauth_lib import (
    CARD_ID,
    DRIVE_FILE,
    DRIVE_METADATA,
    GMAIL_READONLY,
    OWNER,
    finish_flow,
    leaks,
    start_flow,
    types_of,
    validate_part,
)
from _shared_grant_lib import make_shared_env
from tilo_connectors.consent import ConsentRefused
from tilo_connectors.tokens import (
    InMemoryTokenStore,
    InsufficientScope,
    KmsError,
    NotConnected,
    OAuthSettings,
    TokenBroker,
)


def refused(env, flow, **kwargs):
    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER, **kwargs)


def gmail_still_usable(env) -> None:
    assert env.broker.connection_state(OWNER, "gmail") == "connected"
    assert env.google.grant_alive(), "the shared grant is alive at Google"
    token = env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])
    assert token


# ---- blocker 1: a discarded token never ends the shared grant ------------------------------------


def test_FR_CON_03_a_discarded_drive_callback_does_not_revoke_the_shared_gmail_grant():
    env = make_shared_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    # Google returns the combined token with only the Gmail scope: no Drive access was granted.
    refused(env, flow, granted=[GMAIL_READONLY])

    assert env.google.revoke_calls() == [], "no revoke while Gmail is connected on the same client"
    assert env.broker.connection_state(OWNER, "google_drive") is None
    gmail_still_usable(env)


def test_FR_CON_03_a_drive_callback_whose_kms_seal_fails_does_not_revoke_the_shared_gmail_grant():
    env = make_shared_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    env.kms.encrypt = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kms down"))

    refused(env, flow)
    del env.kms.encrypt  # the SpyKms method is back

    assert env.google.revoke_calls() == []
    assert env.broker.connection_state(OWNER, "google_drive") is None
    gmail_still_usable(env)


def test_FR_CON_03_a_discarded_token_is_revoked_when_the_user_holds_no_other_grant():
    env = make_shared_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    env.kms.encrypt = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kms down"))

    refused(env, flow)

    assert len(env.google.revoke_calls()) == 1, "nothing else is connected: the stray grant is ended"
    assert not env.google.grant_alive()


# ---- disconnect with another connector on the same client ----------------------------------------


def test_FR_CON_02_disconnecting_one_google_connector_keeps_the_grant_while_another_is_connected():
    env = make_shared_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.connect(OWNER, "google_drive", [DRIVE_FILE])

    result = env.broker.disconnect(OWNER, "google_drive")

    assert env.google.revoke_calls() == [], "revoking would end Gmail at Google too (CON-D10)"
    assert result.revoked_at_provider is False and result.provider_error is None
    assert env.broker.connection_state(OWNER, "google_drive") is None
    assert types_of(env.parts_of("connection.revoked")) == ["connection.revoked"]
    gmail_still_usable(env)

    last = env.broker.disconnect(OWNER, "gmail")  # the last connector revokes the grant

    assert last.revoked_at_provider is True and len(env.google.revoke_calls()) == 1
    assert not env.google.grant_alive()


# ---- blocker 2: a failure after the record is stored puts the earlier state back ----------------


def fail_on(emit_owner, event_type):
    real = emit_owner._emit

    def emit(part):
        if part["type"] == event_type:
            raise RuntimeError("event writer down")
        real(part)

    emit_owner._emit = emit


def test_FR_CON_03_a_failing_consented_emit_leaves_nothing_connected_and_consent_can_be_asked_again():
    env = make_shared_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    fail_on(env.service, "connection.consented")

    refused(env, flow)

    assert env.broker.connection_state(OWNER, "google_drive") is None, "no record is left"
    assert env.store.connectors_of(OWNER) == []
    with pytest.raises(NotConnected):
        env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
    assert env.parts_of("connection.consented") == [] and env.parts_of("connection.established") == []
    assert len(env.google.revoke_calls()) == 1, "the unrecorded grant is ended: nothing else is connected"
    again = env.service.authorization_url(
        user_id=OWNER, connector="google_drive", capabilities=["write"], card_id=CARD_ID
    )
    assert again is not None, "the person can consent again"


def test_FR_CON_03_a_failing_consented_emit_restores_the_earlier_scopes_of_that_connector():
    env = make_shared_env()
    env.connect(OWNER, "google_drive", [DRIVE_METADATA])
    before = env.store.get(OWNER, "google_drive")
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    fail_on(env.service, "connection.consented")

    refused(env, flow, granted=[DRIVE_METADATA, DRIVE_FILE])

    assert env.store.get(OWNER, "google_drive") == before, "the earlier record, byte for byte"
    assert env.broker.granted_scopes(OWNER, "google_drive") == {DRIVE_METADATA}
    with pytest.raises(InsufficientScope):
        env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
    assert env.google.revoke_calls() == [], "the user holds a connected connector: the grant stays"
    assert env.service.scopes_needed(user_id=OWNER, connector="google_drive", capabilities=["write"]) == [DRIVE_FILE]


def test_FR_CON_03_a_failing_established_emit_also_puts_the_earlier_state_back():
    env = make_shared_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    fail_on(env.broker, "connection.established")

    refused(env, flow)

    assert env.broker.connection_state(OWNER, "google_drive") is None
    assert env.service.scopes_needed(user_id=OWNER, connector="google_drive", capabilities=["write"]) == [DRIVE_FILE]
    for part in env.emitted:
        validate_part(part)


# ---- follow-ups ---------------------------------------------------------------------------------


def broker_with_retry(env, alerts):
    retry = InMemoryTokenStore()
    broker = TokenBroker(
        store=env.store,
        kms=env.kms,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
        alert=alerts.append,
        retry_store=retry,
    )
    return broker, retry


def test_FR_CON_02_a_kms_decrypt_failure_in_disconnect_keeps_the_ciphertext_for_a_later_revoke():
    env = make_shared_env()
    alerts: list[dict] = []
    broker, retry = broker_with_retry(env, alerts)
    response = env.google.token_response([GMAIL_READONLY])
    broker.store_tokens(OWNER, "gmail", response)
    stored = env.store.get(OWNER, "gmail")
    env.kms.decrypt = lambda *a, **k: (_ for _ in ()).throw(KmsError("kms down"))

    result = broker.disconnect(OWNER, "gmail")

    assert result.revoked_at_provider is False and env.google.revoke_calls() == []
    assert env.store.connectors_of(OWNER) == [], "the record is gone"
    (key,) = retry.connectors_of(OWNER)
    kept = retry.get(OWNER, key)
    assert all(kept[k] == stored[k] for k in ("wrapped_key", "nonce", "ciphertext")), "ciphertext unchanged"
    assert len(alerts) == 1 and validate_part(alerts[0]) is None
    assert broker.retry_pending_revokes(OWNER) == 0 and retry.connectors_of(OWNER) == [key], (
        "kept while the KMS is down"
    )

    del env.kms.decrypt
    assert broker.retry_pending_revokes(OWNER) == 1
    assert [c["token"] for c in env.google.revoke_calls()] == [response["refresh_token"]]
    assert retry.connectors_of(OWNER) == []
    blob = repr(alerts) + repr(env.emitted) + repr(kept.keys())
    assert leaks(blob, [response["access_token"], response["refresh_token"]]) == []


def test_FR_CON_02_a_kept_ciphertext_is_dropped_after_the_retention_even_if_the_kms_stays_down():
    env = make_shared_env()
    broker, retry = broker_with_retry(env, [])
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.kms.decrypt = lambda *a, **k: (_ for _ in ()).throw(KmsError("kms down"))
    broker.disconnect(OWNER, "gmail")
    (key,) = retry.connectors_of(OWNER)
    record = retry.get(OWNER, key)
    record["created_at"] = "2099-01-01T00:00:00.000Z"  # tampering with the unbound date does not extend it
    retry.put(OWNER, key, record)

    env.clock.advance(7 * 86400 + 1)

    assert broker.retry_pending_revokes(OWNER) == 0
    assert retry.connectors_of(OWNER) == [], "dropped by the age the record's own id carries"


@pytest.mark.parametrize(
    "base",
    [
        "https:evil.example",
        "https://",
        "http://",
        "https://user:pw@h.example",
        "http://localhost@evil.example",
        "https://h.example?next=1",
        "https://h.example#frag",
        "https://h.example/a b",
        " https://h.example",
        "https://h.example\n",
        "https://h.example:notaport",
    ],
)
def test_FR_CON_03_a_redirect_base_without_a_host_or_with_user_query_fragment_or_spaces_is_refused(base):
    with pytest.raises(ValueError) as caught:
        OAuthSettings("client", "secret", base)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("base", ["https://tilo.example", "https://tilo.example:8443/base/", "http://127.0.0.1:8080"])
def test_FR_CON_03_a_plain_https_or_loopback_redirect_base_is_accepted(base):
    assert OAuthSettings("client", "secret", base).redirect_uri.endswith("/oauth/google/callback")
