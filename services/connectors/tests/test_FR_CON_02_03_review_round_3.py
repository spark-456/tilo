"""FR-CON-02 and FR-CON-03, security round 3 on PR #123 (CON-D10, CON-D13): a connected record counts as a
live grant whether or not the KMS can read it; a pending revoke never fires while the user is connected
elsewhere; the check-then-revoke in disconnect is serialised per user; no adapter takes a token before
connection.consented is recorded; a failed rollback marks the record unusable; a future-dated retry key
is not kept for ever. New tests only: no pinned test is edited. Tokens and secrets are runtime fakes.
"""

from __future__ import annotations

import logging
import threading

import pytest
from _oauth_lib import (
    CARD_ID,
    DRIVE_FILE,
    GMAIL_READONLY,
    OWNER,
    finish_flow,
    leaks,
    start_flow,
)
from _shared_grant_lib import make_shared_env
from tilo_connectors._time import add_seconds
from tilo_connectors.consent import ConsentRefused
from tilo_connectors.tokens import (
    ConnectionExpired,
    InMemoryTokenStore,
    KmsError,
    NotConnected,
    TokenBroker,
    _ulid,
)


def kms_down(env) -> None:
    def down(*a, **k):
        raise KmsError("kms down")

    env.kms.encrypt = down
    env.kms.decrypt = down


def kms_back(env) -> None:
    del env.kms.encrypt
    del env.kms.decrypt


def broker_with_retry(env, alerts=None):
    retry = InMemoryTokenStore()
    broker = TokenBroker(
        store=env.store,
        kms=env.kms,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
        alert=(alerts if alerts is not None else []).append,
        retry_store=retry,
    )
    return broker, retry


def gmail_still_usable(env, broker=None) -> None:
    broker = broker or env.broker
    assert broker.connection_state(OWNER, "gmail") == "connected"
    assert env.google.grant_alive(), "the shared grant is alive at Google"
    assert broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])


# ---- blocker 1: a connected record is a live grant even when the KMS cannot read it -------------


def test_FR_CON_03_a_drive_callback_during_a_full_kms_outage_does_not_revoke_the_gmail_grant():
    env = make_shared_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    kms_down(env)

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER)
    kms_back(env)

    assert env.google.revoke_calls() == [], "Gmail is connected: the shared grant must not be revoked"
    assert env.broker.connection_state(OWNER, "google_drive") is None
    gmail_still_usable(env)


def test_FR_CON_02_a_drive_disconnect_during_a_kms_outage_does_not_end_gmail_after_the_kms_returns():
    env = make_shared_env()
    broker, retry = broker_with_retry(env)
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]))
    kms_down(env)

    result = broker.disconnect(OWNER, "google_drive")
    assert result.revoked_at_provider is False and env.google.revoke_calls() == []
    kms_back(env)
    broker.retry_pending_revokes(OWNER)

    assert env.google.revoke_calls() == [], "the retry must not fire while Gmail is connected"
    gmail_still_usable(env, broker)


# ---- blocker 2: a pending revoke never fires while the user is connected elsewhere --------------


def test_FR_CON_02_a_pending_revoke_does_not_fire_after_the_user_connects_another_connector():
    env = make_shared_env()
    alerts: list[dict] = []
    broker, retry = broker_with_retry(env, alerts)
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.google.revoke_mode = "network"
    assert broker.disconnect(OWNER, "gmail").revoked_at_provider is False  # kept for retry
    assert len(retry.connectors_of(OWNER)) == 1 and len(alerts) == 1
    env.google.revoke_mode = "ok"
    broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]))
    calls_before = len(env.google.revoke_calls())

    assert broker.retry_pending_revokes(OWNER) == 0

    assert len(env.google.revoke_calls()) == calls_before, "no revoke while Drive is connected"
    assert broker.connection_state(OWNER, "google_drive") == "connected"
    assert env.google.grant_alive(), "Drive's grant stays alive"
    assert broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
    assert len(retry.connectors_of(OWNER)) == 1, "kept (CON-D10) until the retention ends"


def test_FR_CON_02_a_kept_pending_revoke_fires_once_the_last_connector_is_gone():
    env = make_shared_env()
    broker, retry = broker_with_retry(env)
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.google.revoke_mode = "network"
    broker.disconnect(OWNER, "gmail")
    env.google.revoke_mode = "ok"
    broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]))
    broker.retry_pending_revokes(OWNER)
    env.store.delete(OWNER, "google_drive")  # the user is no longer connected anywhere

    assert broker.retry_pending_revokes(OWNER) == 1

    assert not env.google.grant_alive() and retry.connectors_of(OWNER) == []


# ---- two disconnects at once cannot both skip the revoke ----------------------------------------


def test_FR_CON_02_two_concurrent_disconnects_still_revoke_the_grant_once():
    env = make_shared_env()
    broker, _retry = broker_with_retry(env)
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]))
    real = broker.has_live_grant
    gate = threading.Barrier(2)

    def synced(user, *, excluding=None):
        answer = real(user, excluding=excluding)
        try:
            gate.wait(timeout=0.5)  # forces the interleave if nothing serialises the two checks
        except threading.BrokenBarrierError:
            pass
        return answer

    broker.has_live_grant = synced  # type: ignore[method-assign]
    threads = [threading.Thread(target=broker.disconnect, args=(OWNER, c)) for c in ("gmail", "google_drive")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(env.google.revoke_calls()) == 1, "the last of the two revokes the grant"
    assert not env.google.grant_alive()
    assert env.store.connectors_of(OWNER) == []


# ---- no adapter takes a token before connection.consented is recorded ---------------------------


def adapter_in_a_thread(broker, outcome: dict, emitted) -> threading.Thread:
    def run() -> None:
        try:
            outcome["token"] = broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
            outcome["established_seen"] = [p["type"] for p in emitted if p["type"] == "connection.established"]
        except Exception as error:  # noqa: BLE001
            outcome["error"] = error

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_FR_CON_03_an_adapter_waits_for_the_connection_events_before_it_gets_the_new_token():
    env = make_shared_env()
    outcome: dict = {}
    seen: dict = {}

    def hook() -> None:
        seen["thread"] = adapter_in_a_thread(env.broker, outcome, env.emitted)
        seen["thread"].join(timeout=0.3)
        seen["blocked"] = seen["thread"].is_alive()

    env.broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]), before_established=hook)
    seen["thread"].join(timeout=10)

    assert seen["blocked"], "the adapter must not get a token inside the window"
    assert outcome.get("token"), outcome
    assert outcome["established_seen"] == ["connection.established"], "only after the established event"


def test_FR_CON_03_an_adapter_never_sees_a_connection_that_was_rolled_back():
    env = make_shared_env()
    outcome: dict = {}
    seen: dict = {}

    def hook() -> None:
        seen["thread"] = adapter_in_a_thread(env.broker, outcome, env.emitted)
        seen["thread"].join(timeout=0.3)
        seen["blocked"] = seen["thread"].is_alive()
        raise RuntimeError("event writer down")

    with pytest.raises(RuntimeError):
        env.broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]), before_established=hook)
    seen["thread"].join(timeout=10)

    assert seen["blocked"]
    assert "token" not in outcome and isinstance(outcome.get("error"), NotConnected)


# ---- a rollback that itself fails leaves the record unusable ------------------------------------


def _raise_os(*args, **kwargs):
    raise OSError("store down")


def test_FR_CON_03_a_failed_rollback_logs_the_original_error_and_leaves_no_usable_record(caplog):
    env = make_shared_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    real = env.service._emit

    def emit(part):
        if part["type"] == "connection.consented":
            env.store.delete = _raise_os  # type: ignore[method-assign]  # the rollback delete will fail
            raise RuntimeError("event writer down")
        real(part)

    env.service._emit = emit

    with caplog.at_level(logging.ERROR, logger="tilo_connectors"), pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER)
    del env.store.delete

    assert any("RuntimeError" in r.getMessage() for r in caplog.records), "the original error is logged"
    assert leaks(caplog.text, list(env.google.issued_access) + list(env.google.live_refresh)) == []
    assert env.broker.connection_state(OWNER, "google_drive") != "connected"
    with pytest.raises((NotConnected, ConnectionExpired)):
        env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
    assert env.parts_of("connection.consented") == [] and env.parts_of("connection.established") == []


def test_FR_CON_03_a_rollback_whose_delete_fails_but_whose_marker_lands_marks_the_record_unusable():
    env = make_shared_env()
    seen: dict = {}

    def hook() -> None:
        env.store.delete = _raise_os  # type: ignore[method-assign]  # only the rollback delete fails
        raise RuntimeError("event writer down")

    with pytest.raises(RuntimeError) as caught:
        env.broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]), before_established=hook)
    seen["error"] = caught.value
    del env.store.delete

    assert not isinstance(seen["error"], OSError), "the original error surfaces, not the rollback's"
    assert env.broker.connection_state(OWNER, "google_drive") != "connected"
    assert not env.broker.has_live_grant(OWNER)
    with pytest.raises((NotConnected, ConnectionExpired)):
        env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
    again = env.service.authorization_url(
        user_id=OWNER, connector="google_drive", capabilities=["write"], card_id=CARD_ID
    )
    assert again is not None


# ---- a future-dated retry key is not kept for ever ----------------------------------------------


def _moved_entry(env, broker, retry):
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    kms_down(env)
    broker.disconnect(OWNER, "gmail")  # the unreadable ciphertext moves to the retry store
    (key,) = retry.connectors_of(OWNER)
    return key, retry.get(OWNER, key)


def test_FR_CON_02_a_far_future_dated_retry_key_is_dropped_as_malformed():
    env = make_shared_env()
    broker, retry = broker_with_retry(env)
    key, record = _moved_entry(env, broker, retry)
    retry.delete(OWNER, key)
    retry.put(OWNER, _ulid("2099-01-01T00:00:00.000Z"), record)

    assert broker.retry_pending_revokes(OWNER) == 0

    assert retry.connectors_of(OWNER) == [], "an unreadable entry with a key from the future is not kept"


def test_FR_CON_02_a_retry_key_within_clock_skew_keeps_an_age_of_zero_not_a_negative_one():
    env = make_shared_env()
    broker, retry = broker_with_retry(env)
    key, record = _moved_entry(env, broker, retry)
    retry.delete(OWNER, key)
    skewed = _ulid(add_seconds(env.clock(), 30))  # a few seconds ahead of the clock
    retry.put(OWNER, skewed, record)

    assert broker.retry_pending_revokes(OWNER) == 0

    assert retry.connectors_of(OWNER) == [skewed], "within skew: kept while the KMS may come back"
