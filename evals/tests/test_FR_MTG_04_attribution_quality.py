"""Adversarial annotation gates; hypothetical metadata never certifies a provider."""

import copy

import pytest
from test_FR_MTG_03_meeting_quality import bank, bind
from tilo_evals.meeting_quality import evaluate


@pytest.mark.parametrize(
    "missing",
    ["decision_ids", "planted_false_decision_indices", "planted_false_owner_ids", "decision_matches", "owner_expected"],
)
def test_FR_MTG_04_action_only_annotations_are_pending(missing):
    cases = bank("recorded_provider")
    section = "annotation" if missing in ("decision_matches", "owner_expected") else "gold"
    del cases[0][section][missing]
    assert evaluate(cases)["provider_quality"] == "pending"


@pytest.mark.parametrize(
    "mutation",
    [
        "unsupported",
        "duplicate",
        "false_verified",
        "false_dropped",
        "wrong_owner",
        "ambiguous_owner",
        "owner_dropped",
        "owner_verified",
    ],
)
def test_FR_MTG_04_false_credit_is_refused(mutation):
    cases = bank("recorded_provider")
    for case in cases:
        decisions = case["minutes"]["decisions"]
        if mutation == "unsupported":
            case["annotation"]["decision_matches"][0] = None
        elif mutation == "duplicate":
            decisions.append(copy.deepcopy(decisions[0]))
            case["annotation"]["decision_matches"].append("decision1")
        elif mutation == "false_verified":
            decisions[1].update(state="verified", evidence=["u0012"])
        elif mutation == "false_dropped":
            decisions.pop()
            case["annotation"]["decision_matches"].pop()
        elif mutation == "wrong_owner":
            case["minutes"]["action_items"][0]["owner"] = "u_wrong"
        elif mutation == "owner_dropped":
            case["minutes"]["action_items"].pop()
        elif mutation == "owner_verified":
            case["minutes"]["action_items"][1].update(state="verified", evidence=["u0012"])
            case["annotation"]["action_matches"]["ai2"] = "gold1"
        else:
            case["minutes"]["action_items"][1]["owner"] = "u_sam"
        bind(case)
    assert evaluate(cases)["provider_quality"] == "fail"


@pytest.mark.parametrize(
    "field,value", [("decision_matches", []), ("decision_matches", [True, None]), ("owner_expected", {})]
)
def test_FR_MTG_04_incomplete_or_mistyped_attribution_is_pending(field, value):
    cases = bank("recorded_provider")
    cases[0]["annotation"][field] = value
    assert evaluate(cases)["provider_quality"] == "pending"


def test_FR_MTG_04_absent_transcript_cannot_pass():
    cases = bank("recorded_provider")
    del cases[0]["transcript"]
    assert evaluate(cases)["provider_quality"] != "pass"


def test_FR_MTG_04_synthetic_complete_attribution_stays_provider_pending():
    report = evaluate(bank())
    assert report["mechanics"] == "pass"
    assert report["provider_quality"] == "pending"
    assert report["metrics"]["planted_false_decision_detection"] == 1
    assert report["metrics"]["planted_false_owner_detection"] == 1
