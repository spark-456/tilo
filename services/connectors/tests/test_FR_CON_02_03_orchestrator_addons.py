"""FR-CON-02 and FR-CON-03, orchestrator add-ons (CL-REACH handoff 2026-10-02): the consent sheet's
access line (PRD 18.4), a failed provider revoke that still deletes locally but raises the registered
alert.raised and keeps an encrypted retry, and the user_id seam on every connection event.

Written after the pinned tests; they never edit them. Tokens and secrets are runtime fakes.
"""

from __future__ import annotations

from _oauth_lib import (
    CARD_ID,
    GMAIL_READONLY,
    OWNER,
    REVOKE_URL,
    RUN,
    WORLD,
    finish_flow,
    graph_contains,
    leaks,
    make_env,
    schema_errors,
    start_flow,
    validate_part,
)
from tilo_connectors.tokens import InMemoryTokenStore, TokenBroker

ACCESS_LINE = "You sign in with Google; Tilo never sees your password."


def broker_with_alerts(env, alerts, retry_store=None):
    return TokenBroker(
        store=env.store,
        kms=env.kms,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
        alert=alerts.append,
        retry_store=retry_store,
    )


def test_FR_CON_03_the_consent_sheet_carries_the_access_line():
    env = make_env()

    card = env.service.build_consent_card(
        user_id=OWNER,
        connector="gmail",
        capabilities=["read"],
        card_id=CARD_ID,
        world_id=WORLD,
        run_id=RUN,
        building="B1",
        agent="A_dir",
        what_happened="Sorting replies needs to read your Gmail.",
        why_it_matters="Without it Tilo cannot triage your inbox.",
    )

    connect = next(o for o in card["options"] if o["id"] == "connect")
    assert ACCESS_LINE in connect["reason"], "the password rule, in the words of PRD 18.4"
    assert "Gmail" in connect["reason"], "who gets access to what"
    assert schema_errors("card.schema.json", card) == []


def test_FR_CON_02_a_failed_revoke_deletes_locally_raises_alert_raised_and_keeps_an_encrypted_retry():
    env = make_env()
    alerts: list[dict] = []
    retry_store = InMemoryTokenStore()
    broker = broker_with_alerts(env, alerts, retry_store)
    response = env.google.token_response([GMAIL_READONLY])
    broker.store_tokens(OWNER, "gmail", response)
    env.google.revoke_mode = "unavailable"

    result = broker.disconnect(OWNER, "gmail")

    assert result.revoked_at_provider is False
    assert env.store.live_keys() == []
    assert len(alerts) == 1
    validate_part(alerts[0])
    assert alerts[0]["type"] == "alert.raised" and alerts[0]["user_id"] == OWNER
    assert alerts[0]["data"]["card_id"] is None
    pending = retry_store.get(OWNER, "gmail")
    assert pending is not None, "a retry is kept"
    blob = repr(alerts) + repr(pending)
    assert leaks(blob, [response["access_token"], response["refresh_token"]]) == []
    skip = (env.store, env.kms, env.google, env.emitted, env.clock, env.settings, retry_store)
    assert not graph_contains(broker, [response["access_token"], response["refresh_token"]], skip=skip)

    env.google.revoke_mode = "ok"
    assert broker.retry_pending_revokes(OWNER) == 1
    assert response["refresh_token"] in env.google.revoked
    assert retry_store.connectors_of(OWNER) == []
    assert broker.retry_pending_revokes(OWNER) == 0, "nothing left to retry"


def test_FR_CON_02_a_retry_that_fails_again_keeps_the_pending_revoke():
    env = make_env()
    retry_store = InMemoryTokenStore()
    broker = broker_with_alerts(env, [], retry_store)
    broker.store_tokens(OWNER, "gmail", env.google.token_response([GMAIL_READONLY]))
    env.google.revoke_mode = "network"
    broker.disconnect(OWNER, "gmail")
    calls = len(env.google.calls_to(REVOKE_URL))

    assert broker.retry_pending_revokes(OWNER) == 0

    assert len(env.google.calls_to(REVOKE_URL)) == calls + 1
    assert retry_store.connectors_of(OWNER) == ["gmail"]


def test_FR_CON_02_every_connection_part_names_its_owner_and_never_a_world_or_an_actor():
    env = make_env()
    flow = start_flow(env, OWNER, "gmail", ["read"])
    finish_flow(env, flow, OWNER)
    env.broker.disconnect(OWNER, "gmail")

    assert env.emitted, "the flow emitted parts"
    for part in env.emitted:
        assert set(part) == {"type", "authz", "data", "user_id"}, "no world_id, no actor: the caller picks them"
        assert part["user_id"] == OWNER
