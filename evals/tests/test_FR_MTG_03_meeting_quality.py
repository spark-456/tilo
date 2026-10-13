"""FR-MTG-03/04: offline rubric gates; synthetic data proves mechanics only."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from tilo_evals.meeting_quality import evaluate

ROOT = Path(__file__).resolve().parents[2]


def bank(basis="scripted_fakes"):
    transcript = json.loads((ROOT / "contracts/fixtures/transcript/valid/upload_q4_plan.json").read_text())
    minutes = json.loads((ROOT / "contracts/fixtures/minutes/valid/q4_plan.json").read_text())
    # Contract fixtures lack these referenced lines; these additions are synthetic.
    transcript["utterances"] += [
        {"id": uid, "speaker": "Fixture", "t_ms": i, "text": "Synthetic plumbing."}
        for i, uid in enumerate(["u0010", "u0012", "u0014"])
    ]
    cases = []
    for i in range(1, 13):
        case = {
            "id": f"E-MEET-{i:02d}",
            "basis": basis,
            "transcript": copy.deepcopy(transcript),
            "minutes": copy.deepcopy(minutes),
            "gold": {
                "action_ids": ["gold1"],
                "agenda": minutes["agenda"],
                "summary_score": 4,
                "planted_false_ids": ["ai2"],
                "decision_ids": ["decision1"],
                "planted_false_decision_indices": [1],
                "planted_false_owner_ids": ["ai2"],
            },
            "annotation": {
                "action_matches": {"ai1": "gold1"},
                "invented_commitment_ids": [],
                "dates_correct": True,
                "ambiguous_names_safe": True,
                "decision_matches": ["decision1", None],
                "owner_expected": {"ai1": "u_priya", "ai2": None},
            },
        }
        case["minutes"]["decisions"].append(
            {"text": "Synthetic false decision.", "state": "unverified", "evidence": []}
        )
        case["transcript"]["meeting_id"] = case["minutes"]["meeting_id"] = f"mt_synthetic_{i}"
        case["transcript"]["utterances"].append(
            {"id": "u0030", "speaker": "Fixture", "t_ms": 90000, "text": f"Synthetic case {i}."}
        )
        bind(case)
        cases.append(case)
    return cases


def bind(case):
    payload = {key: case[key] for key in ("transcript", "minutes")}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    case["provenance"] = {"recording_sha256": digest, "reviewer": "rater", "producer": "provider"}


def test_FR_MTG_03_synthetic_never_claims_provider_quality():
    report = evaluate(bank())
    assert report["mechanics"] == "pass"
    assert report["provider_quality"] == "pending"
    assert report["metrics"]["action_precision"] == 1
    assert report["metrics"]["action_recall"] == 1
    assert report["metrics"]["schema_valid_rate"] == 1


def test_FR_MTG_03_recorded_rubric_complete_annotations():
    # Hypothetical input metadata exercises rubric plumbing, not provider certification.
    assert evaluate(bank("recorded_provider"))["provider_quality"] == "pass"


@pytest.mark.parametrize(
    "mutation",
    "schema agenda invented date ambiguous summary evidence false_positive".split(),
)
def test_FR_MTG_03_each_immutable_quality_gate(mutation):
    cases = bank("recorded_provider")
    case = cases[0]
    if mutation == "schema":
        case["minutes"]["flagged"] = "false"
    elif mutation == "agenda":
        case["gold"]["agenda"] = []
    elif mutation == "invented":
        case["annotation"]["invented_commitment_ids"] = ["ai1"]
    elif mutation in ("date", "ambiguous"):
        case["annotation"]["dates_correct" if mutation == "date" else "ambiguous_names_safe"] = False
    elif mutation == "summary":
        case["gold"]["summary_score"] = 3
    elif mutation == "evidence":
        case["minutes"]["action_items"][0]["evidence"] = ["u9999"]
    else:
        for row in cases[:2]:
            row["minutes"]["action_items"][1]["state"] = "verified"
            row["minutes"]["action_items"][1]["evidence"] = ["u0021"]
            row["annotation"]["action_matches"]["ai2"] = None
            bind(row)
    bind(case)
    assert evaluate(cases)["provider_quality"] == "fail"


def test_FR_MTG_03_duplicate_matches_are_false_positives():
    cases = bank("recorded_provider")
    for case in cases[:2]:
        action = copy.deepcopy(case["minutes"]["action_items"][0])
        action["id"] = "ai3"
        case["minutes"]["action_items"].append(action)
        case["annotation"]["action_matches"]["ai3"] = "gold1"
        case["annotation"]["owner_expected"]["ai3"] = "u_priya"
        bind(case)
    report = evaluate(cases)
    assert report["metrics"]["action_recall"] == 1
    assert report["metrics"]["action_precision"] == pytest.approx(12 / 14)
    assert report["provider_quality"] == "fail"


@pytest.mark.parametrize("missing", ["annotation", "summary", "provenance", "independent", "hash"])
def test_FR_MTG_03_missing_evidence_never_passes(missing):
    cases = bank("recorded_provider")
    case = cases[0]
    if missing in ("annotation", "provenance"):
        del case[missing]
    elif missing == "summary":
        case["gold"]["summary_score"] = None
    elif missing == "independent":
        case["provenance"]["reviewer"] = case["provenance"]["producer"]
    else:
        case["provenance"]["recording_sha256"] = "0" * 64
    assert evaluate(cases)["provider_quality"] == "pending"


def test_FR_MTG_03_twelve_distinct_cases_required():
    cases = bank("recorded_provider")
    assert evaluate(cases[:11])["provider_quality"] != "pass"
    cases[-1]["id"] = cases[0]["id"]
    assert evaluate(cases)["provider_quality"] != "pass"


def test_FR_MTG_03_mixed_bases_are_not_pooled():
    cases = bank()
    cases[0]["basis"] = "recorded_provider"
    report = evaluate(cases)
    assert report["metrics"] == {}
    assert set(report["by_basis"]) == {"scripted_fakes", "recorded_provider"}
    assert report["provider_quality"] == "pending"


@pytest.mark.parametrize(
    "field,value", [("dates_correct", "true"), ("action_matches", []), ("ambiguous_names_safe", 1)]
)
def test_FR_MTG_03_mistyped_annotation_fails_closed(field, value):
    cases = bank("recorded_provider")
    cases[0]["annotation"][field] = value
    assert evaluate(cases)["provider_quality"] != "pass"


def test_FR_MTG_03_recall_threshold_cannot_be_weakened():
    cases = bank("recorded_provider")
    for case in cases[:3]:
        case["gold"]["action_ids"].append("missed")
    assert evaluate(cases)["provider_quality"] == "fail"


def test_FR_MTG_03_duplicate_transcript_content_is_not_a_corpus():
    cases = bank("recorded_provider")
    for case in cases:
        case["transcript"] = copy.deepcopy(cases[0]["transcript"])
        case["minutes"]["meeting_id"] = cases[0]["transcript"]["meeting_id"]
        bind(case)
    assert evaluate(cases)["provider_quality"] == "pending"


def test_FR_MTG_03_empty_gold_actions_are_missing_metric_evidence():
    cases = bank("recorded_provider")
    for case in cases:
        case["gold"]["action_ids"] = []
        case["annotation"]["action_matches"] = {}
        case["minutes"]["action_items"][0]["state"] = "unverified"
        bind(case)
    report = evaluate(cases)
    assert report["provider_quality"] == "pending"
    assert report["metrics"]["action_recall"] is None
    assert report["metrics"]["action_precision"] is None
