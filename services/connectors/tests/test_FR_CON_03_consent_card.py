"""FR-CON-03 (PRD 10.2 "Connection consent", 10.3, 12.1 "The consent sheet lists every scope in plain
words", contracts/card.rules.md CR-01 to CR-06 and CR-13): the consent card lists only the scopes
not yet granted, each as one plain-language line taken from the connector declaration; its options
are the fixed Connect and Hold; building it grants nothing.

PRD and contract gap, resolved: connector.schema.json has no per-scope wording, only a description
per action. Default chosen (and listed in the report as "needs contract change" if a per-scope line
is wanted): the line for a scope is the `description` of the declared action of the capability that
needs it, so the wording is the connector's own and never a model's. A scope needed by two
capabilities shows one line.

ConsentService.build_consent_card(...) -> dict | None. None when nothing is needed ("only when
needed"). The deterministic builder writes the options, safe default, channels and actions; the
caller (the Director's card path) supplies the ids, the header and the two plain sentences.
"""

from __future__ import annotations

from _oauth_lib import (
    CARD_ID,
    DRIVE_FILE,
    DRIVE_READONLY,
    GMAIL_READONLY,
    OWNER,
    RUN,
    START,
    WORLD,
    action_description,
    check_consent_card_rules,
    drive_decl,
    gmail_decl,
    make_env,
    schema_errors,
    types_of,
    validate_part,
)

WHAT = "Saving the report needs access to one Drive folder."
WHY = "Without it the report stays in Tilo only."


def build(env, connector="google_drive", capabilities=("write",), **overrides):
    kwargs = {
        "user_id": OWNER,
        "connector": connector,
        "capabilities": list(capabilities),
        "card_id": CARD_ID,
        "world_id": WORLD,
        "run_id": RUN,
        "building": "B1",
        "agent": "A_dir",
        "what_happened": WHAT,
        "why_it_matters": WHY,
    }
    kwargs.update(overrides)
    return env.service.build_consent_card(**kwargs)


def option(card, option_id):
    return next(o for o in card["options"] if o["id"] == option_id)


def test_FR_CON_03_the_consent_card_is_valid_against_the_card_schema_and_rules():
    card = build(make_env())

    assert schema_errors("card.schema.json", card) == []
    assert check_consent_card_rules(card) == []
    assert card["kind"] == "consent" and card["rung"] == "consent"
    assert card["gate"] is None
    assert card["consent"]["connector"] == "google_drive"


def test_FR_CON_03_option_labels_are_fixed_by_id():
    card = build(make_env())

    assert sorted(o["id"] for o in card["options"]) == ["connect", "hold"]
    assert option(card, "connect")["label"] == "Connect"
    assert option(card, "hold")["label"] == "Hold"
    assert all(o["irreversible"] is False for o in card["options"])


def test_FR_CON_03_the_card_times_out_to_hold_and_is_never_delegated():
    card = build(make_env())

    assert card["safe_default"] == "hold", "a timeout never grants (CR-04)"
    assert "delegate" not in card["actions"], "a model never authorises a grant (CR-06)"
    assert set(card["answer_channels"]) <= {"web", "mobile_web"}, "consent needs the web (PRD 10.2)"
    assert isinstance(card["timeout"], int) and card["timeout"] >= 1


def test_FR_CON_03_the_card_carries_the_given_ids_header_and_sentences_unchanged():
    env = make_env()
    card = build(env, timeout=1800)

    assert card["id"] == CARD_ID
    assert card["world_id"] == WORLD and card["run_id"] == RUN
    assert card["header"] == {"building": "B1", "agent": "A_dir"}
    assert card["what_happened"] == WHAT and card["why_it_matters"] == WHY
    assert card["timeout"] == 1800
    assert card["created_at"] == START, "stamped from the injected clock"


def test_FR_CON_03_a_task_needing_drive_write_shows_one_plain_line_for_that_scope_only():
    env = make_env()
    env.connect(OWNER, "google_drive", [DRIVE_READONLY])  # read is already granted

    card = build(env, capabilities=("read", "write"))

    lines = card["consent"]["scopes"]
    assert lines == [action_description(drive_decl(), "write")]
    assert action_description(drive_decl(), "read") not in lines, "what is already granted is not listed"


def test_FR_CON_03_every_line_is_the_connectors_own_words_not_a_scope_url():
    env = make_env()

    card = build(env, capabilities=("read", "list", "write"))

    decl = drive_decl()
    assert card["consent"]["scopes"] == [action_description(decl, c) for c in ("read", "list", "write")]
    for line in card["consent"]["scopes"]:
        assert "http" not in line and "googleapis" not in line


def test_FR_CON_03_gmail_lines_come_from_the_gmail_declaration():
    env = make_env()

    card = build(env, connector="gmail", capabilities=("send",))

    assert card["consent"]["scopes"] == [action_description(gmail_decl(), "send")]


def test_FR_CON_03_two_capabilities_sharing_a_scope_show_one_line():
    env = make_env()

    card = build(env, connector="gmail", capabilities=("read", "search"))

    assert len(card["consent"]["scopes"]) == 1
    assert "http" not in card["consent"]["scopes"][0]
    assert schema_errors("card.schema.json", card) == []


def test_FR_CON_03_no_card_when_everything_needed_is_already_granted():
    env = make_env()
    env.connect(OWNER, "google_drive", [DRIVE_FILE])

    assert build(env) is None


def test_FR_CON_03_the_card_lists_as_many_lines_as_scopes_needed():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY])

    needed = env.service.scopes_needed(user_id=OWNER, connector="gmail", capabilities=["read", "send", "write"])
    card = build(env, connector="gmail", capabilities=("read", "send", "write"))

    assert len(card["consent"]["scopes"]) == len(needed) == 2
    assert len(set(card["consent"]["scopes"])) == 2


def test_FR_CON_03_building_a_card_grants_nothing():
    env = make_env()

    build(env)

    assert env.google.calls == [], "no provider call"
    assert env.store.live_keys() == [], "no token stored"
    assert not {"connection.consented", "connection.established"} & set(types_of(env.emitted)), (
        "only the person's Connect can grant (CR-13)"
    )
    for part in env.emitted:  # connection.requested, if the builder emits it, is the one allowed event
        assert part["type"] == "connection.requested"
        validate_part(part)
        assert part["data"] == {"connector": "google_drive", "card_id": CARD_ID}


def test_FR_CON_03_the_card_never_contains_the_client_secret_or_a_url():
    env = make_env()

    card = build(env, capabilities=("read", "list", "write"))

    text = repr(card)
    assert env.secrets["client_secret"] not in text
    assert "http" not in text
