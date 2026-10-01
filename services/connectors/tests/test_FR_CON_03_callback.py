"""FR-CON-03 (PRD 10.1 "only a person grants a connection", 12.1, 16.1 rule 2, event.rules.md EV-04):
the OAuth callback. The state value is bound to the user, the connector and a nonce, expires, and
works once; a wrong, forged, reused, expired or someone else's state is refused before any code is
exchanged; the granted scopes are what the token response says, never what was asked for.

PRD silent on the state lifetime. Default chosen: `state_ttl_s = 600` (ten minutes, about the life of
a Google authorisation code), tested at 599 s and 601 s; with the default it is accepted after one
minute and refused after an hour. PRD silent on a denied consent: the connection waits (PRD 10.2),
nothing is stored, the state is spent.

ConsentService.handle_callback(user_id=, state=, code=None, error=None) -> ConsentResult
(connector, card_id, granted_scopes: frozenset[str]); refusals raise ConsentRefused. `user_id` is the
signed-in user at the callback, as authenticated by tilo-api.
"""

from __future__ import annotations

import logging
import threading

import pytest
from _oauth_lib import (
    CARD_ID,
    DRIVE_FILE,
    DRIVE_READONLY,
    GMAIL_COMPOSE,
    GMAIL_READONLY,
    GMAIL_SEND,
    OTHER,
    OWNER,
    START,
    action_description,
    drive_decl,
    finish_flow,
    gmail_decl,
    leaks,
    make_env,
    start_flow,
    types_of,
    validate_part,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_connectors.consent import ConsentRefused


def assert_nothing_happened(env):
    assert env.google.exchange_calls() == [], "refused before any code is exchanged"
    assert env.store.live_keys() == [], "no token stored"
    assert env.emitted == [], "no event"


def flip(state: str) -> str:
    return state[:-1] + ("A" if state[-1] != "A" else "B")


# ---- The granted path --------------------------------------------------------------------------


def test_FR_CON_03_a_valid_callback_connects_with_the_scopes_google_granted():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    result = finish_flow(env, flow, OWNER)

    assert result.connector == "google_drive"
    assert result.card_id == CARD_ID
    assert result.granted_scopes == frozenset({DRIVE_FILE})
    assert env.broker.connection_state(OWNER, "google_drive") == "connected"
    assert env.broker.granted_scopes(OWNER, "google_drive") == frozenset({DRIVE_FILE})
    token = env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
    assert token in env.google.issued_access
    assert leaks(env.store.ever_text(), [token]) == []


def test_FR_CON_03_a_grant_emits_consented_by_the_person_then_established():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    env.clock.advance(30)

    finish_flow(env, flow, OWNER)

    assert types_of(env.emitted) == ["connection.consented", "connection.established"]
    consented, established = env.emitted
    for part in env.emitted:
        validate_part(part)
        assert part["user_id"] == OWNER
    assert consented["data"] == {
        "connector": "google_drive",
        "card_id": CARD_ID,
        "scopes": [action_description(drive_decl(), "write")],
    }
    assert consented["authz"]["by"] == "person" and consented["authz"]["ref"] == OWNER
    assert consented["authz"]["at"] == "2026-10-02T09:00:30.000Z"
    assert established["data"] == {"connector": "google_drive"}
    assert established["authz"] is None


def test_FR_CON_03_the_tokens_are_stored_through_the_broker_encrypted():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    finish_flow(env, flow, OWNER)

    issued = env.google.issued_access + list(env.google.live_refresh)
    assert env.store.live_keys() == [(OWNER, "google_drive")]
    assert leaks(env.store.ever_text(), issued) == []
    assert env.kms.encrypted, "wrapped by the KMS"


# ---- Granted scopes come from the response, never the request ---------------------------------


def test_FR_CON_03_a_scope_the_user_unticked_is_not_recorded_as_granted():
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["write", "send"])
    assert flow.scopes == [GMAIL_COMPOSE, GMAIL_SEND]

    result = finish_flow(env, flow, OWNER, granted=[GMAIL_COMPOSE])  # Google's granular consent

    assert result.granted_scopes == frozenset({GMAIL_COMPOSE})
    assert env.broker.granted_scopes(OWNER, "gmail") == frozenset({GMAIL_COMPOSE})
    assert env.service.scopes_needed(user_id=OWNER, connector="gmail", capabilities=["send"]) == [GMAIL_SEND]
    with pytest.raises(Exception, match="(?i)scope|insufficient"):
        env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_SEND])


def test_FR_CON_03_the_consented_event_lists_only_what_was_granted():
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["write", "send"])

    finish_flow(env, flow, OWNER, granted=[GMAIL_COMPOSE])

    consented = env.emitted[0]
    assert consented["type"] == "connection.consented"
    assert consented["data"]["scopes"] == [action_description(gmail_decl(), "write")]


def test_FR_CON_03_granted_scopes_are_exactly_what_the_token_response_lists():
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["send"])

    # Google answers with a scope the request never named; the response is the record.
    result = finish_flow(env, flow, OWNER, granted=[GMAIL_SEND, GMAIL_READONLY])

    assert result.granted_scopes == frozenset({GMAIL_SEND, GMAIL_READONLY})
    assert env.broker.granted_scopes(OWNER, "gmail") == frozenset({GMAIL_SEND, GMAIL_READONLY})


def test_FR_CON_03_an_incremental_grant_records_the_merged_scopes_google_returns():
    env = make_env()
    env.connect(OWNER, "google_drive", [DRIVE_READONLY])
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    assert flow.scopes == [DRIVE_FILE]

    # include_granted_scopes=true: Google's response lists the earlier grant as well as the new one.
    result = finish_flow(env, flow, OWNER, granted=[DRIVE_READONLY, DRIVE_FILE])

    assert result.granted_scopes == frozenset({DRIVE_READONLY, DRIVE_FILE})
    assert env.broker.granted_scopes(OWNER, "google_drive") == frozenset({DRIVE_READONLY, DRIVE_FILE})


# ---- Acceptance: incremental, only when needed ------------------------------------------------


def test_FR_CON_03_a_task_needing_drive_write_asks_for_that_scope_only_and_only_once():
    env = make_env()
    # The user connected Gmail earlier, for reading.
    gmail_flow = start_flow(env, OWNER, "gmail", ["read"])
    finish_flow(env, gmail_flow, OWNER)
    gmail_token = env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])
    env.emitted.clear()

    # Later a task needs to save a report to Drive: the card and the URL ask for write, nothing else.
    card = env.service.build_consent_card(
        user_id=OWNER,
        connector="google_drive",
        capabilities=["write"],
        card_id=CARD_ID,
        world_id="w_village_basic",
        run_id="r_village_basic_1",
        building="B1",
        agent="A_dir",
        what_happened="Saving the report needs access to one Drive folder.",
        why_it_matters="Without it the report stays in Tilo only.",
    )
    assert card["consent"]["scopes"] == [action_description(drive_decl(), "write")]
    drive_flow = start_flow(env, OWNER, "google_drive", ["write"])
    assert drive_flow.scopes == [DRIVE_FILE]
    finish_flow(env, drive_flow, OWNER)

    # Once granted it is not asked for again, and Gmail is untouched.
    assert env.service.scopes_needed(user_id=OWNER, connector="google_drive", capabilities=["write"]) == []
    assert (
        env.service.build_consent_card(
            user_id=OWNER,
            connector="google_drive",
            capabilities=["write"],
            card_id=CARD_ID,
            world_id="w_village_basic",
            run_id="r_village_basic_1",
            building="B1",
            agent="A_dir",
            what_happened="Saving the report needs access to one Drive folder.",
            why_it_matters="Without it the report stays in Tilo only.",
        )
        is None
    )
    assert env.broker.granted_scopes(OWNER, "gmail") == frozenset({GMAIL_READONLY})
    assert env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY]) == gmail_token


# ---- The state: wrong, forged, reused, expired, someone else's --------------------------------


def test_FR_CON_03_a_callback_with_an_unknown_state_is_refused():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    env.google.calls.clear()

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER, state="not-a-state-this-service-minted-0123456789")

    assert_nothing_happened(env)


def test_FR_CON_03_a_forged_state_is_refused():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER, state=flip(flow.state))

    assert_nothing_happened(env)


def test_FR_CON_03_a_reused_state_is_refused_and_changes_nothing():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    finish_flow(env, flow, OWNER)
    token = env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE])
    events = len(env.emitted)

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER)

    assert len(env.google.exchange_calls()) == 1, "the replay never reaches Google"
    assert len(env.emitted) == events
    assert env.broker.access_token_for_adapter(OWNER, "google_drive", required_scopes=[DRIVE_FILE]) == token


def test_FR_CON_03_a_state_is_refused_for_a_different_signed_in_user():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OTHER)

    assert_nothing_happened(env)


def test_FR_CON_03_a_state_is_good_for_its_lifetime_and_not_a_second_longer():
    env = make_env(state_ttl_s=600)
    inside = start_flow(env, OWNER, "google_drive", ["write"])
    outside = start_flow(env, OWNER, "gmail", ["send"])
    env.clock.advance(599)

    finish_flow(env, inside, OWNER)  # 599 s: accepted

    env.clock.advance(2)  # 601 s since `outside` was minted
    with pytest.raises(ConsentRefused):
        finish_flow(env, outside, OWNER)
    assert env.broker.connection_state(OWNER, "gmail") is None
    assert len(env.google.exchange_calls()) == 1


def test_FR_CON_03_the_default_lifetime_is_short():
    env = make_env()
    soon = start_flow(env, OWNER, "google_drive", ["write"])
    late = start_flow(env, OWNER, "gmail", ["send"])
    env.clock.advance(60)
    finish_flow(env, soon, OWNER)

    env.clock.advance(3600)
    with pytest.raises(ConsentRefused):
        finish_flow(env, late, OWNER)


def test_FR_CON_03_the_state_binds_the_connection_so_each_callback_lands_on_its_own_connector():
    env = make_env()
    drive = start_flow(env, OWNER, "google_drive", ["write"])
    gmail = start_flow(env, OWNER, "gmail", ["send"])

    gmail_result = finish_flow(env, gmail, OWNER)
    drive_result = finish_flow(env, drive, OWNER)

    assert gmail_result.connector == "gmail" and drive_result.connector == "google_drive"
    assert env.broker.granted_scopes(OWNER, "gmail") == frozenset({GMAIL_SEND})
    assert env.broker.granted_scopes(OWNER, "google_drive") == frozenset({DRIVE_FILE})


def test_FR_CON_03_two_callbacks_racing_on_one_state_connect_once():
    env = make_env(latency_s=0.05)
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    codes = [
        env.google.issue_code(
            flow.scopes, challenge=flow.query["code_challenge"], redirect_uri=flow.query["redirect_uri"]
        )
        for _ in range(8)
    ]
    barrier = threading.Barrier(len(codes))
    outcomes: list[str] = []

    def callback(code):
        barrier.wait()
        try:
            env.service.handle_callback(user_id=OWNER, state=flow.state, code=code)
            outcomes.append("ok")
        except ConsentRefused:
            outcomes.append("refused")

    threads = [threading.Thread(target=callback, args=(c,)) for c in codes]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert sorted(outcomes) == ["ok"] + ["refused"] * (len(codes) - 1)
    assert len(env.google.exchange_calls()) == 1
    assert types_of(env.emitted) == ["connection.consented", "connection.established"]


@settings(max_examples=25, deadline=None)
@given(replays=st.integers(min_value=2, max_value=6))
def test_FR_CON_03_property_a_state_succeeds_exactly_once_however_often_it_is_replayed(replays):
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    successes = 0

    for _ in range(replays):
        try:
            finish_flow(env, flow, OWNER)
            successes += 1
        except ConsentRefused:
            pass

    assert successes == 1
    assert len(env.google.exchange_calls()) == 1


# ---- Callbacks that carry no grant ------------------------------------------------------------


def test_FR_CON_03_a_denied_consent_stores_nothing_and_spends_the_state():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    with pytest.raises(ConsentRefused):
        env.service.handle_callback(user_id=OWNER, state=flow.state, error="access_denied")

    assert_nothing_happened(env)
    with pytest.raises(ConsentRefused):  # the same state cannot be used afterwards
        finish_flow(env, flow, OWNER)
    assert_nothing_happened(env)


def test_FR_CON_03_a_callback_with_neither_a_code_nor_an_error_is_refused():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    with pytest.raises(ConsentRefused):
        env.service.handle_callback(user_id=OWNER, state=flow.state)

    assert_nothing_happened(env)


def test_FR_CON_03_a_code_google_rejects_connects_nothing_and_leaks_nothing(caplog):
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    caplog.set_level(logging.DEBUG)
    bad_code = "bad-code-" + "0123456789abcdef"

    with pytest.raises(ConsentRefused) as raised:
        env.service.handle_callback(user_id=OWNER, state=flow.state, code=bad_code)

    assert env.store.live_keys() == []
    assert env.emitted == []
    verifier = env.google.exchange_calls()[0]["code_verifier"]
    seen = f"{raised.value!s} {raised.value!r} " + "\n".join(r.getMessage() for r in caplog.records)
    assert leaks(seen, [bad_code, verifier, env.secrets["client_secret"]]) == []


def test_FR_CON_03_no_secret_reaches_events_logs_or_the_service_repr(caplog):
    env = make_env()
    caplog.set_level(logging.DEBUG)
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    finish_flow(env, flow, OWNER)
    verifier = env.google.exchange_calls()[0]["code_verifier"]
    secrets_ = [
        env.secrets["client_secret"],
        verifier,
        *env.google.issued_access,
        *env.google.live_refresh,
    ]

    blob = repr(env.emitted) + repr(env.service) + "\n".join(r.getMessage() for r in caplog.records)

    assert leaks(blob, secrets_) == []
    assert START  # the clock was injected, not read from the wall
