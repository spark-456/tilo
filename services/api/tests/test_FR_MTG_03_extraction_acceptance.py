"""12 E-MEET scripted cases: acceptance plumbing, not a live-provider quality measurement."""

import copy

import pytest
from _ppl11a_lib import conforms
from test_FR_MTG_03_agenda_verification import run
from test_FR_MTG_03_minutes_analysis import Script
from test_FR_MTG_03_minutes_analysis import case as analysis_case

case = analysis_case

# Source, generated paraphrase, independent gold expectation. Negative cases deliberately
# propose a plausible false task so the verifier boundary, rather than an empty output, is exercised.
CASES = [
    ("Priya, send the rate sheet tomorrow.", "Send the rate sheet", True),
    ("Sam, draft the launch note next Friday.", "Draft the launch note", True),
    ("Asha, book the review on Monday.", "Book the review", True),
    ("Priya, check the release checklist.", "Check the release checklist", True),
    ("Unknown colleague, prepare a cost estimate.", "Prepare a cost estimate", True),
    ("I will circulate the revised agenda.", "Circulate the revised agenda", True),
    ("Can Priya send the rate sheet tomorrow? No decision yet.", "Send the rate sheet", False),
    ("Sam must not publish the launch note.", "Publish the launch note", False),
    ("If we approve the launch, Asha could book the review.", "Book the review", False),
    ("Maybe Priya should check the release checklist; let us decide later.", "Check the release checklist", False),
    ("The cost estimate was sent yesterday; no new task.", "Prepare a cost estimate", False),
    ("We are discussing the agenda; nobody volunteered to circulate it.", "Circulate the revised agenda", False),
]


def metrics(gold, predicted):
    # One-to-one matching: duplicates are false positives, never extra recall.
    unmatched = list(gold)
    hits = 0
    for value in predicted:
        if value in unmatched:
            hits += 1
            unmatched.remove(value)
    return hits / len(gold) if gold else 1, hits / len(predicted) if predicted else (0 if gold else 1)


def accepted(gold, predicted):
    recall, precision = metrics(gold, predicted)
    return recall >= 0.85 and precision >= 0.90


def test_FR_MTG_03_12_scripted_transcripts_recall_precision_and_agenda_gate(case):
    gold, predicted = [], []
    valid, agenda_correct = 0, 0
    for index, (spoken, task, expected) in enumerate(CASES):
        local = (*copy.deepcopy(case[:2]), *case[2:])
        transcript, doc, _, _ = local
        quote = copy.deepcopy(transcript["utterances"][0])
        quote["text"] = spoken
        transcript["utterances"] = [quote]
        doc.update(
            decisions=[],
            summary=[],
            action_items=[
                {
                    "id": "ai1",
                    "text": task,
                    "state": "verified",
                    "evidence": [quote["id"]],
                    "owner_text": None,
                    "owner": None,
                    "due_text": None,
                    "due": None,
                    "work_item_id": None,
                }
            ],
            agenda=[{"title": "Next steps", "coverage": "partial", "evidence": [quote["id"]]}],
        )
        router = Script(doc, {"supported": [True, expected]})
        result = run(local, router, agenda=[{"title": "Next steps", "minutes": None}])
        valid += conforms("minutes.schema.json", result)
        agenda_correct += result["agenda"] == doc["agenda"]
        if expected:
            gold.append((index, task, (quote["id"],)))
        predicted.extend(
            (index, row["text"], tuple(row["evidence"])) for row in result["action_items"] if row["state"] == "verified"
        )
        assert all(row["work_item_id"] is None for row in result["action_items"])
        assert result["action_items"][0]["state"] == ("verified" if expected else "unverified")
    assert len(CASES) == valid == agenda_correct == 12
    assert accepted(gold, predicted)
    assert metrics(gold, predicted) == (1, 1)
    assert set(predicted) <= set(gold)  # zero invented verified commitments


@pytest.mark.parametrize(
    "gold,predicted",
    [
        (list(range(12)), list(range(10))),  # 83% recall
        (list(range(12)), list(range(14))),  # 86% precision
        (list(range(12)), list(range(12)) + [0, 0]),  # duplicate commitment inflates precision denominator
        ([1], []),
        ([], [1]),
    ],
)
def test_FR_MTG_03_extraction_gate_rejects_misses_inventions_and_duplicates(gold, predicted):
    assert not accepted(gold, predicted)
