"""FR-CON-02 (PRD 12.1 "Token broker", 16.1 rule 2, SEC-02): OAuth tokens are envelope-encrypted
with a KMS key and stored per user; the store only ever holds ciphertext, and a stored record is
useless outside the user and connector it was written for.

Cloud KMS is not available in dev (ADR-0003), so the Kms interface is tested through FakeKms (a
local envelope of a runtime-generated key). CloudKms is a thin, unexercised adapter: only its
shape is checked here.
"""

from __future__ import annotations

import pytest
from _oauth_lib import (
    DRIVE_FILE,
    GMAIL_READONLY,
    OTHER,
    OWNER,
    fake_secret,
    leaks,
    make_env,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_connectors.tokens import CloudKms, FakeKms, KmsError, TokenError

# ---- FakeKms: the local stand-in for Cloud KMS ------------------------------------------------


def test_FR_CON_02_fake_kms_round_trips_and_hides_the_plaintext():
    kms = FakeKms()
    plaintext = b"data-key-" + bytes(range(16))

    wrapped = kms.encrypt(plaintext, aad=b"u_owner/gmail")

    assert plaintext not in wrapped
    assert kms.decrypt(wrapped, aad=b"u_owner/gmail") == plaintext


def test_FR_CON_02_fake_kms_encrypting_twice_gives_different_ciphertexts():
    kms = FakeKms()
    assert kms.encrypt(b"same plaintext", aad=b"x") != kms.encrypt(b"same plaintext", aad=b"x")


def test_FR_CON_02_fake_kms_key_is_generated_at_runtime_per_instance():
    wrapped = FakeKms().encrypt(b"secret data key", aad=b"x")
    with pytest.raises(KmsError):
        FakeKms().decrypt(wrapped, aad=b"x")


def test_FR_CON_02_fake_kms_refuses_a_different_context_or_a_tampered_ciphertext():
    kms = FakeKms()
    wrapped = kms.encrypt(b"secret data key", aad=b"u_owner/gmail")

    with pytest.raises(KmsError):
        kms.decrypt(wrapped, aad=b"u_other/gmail")
    tampered = bytes([wrapped[0] ^ 1]) + wrapped[1:]
    with pytest.raises(KmsError):
        kms.decrypt(tampered, aad=b"u_owner/gmail")


def test_FR_CON_02_cloud_kms_adapter_exists_with_the_kms_shape():
    assert callable(getattr(CloudKms, "encrypt", None))
    assert callable(getattr(CloudKms, "decrypt", None))


# ---- The broker stores ciphertext only --------------------------------------------------------


def test_FR_CON_02_tokens_are_stored_only_as_ciphertext():
    env = make_env()
    response = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    plaintexts = [response["access_token"], response["refresh_token"]]

    assert env.store.live_keys() == [(OWNER, "gmail")], "one record per user and connector"
    assert leaks(env.store.live_text(), plaintexts) == []
    assert leaks(env.store.ever_text(), plaintexts) == [], "not even briefly, in any form"


def test_FR_CON_02_the_kms_wraps_a_data_key_and_never_sees_a_token():
    env = make_env()
    response = env.connect(OWNER, "gmail", [GMAIL_READONLY])

    assert env.kms.encrypted, "the data key is wrapped by the KMS"
    for plaintext in env.kms.encrypted:
        text = plaintext.decode("latin-1")
        assert response["access_token"] not in text
        assert response["refresh_token"] not in text
        assert len(plaintext) in (16, 24, 32), "an AES-sized data key, not a token"


def test_FR_CON_02_the_stored_token_is_recovered_by_unwrapping_through_the_kms():
    env = make_env()
    response = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    before = env.kms.decrypt_calls

    token = env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])

    assert token == response["access_token"]
    assert env.kms.decrypt_calls > before


def test_FR_CON_02_every_connection_has_its_own_data_key():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    first = list(env.kms.encrypted)
    env.connect(OTHER, "gmail", [GMAIL_READONLY])
    env.connect(OWNER, "google_drive", [DRIVE_FILE])
    later = env.kms.encrypted[len(first) :]

    assert set(first).isdisjoint(later), "a data key is never reused for another user or connector"
    assert len(set(env.kms.encrypted)) == len(env.kms.encrypted), "or twice"


def test_FR_CON_02_a_stored_record_is_useless_in_another_users_slot():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.connect(OTHER, "gmail", [GMAIL_READONLY])
    # Someone with write access to the store copies the owner's record over the other user's.
    env.store.put(OTHER, "gmail", env.store.get(OWNER, "gmail"))

    with pytest.raises(TokenError):
        env.broker.access_token_for_adapter(OTHER, "gmail", required_scopes=[GMAIL_READONLY])


def test_FR_CON_02_a_tampered_record_never_yields_a_token():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    record = env.store.get(OWNER, "gmail")
    for key, value in list(record.items()):
        if isinstance(value, str) and len(value) > 20 and key not in ("scopes", "expires_at"):
            record[key] = value[:-4] + ("AAAA" if not value.endswith("AAAA") else "BBBB")
    env.store.put(OWNER, "gmail", record)

    with pytest.raises(TokenError):
        env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])


def test_FR_CON_02_the_encryption_survives_a_restart_with_the_same_key_and_store():
    """A second broker over the same store and the same KMS key (a new Cloud Run instance) reads
    what the first wrote."""
    from tilo_connectors.tokens import TokenBroker

    env = make_env()
    response = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    second = TokenBroker(
        store=env.store,
        kms=env.kms,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=[].append,
    )

    assert second.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY]) == response["access_token"]


def test_FR_CON_02_the_in_memory_store_works_as_the_dev_default():
    from _connectors_lib import ManualClock
    from _oauth_lib import FakeGoogle
    from tilo_connectors.tokens import InMemoryTokenStore, OAuthSettings, TokenBroker

    client_id, client_secret = fake_secret("client"), fake_secret("cs")
    settings_ = OAuthSettings(client_id=client_id, client_secret=client_secret)
    google = FakeGoogle(client_id=client_id, client_secret=client_secret)
    broker = TokenBroker(
        store=InMemoryTokenStore(),
        kms=FakeKms(),
        http=google,
        settings=settings_,
        clock=ManualClock("2026-10-02T09:00:00.000Z"),
        emit=[].append,
    )
    response = google.token_response([GMAIL_READONLY])

    broker.store_tokens(OWNER, "gmail", response)

    assert broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY]) == response["access_token"]
    broker.disconnect(OWNER, "gmail")
    assert broker.connection_state(OWNER, "gmail") is None


# ---- Property: any token round-trips and never lands in the store -----------------------------

hex_tokens = st.binary(min_size=12, max_size=96).map(lambda b: b.hex())


@settings(max_examples=40, deadline=None)
@given(access=hex_tokens, refresh=hex_tokens)
def test_FR_CON_02_property_any_token_round_trips_and_is_never_stored_in_the_clear(access, refresh):
    env = make_env()
    response = {"access_token": access, "refresh_token": refresh, "expires_in": 3599, "scope": GMAIL_READONLY}

    env.broker.store_tokens(OWNER, "gmail", response)

    assert env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY]) == access
    assert leaks(env.store.ever_text(), [access, refresh]) == []
    assert all(access not in p.hex() and refresh not in p.hex() for p in env.kms.encrypted)
