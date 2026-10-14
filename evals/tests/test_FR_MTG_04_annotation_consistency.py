"""Independent annotation consistency; synthetic inputs do not certify providers."""

import pytest
from test_FR_MTG_03_meeting_quality import bank
from tilo_evals.meeting_quality import evaluate


@pytest.mark.parametrize("match", ["unknown-gold", "", True, 1, [], {}])
def test_FR_MTG_04_invalid_action_match_never_passes(match):
    cases = bank("recorded_provider")
    cases[0]["annotation"]["action_matches"]["ai1"] = match
    report = evaluate(cases)
    assert report["provider_quality"] == "pending"
    assert "annotation shape" in report["pending"]


def test_FR_MTG_04_unverified_action_requires_independent_mapping():
    cases = bank("recorded_provider")
    assert evaluate(cases)["provider_quality"] == "pass"
    del cases[0]["annotation"]["action_matches"]["ai2"]
    report = evaluate(cases)
    assert report["provider_quality"] == "pending"
    assert "action matching incomplete" in report["pending"]


@pytest.mark.parametrize("claim", ["action", "decision"])
def test_FR_MTG_04_planted_false_claim_cannot_also_match_gold(claim):
    cases = bank("recorded_provider")
    case = cases[0]
    if claim == "action":
        case["annotation"]["action_matches"]["ai2"] = "gold1"
    else:
        case["annotation"]["decision_matches"][1] = "decision1"
    report = evaluate(cases)
    assert report["provider_quality"] == "fail"
    assert f"contradictory planted false {claim} annotation" in report["failures"]


def test_FR_MTG_04_consistent_complete_synthetic_annotations_stay_pending():
    report = evaluate(bank())
    assert report["mechanics"] == "pass"
    assert report["provider_quality"] == "pending"
