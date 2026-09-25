"""PRD 10.3 + ticket P0-03 section 6: "Consent cards: give consent-card options a closed id set
and label-by-id like gate cards (security note from P0-02 round 5); update card.rules.md and
fixtures."

`.claude/agent-memory/architect/contract-pitfalls.md` (security review round 5, P0-02): "the
person taps the *label* (WhatsApp shows only labels), so an authorising option needs its label
fixed by id too" -- the same reasoning CR-07 already applies to gate cards' `approve`/`edit`/
`hold`. There is no CR-13 in `contracts/card.rules.md` yet; this file provisionally uses that
number (see `_events_lib`'s docstring for the exact closed set and labels chosen as the default:
`{"connect": "Connect", "hold": "Hold"}`, keeping the `connect` id the shipped
`consent_drive_folder.json` fixture already uses and mirroring gate's `hold` label exactly).

`card.schema.json` as merged for P0-02 has no such constraint (CR-07 is gate-only), so every test
here is expected to fail until the schema is extended -- that is the point: it proves the gap
security review round 5 flagged is still open for consent cards specifically.
"""

from __future__ import annotations

import copy

import pytest
from _lib import errors_for, list_fixtures, load_json, load_schema


@pytest.fixture()
def a_consent_card(repo_root):
    for path in list_fixtures(repo_root, "card", "valid"):
        card = load_json(path)
        if card.get("kind") == "consent":
            return card
    pytest.fail("PRD 10.3: need at least one contracts/fixtures/card/valid/*.json with kind=consent to mutate")


def test_PRD_10_3_CR13_consent_option_id_outside_closed_set_is_invalid(repo_root, registry, a_consent_card):
    card = copy.deepcopy(a_consent_card)
    grant_option = next(o for o in card["options"] if o["id"] != "hold")
    grant_option["id"] = "approve"  # a gate id, not a consent id -- must not leak across kinds
    errors = errors_for(load_schema(repo_root, "card"), card, registry)
    assert errors, (
        "CR-13: a consent option id outside the closed set {'connect', 'hold'} must be invalid, "
        "like CR-07 already does for gates"
    )


@pytest.mark.parametrize(
    ("option_id", "label"),
    [("connect", "Allow access"), ("connect", "Grant Drive access"), ("hold", "Not now"), ("hold", "Later")],
)
def test_PRD_10_3_CR13_consent_option_label_is_fixed_by_id(repo_root, registry, a_consent_card, option_id, label):
    card = copy.deepcopy(a_consent_card)
    target = next(o for o in card["options"] if o["id"] == option_id)
    target["label"] = label
    errors = errors_for(load_schema(repo_root, "card"), card, registry)
    assert errors, (
        f"CR-13: a consent {option_id!r} option labelled {label!r} must be invalid -- the person taps the "
        "label, so it must be fixed by id (connect: 'Connect', hold: 'Hold'), not written per-connector"
    )


def test_PRD_10_3_CR13_consent_hold_option_repeated_is_invalid(repo_root, registry, a_consent_card):
    """Mirrors gate's CR-07 maxContains:1 per id: a repeated 'hold' id must be rejected the same
    way a repeated 'approve' already is on gate cards, not left schema-valid the way a non-gate
    card's repeated option id is today (card.rules.md CR-02, validator-only). The duplicate
    keeps everything else about the card intact -- 3 options, exactly one suggested -- so the
    only thing that can make this invalid is the repeated closed-set id."""
    card = copy.deepcopy(a_consent_card)
    hold_option = next(o for o in card["options"] if o["id"] == "hold")
    other_option = next(o for o in card["options"] if o["id"] != "hold")
    card["options"] = [other_option, hold_option, copy.deepcopy(hold_option)]
    errors = errors_for(load_schema(repo_root, "card"), card, registry)
    assert errors, "CR-13: a consent card with the 'hold' option repeated must be invalid, like gate's CR-07"
