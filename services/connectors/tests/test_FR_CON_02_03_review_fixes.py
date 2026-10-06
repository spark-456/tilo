"""FR-CON-02 and FR-CON-03, review fixes (PR #123): one distinct line per scope for every schema-valid
declaration, delete_user leaving no token in any store, a KMS failure never losing a pending revoke,
consented only after the tokens are stored, malformed token bodies, the redirect URL, log and flow
hygiene. Written after the pinned tests; they never edit them. Tokens and secrets are runtime fakes.
"""

from __future__ import annotations

import logging
import threading

import pytest
from _oauth_lib import (
    CARD_ID,
    DRIVE_FILE,
    EXPIRES_IN,
    GMAIL_READONLY,
    OTHER,
    OWNER,
    RUN,
    WORLD,
    drive_decl,
    finish_flow,
    leaks,
    make_env,
    parse_auth_url,
    schema_errors,
    start_flow,
    types_of,
    validate_part,
)
from tilo_connectors.consent import ConsentRefused, ConsentService
from tilo_connectors.tokens import (
    InMemoryTokenStore,
    OAuthSettings,
    TokenBroker,
    TokenError,
    TokenRefreshFailed,
)

DRIVE_APPDATA = "https://www.googleapis.com/auth/drive.appdata"


def service_for(env, decl):
    assert schema_errors("connector.schema.json", decl) == [], "the declaration itself is valid"
    return ConsentService(
        connectors={decl["id"]: decl},
        broker=env.broker,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
    )


def card_for(service, capabilities):
    return service.build_consent_card(
        user_id=OWNER,
        connector="google_drive",
        capabilities=capabilities,
        card_id=CARD_ID,
        world_id=WORLD,
        run_id=RUN,
        building="B1",
        agent="A_dir",
        what_happened="Saving the report needs access to Drive.",
        why_it_matters="Without it the report stays in Tilo only.",
    )


def broker_with(env, **kwargs):
    return TokenBroker(
        store=env.store,
        kms=env.kms,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
        **kwargs,
    )


class FlakyKms:
    """Wraps a Kms; `fail` makes encrypt or decrypt raise a non-KMS error, like an outage."""

    def __init__(self, inner):
        self.inner, self.fail_encrypt, self.fail_decrypt = inner, False, False

    def encrypt(self, plaintext, *, aad):
        if self.fail_encrypt:
            raise RuntimeError("kms unavailable")
        return self.inner.encrypt(plaintext, aad=aad)

    def decrypt(self, ciphertext, *, aad):
        if self.fail_decrypt:
            raise RuntimeError("kms unavailable")
        return self.inner.decrypt(ciphertext, aad=aad)


# ---- consent lines: one distinct plain-language line per scope -----------------------------------


def test_FR_CON_03_two_scopes_sharing_one_action_show_one_line_and_stay_valid():
    env = make_env()
    decl = drive_decl()
    decl["scopes"]["write"] = [DRIVE_FILE, DRIVE_APPDATA]
    service = service_for(env, decl)

    card = card_for(service, ["write"])

    assert card["consent"]["scopes"] == ["Save finished reports in a Tilo folder in your Drive."]
    assert schema_errors("card.schema.json", card) == []
    flow = parse_auth_url(
        service.authorization_url(user_id=OWNER, connector="google_drive", capabilities=["write"], card_id=CARD_ID)
    )
    assert flow.scopes == [DRIVE_FILE, DRIVE_APPDATA]
    env.emitted.clear()
    code = env.google.issue_code(
        flow.scopes, challenge=flow.query["code_challenge"], redirect_uri=flow.query["redirect_uri"]
    )

    service.handle_callback(user_id=OWNER, state=flow.state, code=code)

    consented = env.parts_of("connection.consented")[0]
    validate_part(consented)
    assert consented["data"]["scopes"] == ["Save finished reports in a Tilo folder in your Drive."]


def test_FR_CON_03_a_scope_no_action_describes_is_refused_before_anything_is_emitted_or_minted():
    env = make_env()
    decl = drive_decl()
    decl["actions"] = [a for a in decl["actions"] if a["capability"] != "list"]
    service = service_for(env, decl)

    with pytest.raises(ConsentRefused):
        card_for(service, ["list"])
    with pytest.raises(ConsentRefused):
        service.authorization_url(user_id=OWNER, connector="google_drive", capabilities=["list"], card_id=CARD_ID)

    assert env.emitted == [] and env.google.calls == []
    assert service._flows == {}, "no flow was minted"
    assert card_for(service, ["write"])["consent"]["scopes"], "capabilities that are described still work"


# ---- callback: consented only after the tokens are stored; discarded tokens are revoked --------


def test_FR_CON_03_no_consented_event_when_the_tokens_cannot_be_stored_and_they_are_revoked():
    env = make_env()
    env.kms.inner = flaky = FlakyKms(env.kms.inner)
    flow = start_flow(env, OWNER, "gmail", ["send"])
    flaky.fail_encrypt = True

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER)

    assert env.emitted == [] and env.store.live_keys() == []
    assert len(env.google.revoked) == 1, "the issued grant is revoked, not left live"
    assert not env.google.live_refresh


def test_FR_CON_03_a_response_granting_none_of_the_asked_scopes_is_revoked_and_stores_nothing():
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["send"])

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER, granted=[GMAIL_READONLY])

    assert env.emitted == [] and env.store.live_keys() == []
    assert len(env.google.revoked) == 1


def test_FR_CON_03_discarded_tokens_are_not_revoked_when_the_user_already_has_a_grant():
    """Google shares one grant between tokens, so revoking the discarded ones would end the live one."""
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    flow = start_flow(env, OWNER, "gmail", ["send"])

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER, granted=[GMAIL_READONLY])

    assert env.google.revoked == []
    assert env.broker.granted_scopes(OWNER, "gmail") == frozenset({GMAIL_READONLY})


@pytest.mark.parametrize("bad", [None, "abc", True, 0, -5, 1e30, float("nan")])
def test_FR_CON_03_a_malformed_expires_in_refuses_the_callback_and_names_no_token(bad):
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["send"])
    code = env.google.issue_code(
        flow.scopes, challenge=flow.query["code_challenge"], redirect_uri=flow.query["redirect_uri"]
    )
    original = env.google._exchange

    def exchange(d):
        response = original(d)
        body = response.json()
        body["expires_in"] = bad
        response._body = body
        return response

    env.google._exchange = exchange

    with pytest.raises(ConsentRefused) as raised:
        env.service.handle_callback(user_id=OWNER, state=flow.state, code=code)

    assert env.emitted == [] and env.store.live_keys() == []
    assert leaks(f"{raised.value!s} {raised.value!r}", env.google.issued_access) == []


# ---- token body validation ---------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, "abc", True, 0, 1e30, float("nan"), [1]])
def test_FR_CON_02_a_malformed_expires_in_raises_a_fixed_text_token_error(bad):
    env = make_env()
    access = "tok-" + "ab" * 8
    response = {"access_token": access, "expires_in": bad, "scope": GMAIL_READONLY}

    with pytest.raises(TokenError) as raised:
        env.broker.store_tokens(OWNER, "gmail", response)

    assert type(raised.value) is TokenError and access not in str(raised.value)
    assert env.store.live_keys() == [] and env.emitted == []


@pytest.mark.parametrize("field", ["access_token", "refresh_token", "scope"])
def test_FR_CON_02_a_token_body_of_the_wrong_shape_is_refused(field):
    env = make_env()
    response = env.google.token_response([GMAIL_READONLY])
    response[field] = 12345

    with pytest.raises(TokenError):
        env.broker.store_tokens(OWNER, "gmail", response)

    assert env.store.live_keys() == []


def test_FR_CON_02_a_refresh_answer_with_a_malformed_body_is_a_failed_refresh_not_an_expiry():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.clock.advance(EXPIRES_IN + 1)
    original = env.google._token

    def token(d):
        response = original(d)
        body = response.json()
        body["expires_in"] = "abc"
        response._body = body
        return response

    env.google._token = token

    with pytest.raises(TokenRefreshFailed):
        env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])

    assert env.broker.connection_state(OWNER, "gmail") == "connected"


# ---- delete_user leaves no token in any store ---------------------------------------------------


def test_FR_CON_02_delete_user_drops_the_sealed_token_when_the_revoke_still_fails_and_raises_an_alert():
    env = make_env()
    alerts: list[dict] = []
    retry_store = InMemoryTokenStore()
    broker = broker_with(env, alert=alerts.append, retry_store=retry_store)
    broker.store_tokens(OTHER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.google.revoke_mode = "network"
    # An earlier failed disconnect left a sealed retry behind (the only connector then, so it revokes).
    broker.store_tokens(OWNER, "google_drive", env.google.token_response([DRIVE_FILE]))
    broker.disconnect(OWNER, "google_drive")
    assert len(retry_store.connectors_of(OWNER)) == 1
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    alerts.clear()

    broker.delete_user(OWNER)

    assert env.store.live_keys() == [(OTHER, "gmail")]
    assert retry_store.connectors_of(OWNER) == [], "no token in any store, retry copies included"
    assert len(alerts) == 2, "one for the connection, one for the dropped retry"
    for part in alerts:
        validate_part(part)
        assert part["user_id"] == OWNER


# ---- retry store: keyed by alert, bounded, sealed first -----------------------------------------


def test_FR_CON_02_two_failed_revokes_for_one_connector_keep_both_pending():
    env = make_env()
    retry_store = InMemoryTokenStore()
    broker = broker_with(env, alert=[].append, retry_store=retry_store)
    env.google.revoke_mode = "unavailable"
    for _ in range(2):
        broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
        broker.disconnect(OWNER, "gmail")

    assert len(retry_store.connectors_of(OWNER)) == 2, "the second does not overwrite the first"
    env.google.revoke_mode = "ok"
    assert broker.retry_pending_revokes(OWNER) == 2
    assert len(env.google.revoked) == 2


def test_FR_CON_02_a_pending_revoke_older_than_the_retention_limit_is_dropped_unrevoked(caplog):
    env = make_env()
    retry_store = InMemoryTokenStore()
    broker = broker_with(env, alert=[].append, retry_store=retry_store, retry_retention_s=3600)
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.google.revoke_mode = "unavailable"
    broker.disconnect(OWNER, "gmail")
    env.google.revoke_mode = "ok"
    env.clock.advance(3601)
    caplog.set_level(logging.WARNING)

    assert broker.retry_pending_revokes(OWNER) == 0

    assert retry_store.connectors_of(OWNER) == []
    assert env.google.revoked == []
    assert any("gmail" in r.getMessage() for r in caplog.records)


def test_FR_CON_02_a_kms_failure_while_sealing_the_retry_copy_keeps_the_record_and_its_pending_revoke():
    env = make_env()
    env.kms.inner = flaky = FlakyKms(env.kms.inner)
    retry_store = InMemoryTokenStore()
    broker = broker_with(env, alert=[].append, retry_store=retry_store)
    response = env.google.token_response([GMAIL_READONLY])
    broker.store_tokens(OWNER, "gmail", response)
    env.emitted.clear()
    env.google.revoke_mode = "unavailable"
    flaky.fail_encrypt = True

    with pytest.raises(RuntimeError):
        broker.disconnect(OWNER, "gmail")

    assert env.store.live_keys() == [(OWNER, "gmail")], "the record is not deleted"
    assert env.emitted == []
    flaky.fail_encrypt, env.google.revoke_mode = False, "ok"
    broker.disconnect(OWNER, "gmail")
    assert response["refresh_token"] in env.google.revoked


def test_FR_CON_02_without_an_alert_sink_a_failed_revoke_is_logged_as_an_error(caplog):
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.google.revoke_mode = "network"
    caplog.set_level(logging.WARNING)

    env.broker.disconnect(OWNER, "gmail")

    assert any(r.levelno >= logging.ERROR and "alert" in r.getMessage() for r in caplog.records)


def test_FR_CON_02_a_connector_id_with_a_newline_cannot_forge_a_log_line(caplog):
    env = make_env()
    env.connect(OWNER, "gmail\nERROR forged", [GMAIL_READONLY])
    env.google.revoke_mode = "network"
    caplog.set_level(logging.WARNING)

    env.broker.disconnect(OWNER, "gmail\nERROR forged")

    assert all("\n" not in r.getMessage() for r in caplog.records)


# ---- settings: the redirect base URL -----------------------------------------------------------


def settings_from(**extra):
    environ = {"GOOGLE_OAUTH_CLIENT_ID": "id-" + "a" * 8, "GOOGLE_OAUTH_CLIENT_SECRET": "cs-" + "b" * 8}
    return OAuthSettings.from_env({**environ, **extra})


def test_FR_CON_02_the_redirect_base_url_comes_from_the_environment():
    settings = settings_from(GOOGLE_OAUTH_REDIRECT_BASE_URL="https://api.tilo.example/")

    assert settings.redirect_uri == "https://api.tilo.example/oauth/google/callback"


@pytest.mark.parametrize("base", ["http://localhost:3000", "http://127.0.0.1:8080", "http://[::1]:8080"])
def test_FR_CON_02_plain_http_is_allowed_only_for_loopback(base):
    assert settings_from(GOOGLE_OAUTH_REDIRECT_BASE_URL=base).redirect_base_url == base


@pytest.mark.parametrize(
    "base", ["http://api.tilo.example", "ftp://localhost", "api.tilo.example", "http://localhost.evil.example"]
)
def test_FR_CON_02_a_non_https_redirect_base_outside_loopback_is_refused(base):
    with pytest.raises(ValueError, match="https"):
        settings_from(GOOGLE_OAUTH_REDIRECT_BASE_URL=base)
    with pytest.raises(ValueError, match="https"):
        OAuthSettings(client_id="x", client_secret="y", redirect_base_url=base)


# ---- consent state hygiene ---------------------------------------------------------------------


def test_FR_CON_03_the_flow_table_is_capped_per_user_and_keeps_the_newest():
    env = make_env()
    other = start_flow(env, OTHER, "gmail", ["send"])
    flows = [start_flow(env, OWNER, "gmail", ["send"]) for _ in range(60)]

    assert sum(1 for f in env.service._flows.values() if f.user_id == OWNER) <= 20
    with pytest.raises(ConsentRefused):
        finish_flow(env, flows[0], OWNER)
    finish_flow(env, flows[-1], OWNER)
    finish_flow(env, other, OTHER)  # another user's flow is never evicted by this one's


def test_FR_CON_03_a_flows_repr_does_not_show_the_pkce_verifier():
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["send"])
    held = env.service._flows[flow.state]

    assert held.verifier and held.verifier not in repr(held)


def test_FR_CON_03_concurrent_flow_starts_stay_within_the_cap():
    env = make_env()
    threads = [threading.Thread(target=start_flow, args=(env, OWNER, "gmail", ["send"])) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert sum(1 for f in env.service._flows.values() if f.user_id == OWNER) <= 20
    assert types_of(env.emitted) == []
