"""Offline semantic agenda checks; stored titles and absence claims are never model authority."""

import json

import pytest
from test_FR_MTG_03_minutes_analysis import Script
from test_FR_MTG_03_minutes_analysis import case as analysis_case
from tilo_api.meeting_analysis import analyze_minutes
from tilo_providers.safety import FakeSafetyProvider

case = analysis_case


def run(case, router, agenda=None):
    transcript, doc, directory, now = case
    return analyze_minutes(
        router,
        transcript,
        doc["transcript"],
        directory=directory,
        viewer="u_owner",
        meeting_at=now,
        now=now,
        budget=2,
        safety=FakeSafetyProvider(),
        agenda=agenda if agenda is not None else [{"title": "Rate sheet", "minutes": 5}],
    )


def proposal(case, coverage="covered", evidence=None):
    case[1].update(
        decisions=[],
        agenda=[
            {
                "title": "Rate sheet",
                "coverage": coverage,
                "evidence": [case[0]["utterances"][0]["id"]] if evidence is None else evidence,
            }
        ],
    )


@pytest.mark.parametrize("coverage", ["covered", "partial", "not_discussed"])
def test_FR_MTG_03_agenda_requires_semantic_verdict_and_stored_title(case, coverage):
    proposal(case, coverage, [] if coverage == "not_discussed" else None)
    router = Script(case[1], {"supported": [True]})
    result = run(case, router)
    assert result["agenda"] == case[1]["agenda"]
    payload = json.loads(router.calls[1][1].prompt.split("\n", 1)[1].rsplit("\n", 1)[0])
    check = payload["checks"][0]
    assert check["claim"] == {"title": "Rate sheet", "coverage": coverage}
    assert payload["transcript"] == case[0]  # absence cannot be verified from selected spans
    generated = json.loads(router.calls[0][1].prompt.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert generated["agenda"] == [{"title": "Rate sheet", "minutes": 5}]
    assert router.calls[1][2] == 0.75


@pytest.mark.parametrize(
    "answer",
    [
        {"supported": [False]},
        {"supported": []},
        {"supported": ["true"]},
        {"supported": [True, True]},
        {"supported": [True], "extra": 1},
        RuntimeError("offline"),
    ],
)
def test_FR_MTG_03_unverified_agenda_refuses_minutes(case, answer):
    proposal(case)
    with pytest.raises(ValueError, match="analysis_failed"):
        run(case, Script(case[1], answer))


@pytest.mark.parametrize("change", ["missing", "invented", "duplicate", "empty_evidence", "unknown_evidence"])
def test_FR_MTG_03_agenda_shape_or_pin_failure_before_verifier(case, change):
    proposal(case)
    if change == "missing":
        case[1]["agenda"] = []
    elif change == "invented":
        case[1]["agenda"][0]["title"] = "Invented topic"
    elif change == "duplicate":
        case[1]["agenda"] *= 2
    else:
        case[1]["agenda"][0]["evidence"] = [] if change == "empty_evidence" else ["u9999"]
    router = Script(case[1], {"supported": [True]})
    with pytest.raises(ValueError, match="analysis_failed"):
        run(case, router)
    assert len(router.calls) == 1


def test_FR_MTG_03_agenda_budget_exhaustion_cannot_publish_coverage(case):
    proposal(case)
    router = Script(case[1])
    router.budget = 0
    with pytest.raises(ValueError, match="analysis_failed"):
        run(case, router)
    assert len(router.calls) == 1


def test_FR_MTG_03_no_stored_agenda_cannot_invent_a_topic(case):
    proposal(case)
    with pytest.raises(ValueError, match="analysis_failed"):
        run(case, Script(case[1]), agenda=[])
