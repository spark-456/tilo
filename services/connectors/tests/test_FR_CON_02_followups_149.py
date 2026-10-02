"""FR-CON-02 and FR-CON-03, follow-ups of issue #149 (PR #123 security r4) and the #163 force_refresh item.

store_tokens takes the user lock before the connector lock, and a discarded consent token is checked and
revoked under it, so a retry, discard or disconnect racing a new connection cannot end the shared grant
(CON-D10); no lock is held while the consented hook, the established emit or the alert sink run; a
rollback marker emits connection.expired; a revoke skipped only for an unreadable sibling is kept for
later; the last disconnect retries the pending revokes; a KMS failure in a refresh is TokenRefreshFailed.
New tests only: no pinned test is edited. Tokens and secrets are runtime fakes.
"""

from __future__ import annotations

import threading

import pytest
from _oauth_lib import DRIVE_FILE, DRIVE_METADATA, GMAIL_READONLY, OWNER, finish_flow, leaks, make_env, start_flow
from _oauth_lib import validate_part as valid_part
from _shared_grant_lib import make_shared_env
from tilo_connectors.consent import ConsentRefused
from tilo_connectors.tokens import InMemoryTokenStore, KmsError, TokenBroker, TokenError, TokenRefreshFailed


def broker_for(env, alert=None):
    retry = InMemoryTokenStore()
    broker = TokenBroker(
        store=env.store,
        kms=env.kms,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
        alert=alert or (lambda part: None),
        retry_store=retry,
    )
    return broker, retry


def connected_and_alive(env, broker, connector, scope) -> None:
    assert broker.connection_state(OWNER, connector) == "connected"
    assert env.google.grant_alive(), "the shared grant is alive at Google"
    assert broker.access_token_for_adapter(OWNER, connector, required_scopes=[scope])


def finishes(fn) -> threading.Thread:
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    thread.join(timeout=5)
    return thread


def race(env, broker, connector, scopes, rival_call) -> None:
    """Hold a store_tokens inside its KMS seal (after it took its locks, before its put), run the rival
    meanwhile, then let the store finish. Without the user lock the rival checks and revokes in the window."""
    entered, release = threading.Event(), threading.Event()
    real = env.kms.encrypt

    def encrypt(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            release.wait(timeout=5)
        return real(*args, **kwargs)

    env.kms.encrypt = encrypt
    response = env.google.token_response(scopes)
    store = threading.Thread(target=broker.store_tokens, args=(OWNER, connector, response), daemon=True)
    store.start()
    assert entered.wait(timeout=5)
    rival = threading.Thread(target=rival_call, daemon=True)
    rival.start()
    rival.join(timeout=0.5)
    release.set()
    store.join(timeout=5)
    rival.join(timeout=5)
    del env.kms.encrypt
    assert not store.is_alive() and not rival.is_alive()


# ---- item 1: one test per interleave -------------------------------------------------------------


def test_FR_CON_02_a_retry_racing_a_drive_store_leaves_the_grant_alive_and_drive_connected():
    env = make_shared_env()
    broker, retry = broker_for(env)
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.google.revoke_mode = "network"
    broker.disconnect(OWNER, "gmail")  # the only connector: its failed revoke is kept for retry
    env.google.revoke_mode = "ok"
    assert len(retry.connectors_of(OWNER)) == 1

    race(env, broker, "google_drive", [DRIVE_FILE], lambda: broker.retry_pending_revokes(OWNER))

    connected_and_alive(env, broker, "google_drive", DRIVE_FILE)


def test_FR_CON_03_a_discard_racing_a_gmail_store_leaves_the_grant_alive_and_gmail_connected():
    env = make_shared_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    outcome: dict = {}

    def discard() -> None:
        try:
            finish_flow(env, flow, OWNER, granted=[GMAIL_READONLY])  # no Drive scope: the tokens are discarded
        except ConsentRefused as error:
            outcome["refused"] = error

    race(env, env.broker, "gmail", [GMAIL_READONLY], discard)

    assert "refused" in outcome
    connected_and_alive(env, env.broker, "gmail", GMAIL_READONLY)


def test_FR_CON_02_disconnecting_gmail_racing_a_drive_store_leaves_the_grant_alive_and_drive_connected():
    env = make_shared_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])

    race(env, env.broker, "google_drive", [DRIVE_FILE], lambda: env.broker.disconnect(OWNER, "gmail"))

    assert env.broker.connection_state(OWNER, "gmail") is None
    connected_and_alive(env, env.broker, "google_drive", DRIVE_FILE)


# ---- item 2: no lock is held while a hook or a sink runs -----------------------------------------


def test_FR_CON_03_a_hook_calling_back_into_the_broker_for_the_same_user_and_connector_does_not_hang():
    env = make_shared_env()
    seen: list[str] = []

    def hook() -> None:
        calls = (
            lambda: env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE]),
            lambda: env.broker.disconnect(OWNER, "google_drive"),
            lambda: env.broker.retry_pending_revokes(OWNER),
        )
        for call in calls:
            try:
                call()
                seen.append("returned")
            except TokenError:
                seen.append("refused")

    response = env.google.token_response([DRIVE_FILE])
    thread = finishes(lambda: env.broker.store_tokens(OWNER, "google_drive", response, before_established=hook))

    assert not thread.is_alive(), "a hook calling back into the broker must not hang it"
    assert seen == ["refused", "refused", "returned"], "nothing of it is handed out or removed before its events"
    assert [p["type"] for p in env.parts_of("connection.established")] == ["connection.established"]
    connected_and_alive(env, env.broker, "google_drive", DRIVE_FILE)


def test_FR_CON_02_an_alert_sink_calling_back_into_the_broker_for_the_same_user_does_not_hang():
    env = make_shared_env()
    retried: list[int] = []
    broker, retry = broker_for(env, alert=lambda part: retried.append(broker.retry_pending_revokes(OWNER)))
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.google.revoke_mode = "unavailable"

    thread = finishes(lambda: broker.disconnect(OWNER, "gmail"))

    assert not thread.is_alive(), "an alert sink calling back into the broker must not hang it"
    assert retried == [0] and len(retry.connectors_of(OWNER)) == 1, "still kept: Google is down"
    assert broker.connection_state(OWNER, "gmail") is None


# ---- item 3: the rollback marker is announced -----------------------------------------------------


def test_FR_CON_03_a_rollback_marker_replacing_a_connected_record_emits_connection_expired():
    env = make_shared_env()
    env.connect(OWNER, "google_drive", [DRIVE_METADATA])
    real_put = env.store.put

    def hook() -> None:
        def put(user_id, connector, record):
            if record.get("state") != "expired":
                raise OSError("store down")  # the restore fails; the marker lands
            real_put(user_id, connector, record)

        env.store.put = put
        raise RuntimeError("event writer down")

    response = env.google.token_response([DRIVE_METADATA, DRIVE_FILE])
    with pytest.raises(RuntimeError):
        env.broker.store_tokens(OWNER, "google_drive", response, before_established=hook)
    del env.store.put

    assert env.broker.connection_state(OWNER, "google_drive") == "expired"
    (part,) = env.parts_of("connection.expired")
    valid_part(part)
    assert part["data"] == {"connector": "google_drive"} and part["authz"] is None and part["user_id"] == OWNER


# ---- item 4 and item 6: deferred revokes ----------------------------------------------------------


def test_FR_CON_02_a_revoke_skipped_only_for_an_unreadable_sibling_keeps_the_readable_token_for_later():
    env = make_shared_env()
    alerts: list[dict] = []
    broker, retry = broker_for(env, alert=alerts.append)
    gmail = env.google.token_response([GMAIL_READONLY])
    drive = env.google.token_response([DRIVE_FILE])
    broker.store_tokens(OWNER, "gmail", gmail)
    broker.store_tokens(OWNER, "google_drive", drive)
    broken = env.store.get(OWNER, "gmail")
    broken["expires_at"] = "2099-01-01T00:00:00.000Z"  # bound into the AES-GCM context: never readable again
    env.store.put(OWNER, "gmail", broken)

    broker.disconnect(OWNER, "google_drive")

    assert env.google.revoke_calls() == [], "Gmail still counts as connected (CON-D10)"
    assert len(retry.connectors_of(OWNER)) == 1, "Drive's readable token is kept as the deferred revoke"
    assert broker.retry_pending_revokes(OWNER) == 0, "held while the unreadable Gmail record is connected"

    broker.disconnect(OWNER, "gmail")  # the last connector goes

    assert drive["refresh_token"] in [c["token"] for c in env.google.revoke_calls()]
    assert not env.google.grant_alive(), "the grant ends once nothing is connected"
    for part in alerts:
        valid_part(part)
    secrets_ = [gmail["access_token"], gmail["refresh_token"], drive["access_token"], drive["refresh_token"]]
    assert leaks(repr(alerts) + repr(env.emitted), secrets_) == []


def test_FR_CON_02_the_last_disconnect_retries_the_users_pending_revokes():
    env = make_shared_env()
    broker, retry = broker_for(env)
    gmail = env.google.token_response([GMAIL_READONLY])
    broker.store_tokens(OWNER, "gmail", gmail)
    env.google.revoke_mode = "network"
    broker.disconnect(OWNER, "gmail")
    env.google.revoke_mode = "ok"
    broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]))
    assert broker.retry_pending_revokes(OWNER) == 0, "kept while Drive is connected"

    result = broker.disconnect(OWNER, "google_drive")

    assert result.revoked_at_provider is True
    assert gmail["refresh_token"] in [c["token"] for c in env.google.revoke_calls()]
    assert retry.connectors_of(OWNER) == [], "the last disconnect retried the pending revoke"


# ---- #163: a KMS failure inside a forced refresh ---------------------------------------------------


@pytest.mark.parametrize("failure", [KmsError, RuntimeError])
def test_FR_CON_02_a_kms_encrypt_failure_in_a_forced_refresh_raises_token_refresh_failed(failure):
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])

    def down(*args, **kwargs):
        raise failure("kms down")

    env.kms.encrypt = down
    with pytest.raises(TokenRefreshFailed) as caught:
        env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY], force_refresh=True)
    del env.kms.encrypt

    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert leaks(repr(caught.value), list(env.google.issued_access) + list(env.google.live_refresh)) == []
    assert env.broker.connection_state(OWNER, "gmail") == "connected"
