"""FR-MTG-09 (token broker): the host account is a second Google account, so its grant lives in its own group, and
a consent answer that is not the bot's account alone is refused (MH-C1). API_FR_MTG_09.md "Token broker: a second
Google account"; ADR-0024 decision 5; BQ-MTG09-10, BQ-MTG09-11; CON-D10 (never revoke while a sibling of the same
Google grant is connected) stays as it is inside one group.

The broker keys grants by (user_id, connector) and, before this ticket, treated every connector of one user as one
Google grant. Tests that need `GRANT_GROUPS`, group-aware revokes or MH-C1 fail today; the ones that pin
unchanged behaviour (one group, secrecy) pass today.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping

import pytest
from _meeting_host_lib import (
    CALENDAR_EVENTS_OWNED,
    CALENDAR_READONLY,
    CONNECTOR_ID,
    DRIVE_FILE,
    GMAIL_READONLY,
    OWNER,
    make_host_env,
    no_network_and_no_live,  # noqa: F401 - autouse guard
    shipped_decl,
)
from _oauth_lib import (
    CARD_ID,
    RUN,
    WORLD,
    check_consent_card_rules,
    finish_flow,
    leaks,
    make_env,
    schema_errors,
    start_flow,
)

NOT_THE_BOT = "this is not the meeting bot account: sign in with the bot's account"


def env_with_host_service():
    """The broker and a consent service that knows `meeting_host` (the pinned declaration), nothing connected."""
    return make_host_env(connect_host=False).env


def tokens_module():
    import importlib

    return importlib.import_module("tilo_connectors.tokens")


# ---------------------------------------------------------------------------
# The group table


def test_FR_MTG_09_GRANT_GROUPS_maps_only_meeting_host_to_its_own_group_and_every_other_connector_to_person():
    tokens = tokens_module()

    assert isinstance(tokens.GRANT_GROUPS, Mapping)
    assert dict(tokens.GRANT_GROUPS) == {"meeting_host": "meeting_host"}
    assert tokens.grant_group("meeting_host") == "meeting_host"
    for connector in ("gmail", "google_drive", "google_calendar", "lovable", "web_search", "anything_else", ""):
        assert tokens.grant_group(connector) == "person", connector


def test_FR_MTG_09_has_live_grant_counts_only_the_connectors_of_one_group():
    env = make_env()
    assert env.broker.has_live_grant(OWNER) is False

    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    assert env.broker.has_live_grant(OWNER) is True, "a person's grant"
    assert env.broker.has_live_grant(OWNER, excluding="meeting_host") is False, "the host group is empty"
    assert env.broker.has_live_grant(OWNER, excluding="gmail") is False, "nothing else of the person group"


def test_FR_MTG_09_has_live_grant_a_host_grant_alone_is_not_a_person_grant():
    env = make_env()
    env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])

    assert env.broker.has_live_grant(OWNER) is False
    assert env.broker.has_live_grant(OWNER, excluding="gmail") is False
    assert env.broker.has_live_grant(OWNER, excluding=CONNECTOR_ID) is False


def test_FR_MTG_09_has_live_grant_both_groups_connected_each_counts_only_its_own():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.connect(OWNER, "google_calendar", [CALENDAR_READONLY])
    env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])

    assert env.broker.has_live_grant(OWNER) is True
    assert env.broker.has_live_grant(OWNER, excluding="gmail") is True, "google_calendar shares the person grant"
    assert env.broker.has_live_grant(OWNER, excluding=CONNECTOR_ID) is False, "no other host connector"
    assert env.broker.has_live_grant("u_other") is False


# ---------------------------------------------------------------------------
# Disconnect: one revoke per grant, never the other account's


def test_FR_MTG_09_disconnecting_gmail_revokes_the_gmail_grant_at_google_with_a_host_grant_connected():
    env = make_env()
    gmail = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    host = env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])

    result = env.broker.disconnect(OWNER, "gmail")

    assert result.revoked_at_provider is True
    assert len(env.google.revoke_calls()) == 1, "exactly one revoke call"
    assert env.google.revoked == [gmail["refresh_token"]]
    assert host["refresh_token"] in env.google.live_refresh, "the bot account's grant is untouched"
    assert env.broker.connection_state(OWNER, CONNECTOR_ID) == "connected"
    assert env.broker.connection_state(OWNER, "gmail") is None


def test_FR_MTG_09_disconnecting_meeting_host_revokes_only_the_host_grant_with_a_person_grant_connected():
    env = make_env()
    gmail = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    host = env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])

    result = env.broker.disconnect(OWNER, CONNECTOR_ID)

    assert result.revoked_at_provider is True
    assert len(env.google.revoke_calls()) == 1
    assert env.google.revoked == [host["refresh_token"]], "only the host grant"
    assert gmail["refresh_token"] in env.google.live_refresh
    assert env.broker.connection_state(OWNER, "gmail") == "connected"
    assert [p["type"] for p in env.parts_of("connection.revoked")] == ["connection.revoked"]
    assert env.parts_of("connection.revoked")[0]["data"] == {"connector": CONNECTOR_ID}


def test_FR_MTG_09_disconnecting_the_host_account_alone_revokes_it():
    env = make_env()
    host = env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])

    env.broker.disconnect(OWNER, CONNECTOR_ID)

    assert env.google.revoked == [host["refresh_token"]]
    assert env.store.connectors_of(OWNER) == []


def test_FR_MTG_09_CON_D10_unchanged_with_gmail_and_calendar_connected_the_first_disconnect_skips_the_revoke():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    calendar = env.connect(OWNER, "google_calendar", [CALENDAR_READONLY])

    first = env.broker.disconnect(OWNER, "gmail")

    assert first.revoked_at_provider is False and env.google.revoke_calls() == [], "a sibling is connected"
    second = env.broker.disconnect(OWNER, "google_calendar")
    assert second.revoked_at_provider is True and len(env.google.revoke_calls()) == 1
    assert env.google.revoked == [calendar["refresh_token"]], "the last of the group revokes its own token"


def test_FR_MTG_09_three_connectors_two_groups_the_person_grant_is_revoked_once_and_the_host_grant_once():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    env.connect(OWNER, "google_calendar", [CALENDAR_READONLY])
    host = env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])

    env.broker.disconnect(OWNER, "gmail")
    assert env.google.revoke_calls() == [], "google_calendar still holds the person grant"
    env.broker.disconnect(OWNER, "google_calendar")
    assert len(env.google.revoke_calls()) == 1, "the last of the person group revokes it"
    assert host["refresh_token"] in env.google.live_refresh
    env.broker.disconnect(OWNER, CONNECTOR_ID)
    assert len(env.google.revoke_calls()) == 2 and host["refresh_token"] in env.google.revoked


def test_FR_MTG_09_delete_user_still_disconnects_every_connector_of_both_groups():
    env = make_env()
    gmail = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    host = env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])

    env.broker.delete_user(OWNER)

    assert env.store.connectors_of(OWNER) == []
    assert {gmail["refresh_token"], host["refresh_token"]} <= set(env.google.revoked)
    assert env.broker.connection_state(OWNER, CONNECTOR_ID) is None


# ---------------------------------------------------------------------------
# discard_tokens uses the connector's own group


def test_FR_MTG_09_discarding_a_person_connectors_tokens_revokes_them_when_only_the_host_grant_is_live():
    env = make_env()
    env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])
    unused = env.google.token_response([GMAIL_READONLY])

    env.broker.discard_tokens(OWNER, "gmail", unused)

    assert env.google.revoked == [unused["refresh_token"]], "the host grant is not a sibling of a person grant"


def test_FR_MTG_09_discarding_host_tokens_revokes_them_when_only_a_person_grant_is_live():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    unused = env.google.token_response([CALENDAR_EVENTS_OWNED])

    env.broker.discard_tokens(OWNER, CONNECTOR_ID, unused)

    assert env.google.revoked == [unused["refresh_token"]]


def test_FR_MTG_09_discarding_host_tokens_skips_the_revoke_when_a_host_grant_is_live():
    env = make_env()
    env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])
    unused = env.google.token_response([CALENDAR_EVENTS_OWNED])

    env.broker.discard_tokens(OWNER, CONNECTOR_ID, unused)

    assert env.google.revoked == [], "same group: it would end the live host grant (CON-D10)"


def test_FR_MTG_09_discarding_a_person_connectors_tokens_still_skips_the_revoke_with_a_person_grant_live():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])
    unused = env.google.token_response([DRIVE_FILE])

    env.broker.discard_tokens(OWNER, "google_drive", unused)

    assert env.google.revoked == []


# ---------------------------------------------------------------------------
# MH-C1: a consent answer for meeting_host that holds any scope but calendar.events.owned is not the bot's account


def test_FR_MTG_09_the_host_consent_asks_for_exactly_one_scope_with_the_granted_scopes_included():
    env = env_with_host_service()

    flow = start_flow(env, OWNER, CONNECTOR_ID, ["send"])

    assert flow.scopes == [CALENDAR_EVENTS_OWNED]
    assert flow.query["include_granted_scopes"] == "true", "so Google's answer lists what the account granted before"
    assert flow.query["access_type"] == "offline" and flow.query["code_challenge_method"] == "S256"


def test_FR_MTG_09_MH_C1_a_callback_that_holds_only_calendar_events_owned_connects_the_host_account():
    env = env_with_host_service()
    flow = start_flow(env, OWNER, CONNECTOR_ID, ["send"])

    result = finish_flow(env, flow, OWNER, granted=[CALENDAR_EVENTS_OWNED])

    assert result.connector == CONNECTOR_ID and result.granted_scopes == frozenset({CALENDAR_EVENTS_OWNED})
    assert env.broker.connection_state(OWNER, CONNECTOR_ID) == "connected"
    assert [p["type"] for p in env.emitted if p["data"].get("connector") == CONNECTOR_ID][-2:] == [
        "connection.consented",
        "connection.established",
    ]


@pytest.mark.parametrize(
    "extra",
    [GMAIL_READONLY, DRIVE_FILE, CALENDAR_READONLY, "openid", "https://www.googleapis.com/auth/calendar.events"],
)
@pytest.mark.parametrize("person_grant", [False, True], ids=["no-other-grant", "gmail-connected"])
def test_FR_MTG_09_MH_C1_a_callback_with_any_other_scope_is_refused_stores_nothing_and_revokes_nothing(
    extra, person_grant
):
    from tilo_connectors.consent import ConsentRefused

    env = env_with_host_service()
    if person_grant:
        env.connect(OWNER, "gmail", [GMAIL_READONLY])
    before = env.store.connectors_of(OWNER)
    flow = start_flow(env, OWNER, CONNECTOR_ID, ["send"])
    emitted_before = len(env.emitted)

    with pytest.raises(ConsentRefused) as refused:
        finish_flow(env, flow, OWNER, granted=[CALENDAR_EVENTS_OWNED, extra])

    assert str(refused.value) == NOT_THE_BOT
    assert env.store.connectors_of(OWNER) == before, "no meeting_host record, nothing else changed"
    assert env.broker.connection_state(OWNER, CONNECTOR_ID) is None
    assert env.google.revoke_calls() == [], "a revoke would end that account's other grant (CON-D10)"
    assert not any(f"{OWNER}/{CONNECTOR_ID}:" in written for written in env.store.history), "never stored, even sealed"
    new_parts = [p["type"] for p in env.emitted[emitted_before:]]
    assert "connection.consented" not in new_parts and "connection.established" not in new_parts
    with pytest.raises(ConsentRefused):  # the state is spent: the same callback cannot be replayed
        finish_flow(env, flow, OWNER, granted=[CALENDAR_EVENTS_OWNED])


def test_FR_MTG_09_MH_C1_a_refused_answer_leaves_an_existing_person_grant_working():
    from tilo_connectors.consent import ConsentRefused

    env = env_with_host_service()
    gmail = env.connect(OWNER, "gmail", [GMAIL_READONLY])
    flow = start_flow(env, OWNER, CONNECTOR_ID, ["send"])

    with pytest.raises(ConsentRefused):
        finish_flow(env, flow, OWNER, granted=[CALENDAR_EVENTS_OWNED, GMAIL_READONLY])

    assert env.broker.connection_state(OWNER, "gmail") == "connected"
    assert gmail["refresh_token"] in env.google.live_refresh
    assert env.broker.access_token_for_adapter(OWNER, "gmail", required_scopes=[GMAIL_READONLY])


def test_FR_MTG_09_MH_C1_applies_to_meeting_host_only_a_gmail_callback_may_carry_earlier_scopes():
    env = env_with_host_service()
    flow = start_flow(env, OWNER, "gmail", ["read"])

    result = finish_flow(env, flow, OWNER, granted=[GMAIL_READONLY, DRIVE_FILE, CALENDAR_READONLY])

    assert result.connector == "gmail" and GMAIL_READONLY in result.granted_scopes
    assert env.broker.connection_state(OWNER, "gmail") == "connected"


# ---------------------------------------------------------------------------
# The consent card says who to sign in as, from the shipped declaration (CR-13)


def _service_with_shipped_decl():
    from tilo_connectors.consent import ConsentService

    env = make_env()
    service = ConsentService(
        connectors={CONNECTOR_ID: shipped_decl()},
        broker=env.broker,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
    )
    return env, service


def test_FR_MTG_09_the_send_capability_asks_for_calendar_events_owned_and_a_person_grant_does_not_count():
    env, service = _service_with_shipped_decl()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])  # a person grant is not a host grant

    assert service.scopes_needed(user_id=OWNER, connector=CONNECTOR_ID, capabilities=["send"]) == [
        CALENDAR_EVENTS_OWNED
    ]
    env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])
    assert service.scopes_needed(user_id=OWNER, connector=CONNECTOR_ID, capabilities=["send"]) == []


def test_FR_MTG_09_the_consent_card_tells_the_person_to_sign_in_as_the_bot_and_validates_unchanged():
    env, service = _service_with_shipped_decl()

    card = service.build_consent_card(
        user_id=OWNER,
        connector=CONNECTOR_ID,
        capabilities=["send"],
        card_id=CARD_ID,
        world_id=WORLD,
        run_id=RUN,
        building="B1",
        agent="A_host1",
        what_happened="Tilo needs the meeting bot's Google account to start your meeting.",
        why_it_matters="Only the account that makes the meeting can host it.",
    )

    assert card is not None and schema_errors("card.schema.json", card) == []
    assert check_consent_card_rules(card) == [], "CR-13: exactly Connect and Hold"
    assert card["consent"]["connector"] == CONNECTOR_ID
    assert card["consent"]["scopes"] == [shipped_decl()["actions"][0]["description"]]
    assert "sign in as the bot" in card["consent"]["scopes"][0].lower()
    assert "never sees your password" in card["options"][0]["reason"]
    assert [p["type"] for p in env.parts_of("connection.requested")] == ["connection.requested"]


# ---------------------------------------------------------------------------
# Tokens: nothing of the host grant in a part, a log or an exception (the broker's tests extended to meeting_host)


def test_FR_MTG_09_no_host_token_or_client_secret_in_any_part_log_store_text_or_error(caplog):
    caplog.set_level(logging.DEBUG)
    env = env_with_host_service()
    flow = start_flow(env, OWNER, CONNECTOR_ID, ["send"])
    finish_flow(env, flow, OWNER, granted=[CALENDAR_EVENTS_OWNED])
    first = env.broker.access_token_for_adapter(OWNER, CONNECTOR_ID, required_scopes=[CALENDAR_EVENTS_OWNED])
    env.clock.advance(7200)  # the access token ran out: a refresh
    second = env.broker.access_token_for_adapter(OWNER, CONNECTOR_ID, required_scopes=[CALENDAR_EVENTS_OWNED])
    errors = []
    try:
        env.broker.access_token_for_adapter(OWNER, CONNECTOR_ID, required_scopes=[GMAIL_READONLY])
    except Exception as exc:  # noqa: BLE001 - the text is what is scanned
        errors.append(repr(exc) + str(exc))
    env.broker.disconnect(OWNER, CONNECTOR_ID)

    secrets_ = [first, second, *env.google.issued_access, *env.google.revoked, env.secrets["client_secret"]]
    blob = "\n".join(
        [
            json.dumps(env.emitted, default=str),
            "\n".join(r.getMessage() + repr(r.args) for r in caplog.records),
            env.store.ever_text(),
            *errors,
        ]
    )
    assert first != second
    assert leaks(blob, secrets_) == []
