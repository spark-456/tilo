"""PRD 10.3 and 10.4: what a person reads on a gate card is what the gate does.

CR-07 (schema): a gate's options have fixed labels by id (approve "Approve", edit "Edit first",
hold "Hold"), because the person taps the label and that tap is the authorisation.

CR-09 to CR-12 (card validator, P1): a gate card's gate id, action type, connector, irreversible
flag, risk tier, recipients, pinned item (artifact id and version) and destination match the plan
gate, the connector action and the held side effect. `mismatches` below is the reference check;
each file in contracts/fixtures/card/crossref/ is shape-valid, and each invalid one breaks
exactly the rule its `rule` field and name state. The P1 card validator's tests must run the
same files.
"""

from __future__ import annotations

import copy

import pytest
from _lib import contracts_dir, errors_for, list_fixtures, load_json, load_schema

BASE = "https://contracts.tilo.example/"
CROSSREF_RULES = ("CR-09", "CR-10", "CR-11", "CR-12")
CASE_KEYS = {"rule", "note", "plan_gates", "connectors", "held", "card_gate"}


def _crossref(repo_root, kind):
    return sorted((contracts_dir(repo_root) / "fixtures" / "card" / "crossref" / kind).glob("*.json"))


def _shape_errors(registry, ref, instance):
    return [e.message for e in errors_for({"$ref": BASE + ref}, instance, registry)]


def mismatches(case) -> set[str]:
    gate, held = case["card_gate"], case["held"]
    broken = set()
    plan_gate = {g["id"]: g for g in case["plan_gates"]}.get(gate["id"])
    if plan_gate is None or plan_gate["action_type"] != gate["action"]["type"]:
        broken.add("CR-09")
    connector = {c["id"]: c for c in case["connectors"]}.get(gate["action"]["connector"], {"actions": []})
    action = {a["id"]: a for a in connector["actions"]}.get(gate["action"]["type"])
    if action is None or action["gate_type"] != "approval" or action["irreversible"] != gate["irreversible"]:
        broken.add("CR-10")
    if plan_gate is not None and gate["risk_tier"] != ("T3" if held["modifiers"] else plan_gate["risk_tier"]):
        broken.add("CR-11")
    if set(gate["recipients"]) != set(held["recipients"]) or gate["action"]["destination"] != held["destination"]:
        broken.add("CR-12")
    if _pinned(gate["action"]["item"]) != _pinned(held["item"]):
        broken.add("CR-12")
    return broken


def _pinned(item):
    return None if item is None else (item["artifact_id"], item["version"])


def _gate_card(repo_root):
    for path in list_fixtures(repo_root, "card", "valid"):
        card = load_json(path)
        if card["kind"] == "gate" and card["gate"]["irreversible"]:
            return card
    raise AssertionError("need a valid irreversible gate card fixture")


@pytest.mark.parametrize(
    ("option_id", "label"),
    [("approve", "Hold"), ("hold", "Send it"), ("edit", "Keep draft"), ("approve", "Send it")],
)
def test_PRD_10_3_CR_07_gate_option_label_is_fixed_by_id(repo_root, registry, option_id, label):
    card = copy.deepcopy(_gate_card(repo_root))
    next(o for o in card["options"] if o["id"] == option_id)["label"] = label
    assert errors_for(load_schema(repo_root, "card"), card, registry), (
        f"CR-07: a gate's {option_id} option labelled {label!r} must be invalid"
    )


def test_PRD_10_3_CR_07_swapped_gate_labels_are_invalid(repo_root, registry):
    card = copy.deepcopy(_gate_card(repo_root))
    labels = {o["id"]: o for o in card["options"]}
    labels["approve"]["label"], labels["hold"]["label"] = "Hold", "Approve"
    assert errors_for(load_schema(repo_root, "card"), card, registry), (
        "CR-07: approve labelled Hold and hold labelled Approve must be invalid"
    )


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_PRD_10_3_CR_09_to_12_crossref_fixtures_are_shape_valid(repo_root, registry, kind):
    files = _crossref(repo_root, kind)
    assert files, f"contracts/fixtures/card/crossref/{kind}/ must hold at least one case"
    for path in files:
        case = load_json(path)
        assert set(case) == CASE_KEYS, f"{path.name}: keys must be {sorted(CASE_KEYS)}"
        found = _shape_errors(registry, "card.schema.json#/$defs/gate", case["card_gate"])
        for plan_gate in case["plan_gates"]:
            found += _shape_errors(registry, "plan.schema.json#/$defs/gate", plan_gate)
        for connector in case["connectors"]:
            found += _shape_errors(registry, "common.schema.json#/$defs/connector_id", connector["id"])
            for action in connector["actions"]:
                found += _shape_errors(registry, "connector.schema.json#/$defs/action", action)
        for recipient in case["held"]["recipients"]:
            found += _shape_errors(registry, "common.schema.json#/$defs/email_address", recipient)
        for modifier in case["held"]["modifiers"]:
            tier_modifier = {"condition": modifier, "raises_to": "T3"}
            found += _shape_errors(registry, "policy.schema.json#/$defs/tier_modifier", tier_modifier)
        for field in ("item", "destination"):
            found += _shape_errors(registry, f"outbox.schema.json#/properties/{field}", case["held"][field])
        assert not found, f"{path.name}: every part must be shape-valid, got {found[:3]}"


def test_PRD_10_3_CR_09_to_12_valid_gate_cards_match_their_sources(repo_root):
    for path in _crossref(repo_root, "valid"):
        case = load_json(path)
        assert case["rule"] is None and not mismatches(case), f"{path.name}: breaks {sorted(mismatches(case))}"


def test_PRD_10_3_CR_09_to_12_each_invalid_gate_card_breaks_only_its_rule(repo_root):
    covered = set()
    for path in _crossref(repo_root, "invalid"):
        case = load_json(path)
        rule = case["rule"]
        assert path.name.startswith(rule.lower().replace("-", "")), f"{path.name} must start with {rule}"
        assert mismatches(case) == {rule}, f"{path.name}: expected only {rule}, got {sorted(mismatches(case))}"
        covered.add(rule)
    assert covered == set(CROSSREF_RULES), f"every rule needs an invalid case; missing {set(CROSSREF_RULES) - covered}"
