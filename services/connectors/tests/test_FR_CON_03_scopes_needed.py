"""FR-CON-03 (PRD 12.1 "Scopes: least-privilege scopes per capability, requested only when a task needs
them", 16.1 rule 2 "incremental scopes"): the scopes to ask for are the declared scopes of the
capabilities the task needs, minus what the user already granted, and nothing else.

Acceptance: a task needing Drive write asks only for that scope, when needed.

ConsentService.scopes_needed(user_id=, connector=, capabilities=) -> list[str] reads the connector
declaration (contracts/connector.schema.json, `scopes` per capability) and the broker's recorded
grants. Ordering: capability order given, then declaration order, each scope once.
"""

from __future__ import annotations

import pytest
from _oauth_lib import (
    DRIVE_FILE,
    DRIVE_METADATA,
    DRIVE_READONLY,
    GMAIL_COMPOSE,
    GMAIL_READONLY,
    GMAIL_SEND,
    OTHER,
    OWNER,
    drive_decl,
    make_env,
    schema_errors,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_connectors.consent import ConsentRefused


def needed(env, connector, capabilities, user=OWNER):
    return env.service.scopes_needed(user_id=user, connector=connector, capabilities=capabilities)


def test_FR_CON_03_the_test_declarations_are_valid_connector_declarations():
    assert schema_errors("connector.schema.json", drive_decl()) == []


def test_FR_CON_03_a_task_needing_drive_write_asks_only_for_that_scope():
    env = make_env()

    assert needed(env, "google_drive", ["write"]) == [DRIVE_FILE]


def test_FR_CON_03_scopes_already_granted_are_not_asked_for_again():
    env = make_env()
    env.connect(OWNER, "google_drive", [DRIVE_READONLY])

    assert needed(env, "google_drive", ["write"]) == [DRIVE_FILE]
    assert needed(env, "google_drive", ["read", "write"]) == [DRIVE_FILE], "read is already granted"
    assert needed(env, "google_drive", ["read"]) == []


def test_FR_CON_03_nothing_is_asked_when_everything_needed_is_granted():
    env = make_env()
    env.connect(OWNER, "google_drive", [DRIVE_READONLY, DRIVE_FILE])

    assert needed(env, "google_drive", ["read", "write"]) == []


def test_FR_CON_03_only_the_capabilities_the_task_needs_are_asked_for():
    env = make_env()

    assert needed(env, "google_drive", ["read"]) == [DRIVE_READONLY]
    assert needed(env, "google_drive", ["list"]) == [DRIVE_METADATA]
    assert needed(env, "google_drive", ["read", "list", "write"]) == [DRIVE_READONLY, DRIVE_METADATA, DRIVE_FILE]


def test_FR_CON_03_gmail_send_asks_for_send_alone_not_compose_or_read():
    env = make_env()

    assert needed(env, "gmail", ["send"]) == [GMAIL_SEND]
    assert needed(env, "gmail", ["write"]) == [GMAIL_COMPOSE]


def test_FR_CON_03_two_capabilities_sharing_one_scope_ask_for_it_once():
    env = make_env()

    assert needed(env, "gmail", ["read", "search"]) == [GMAIL_READONLY]


def test_FR_CON_03_grants_are_per_user_and_per_connector():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY, DRIVE_FILE])  # an odd record, but only gmail's own count

    assert needed(env, "google_drive", ["write"], user=OWNER) == [DRIVE_FILE], "another connector's grant"
    assert needed(env, "gmail", ["read"], user=OTHER) == [GMAIL_READONLY], "another user's grant"
    assert needed(env, "gmail", ["read"], user=OWNER) == []


def test_FR_CON_03_asking_what_is_needed_does_nothing_else():
    env = make_env()

    needed(env, "google_drive", ["write"])

    assert env.google.calls == []
    assert env.emitted == []
    assert env.store.live_keys() == []


@pytest.mark.parametrize(
    ("connector", "capabilities"),
    [
        ("gmail", ["delete"]),  # a capability the connector does not declare
        ("google_drive", ["send"]),
        ("google_drive", ["write", "nonsense"]),
        ("not_a_connector", ["read"]),
        ("web_search", ["search"]),  # a platform connector has no user consent
    ],
)
def test_FR_CON_03_a_scope_the_connector_does_not_declare_is_never_requested(connector, capabilities):
    env = make_env()

    with pytest.raises(ConsentRefused):
        needed(env, connector, capabilities)


# ---- Property: least privilege ----------------------------------------------------------------

DRIVE_CAPS = {"read": DRIVE_READONLY, "list": DRIVE_METADATA, "write": DRIVE_FILE}


@settings(max_examples=60, deadline=None)
@given(
    caps=st.lists(st.sampled_from(sorted(DRIVE_CAPS)), min_size=1, max_size=3, unique=True),
    granted=st.lists(st.sampled_from(sorted(DRIVE_CAPS.values())), max_size=3, unique=True),
)
def test_FR_CON_03_property_the_ask_is_exactly_the_declared_scopes_not_yet_granted(caps, granted):
    env = make_env()
    if granted:
        env.connect(OWNER, "google_drive", list(granted))

    asked = needed(env, "google_drive", caps)

    declared = {DRIVE_CAPS[c] for c in caps}
    assert len(asked) == len(set(asked)), "each scope once"
    assert set(asked) == declared - set(granted)
    assert set(asked) <= declared, "never a scope the task did not need"
    assert set(asked).isdisjoint(granted), "never a scope already granted"
