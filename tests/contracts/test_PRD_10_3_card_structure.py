"""PRD 10.3 "One card, every channel" (ticket P0-02 section 1 card.schema.json).

"Every request uses one card structure: header ..., what happened (<= 140
characters), why it matters, 2-3 options with one marked 'Suggested' and a
reason, an add-context field, and Show me / Snooze / Delegate to Director
[actions] ... Every card has a timeout and a safe default ... Gates default
to `hold` and never time out to 'go'."

All cases mutate existing valid fixtures rather than hand-building a card, so
they do not depend on guessing field names the ticket does not give exactly
(e.g. the header sub-fields).
"""

from __future__ import annotations

import copy

import pytest
from _lib import errors_for, list_fixtures, load_json, load_schema


def _any_valid_card(repo_root):
    fixtures = list_fixtures(repo_root, "card", "valid")
    assert fixtures, "PRD 10.3: need at least one contracts/fixtures/card/valid/*.json to mutate"
    return load_json(fixtures[0]), fixtures[0]


def _valid_gate_card(repo_root):
    for path in list_fixtures(repo_root, "card", "valid"):
        instance = load_json(path)
        if instance.get("kind") == "gate":
            return instance, path
    return None, None


@pytest.fixture()
def a_valid_card(repo_root):
    instance, _ = _any_valid_card(repo_root)
    assert "options" in instance and isinstance(instance["options"], list), (
        "PRD 10.3: a valid card fixture must have an 'options' array"
    )
    return instance


@pytest.fixture()
def a_valid_gate_card(repo_root):
    instance, path = _valid_gate_card(repo_root)
    assert instance is not None, (
        'PRD 10.3: need at least one contracts/fixtures/card/valid/*.json with "kind": "gate" to '
        "check the gate-only safe_default rule"
    )
    return instance


def _card_errors(repo_root, registry, instance):
    return errors_for(load_schema(repo_root, "card"), instance, registry)


def test_PRD_10_3_card_with_one_option_is_invalid(repo_root, registry, a_valid_card):
    mutated = copy.deepcopy(a_valid_card)
    mutated["options"] = mutated["options"][:1]
    assert _card_errors(repo_root, registry, mutated), "PRD 10.3: a card with 1 option must be invalid (2-3 required)"


def test_PRD_10_3_card_with_four_options_is_invalid(repo_root, registry, a_valid_card):
    mutated = copy.deepcopy(a_valid_card)
    options = mutated["options"]
    while len(options) < 4:
        clone = copy.deepcopy(options[len(options) % len(a_valid_card["options"])])
        clone["suggested"] = False
        options.append(clone)
    assert _card_errors(repo_root, registry, mutated), "PRD 10.3: a card with 4 options must be invalid (2-3 required)"


def test_PRD_10_3_card_with_no_suggested_option_is_invalid(repo_root, registry, a_valid_card):
    mutated = copy.deepcopy(a_valid_card)
    for option in mutated["options"]:
        option["suggested"] = False
    assert _card_errors(repo_root, registry, mutated), (
        "PRD 10.3: a card with zero options marked suggested must be invalid (exactly one required)"
    )


def test_PRD_10_3_card_with_two_suggested_options_is_invalid(repo_root, registry, a_valid_card):
    mutated = copy.deepcopy(a_valid_card)
    for option in mutated["options"]:
        option["suggested"] = True
    assert _card_errors(repo_root, registry, mutated), (
        "PRD 10.3: a card with more than one option marked suggested must be invalid (exactly one required)"
    )


def test_PRD_10_3_card_missing_timeout_is_invalid(repo_root, registry, a_valid_card):
    assert "timeout" in a_valid_card, "PRD 10.3: valid card fixture must include 'timeout' to mutate"
    mutated = copy.deepcopy(a_valid_card)
    del mutated["timeout"]
    assert _card_errors(repo_root, registry, mutated), "PRD 10.3: every card must have a timeout"


def test_PRD_10_3_card_missing_safe_default_is_invalid(repo_root, registry, a_valid_card):
    assert "safe_default" in a_valid_card, "PRD 10.3: valid card fixture must include 'safe_default' to mutate"
    mutated = copy.deepcopy(a_valid_card)
    del mutated["safe_default"]
    assert _card_errors(repo_root, registry, mutated), "PRD 10.3: every card must have a safe default"


def test_PRD_10_3_gate_card_safe_default_must_be_hold(repo_root, registry, a_valid_gate_card):
    assert a_valid_gate_card.get("safe_default") == "hold", (
        'PRD 10.3: the valid gate-card fixture must itself have "safe_default": "hold"'
    )
    mutated = copy.deepcopy(a_valid_gate_card)
    mutated["safe_default"] = "go"
    assert _card_errors(repo_root, registry, mutated), (
        "PRD 10.3: \"Gates default to `hold` and never time out to 'go'\" -- a gate card with "
        "safe_default other than hold must be invalid"
    )
