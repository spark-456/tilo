"""COST-FAST-1 (requirements 3 and 4): Quick refuses real work with a typed offer to switch to Thinking.

Real work (needs tools, deliverables or files to produce, side effects, a long multi-step ask, an attachment that needs
processing) is not answered badly in Quick. The response is exactly
`{"mode": "quick", "outcome": "switch_to_thinking", "reason": <fixed code>}` (HTTP 200). Nothing is created or stored,
nothing is charged, and no model is called: a deterministic rules-first classifier decides, so its cost is zero. The
classifier only suggests: Thinking chosen is always Thinking, Quick chosen plus work is the explicit offer and is never
silently run as Thinking, Quick chosen plus a simple question is answered. The model is only a vetted fallback for a
text no rule reads: its reply is a closed shape (exact keys, a reason from the fixed set) and a bad one is no verdict.
Shapes and reasons: `API_COST_FAST_1.md`. Fakes only; no network, no paid call.
"""

from __future__ import annotations

import json

import pytest
from _api_contracts_lib import make_docx_bytes, make_png_bytes
from _clint1_lib import FLOW_USER
from _costfast1_lib import ANSWER, SIMPLE_TEXT, assert_answer_shape, assert_offer_shape

# (text, the reason the ask must carry, or None where any reason of the fixed set will do)
WORK = [
    ("Send an email to the supplier asking for a new quote.", "side_effect"),
    ("Post a message in the team channel saying the release is out.", "side_effect"),
    ("Delete all the old files from my drive.", "side_effect"),
    ("Create a 12-slide presentation about our Q3 results.", "deliverable"),
    ("Write a PDF report on supplier prices.", "deliverable"),
    ("Build me a spreadsheet that tracks weekly expenses.", "deliverable"),
    (
        "First gather last quarter's sales, then compare them with the plan, then rank the regions, then explain "
        "the gaps.",
        "multi_step",
    ),
    ("Research our top five competitors, compare their pricing and write up the findings.", None),
    ("Search the web for the latest EU battery regulations and summarise them with sources.", None),
    ("Check my calendar and book a 30 minute meeting with Priya next week.", None),
    ("Read my inbox and draft replies to everything urgent.", None),
    ("Every Monday at 9 send me a summary of open invoices.", None),
    ("Book a flight to Singapore next Tuesday.", None),
]


def assert_no_cost_no_trace(rig) -> None:
    assert rig.calls == [] and rig.provider_requests == [], "the rules decide: no model is called, so no cost"
    rig.assert_nothing_stored()
    assert rig.allowance.spent(FLOW_USER, rig_today()) == 0


def rig_today() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC).strftime("%Y-%m-%d")


@pytest.mark.parametrize(("text", "reason"), WORK)
def test_COST_FAST_1_real_work_in_quick_is_a_typed_switch_offer_decided_by_rules(quick_rig, text, reason):
    response = quick_rig.ask(text, mode="quick")

    assert response.status_code == 200, response.text
    assert_offer_shape(response.json(), reason)
    assert_no_cost_no_trace(quick_rig)
    assert "director" not in quick_rig.roles, "never silently run as Thinking"


def test_COST_FAST_1_the_same_work_in_thinking_is_the_full_flow(quick_rig):
    """Thinking chosen is always Thinking: the classifier suggests, the person's choice decides."""
    for text, _reason in WORK:
        quick_rig.reset()

        response = quick_rig.ask(text, mode="thinking")

        assert response.status_code == 201, (text, response.text)
        assert response.json()["mode"] == "thinking" and "outcome" not in response.json()
        assert quick_rig.roles == ["director"]


def test_COST_FAST_1_an_attachment_in_quick_is_offered_thinking_and_the_file_is_never_read(quick_rig):
    """Even a trivial question about a file is work: the file needs processing, and Quick processes nothing."""
    response = quick_rig.ask(
        "What does this say?", mode="quick", files=[("notes.docx", make_docx_bytes("Ordinary notes."))]
    )

    assert response.status_code == 200, response.text
    assert_offer_shape(response.json(), "attachments")
    assert_no_cost_no_trace(quick_rig)


def test_COST_FAST_1_an_image_attachment_is_offered_thinking_too(quick_rig):
    response = quick_rig.ask("Describe this.", mode="quick", files=[("photo.png", make_png_bytes())])

    assert response.status_code == 200, response.text
    assert_offer_shape(response.json(), "attachments")
    assert_no_cost_no_trace(quick_rig)


def test_COST_FAST_1_attachment_limits_are_the_same_422s_as_today(quick_rig):
    many = [(f"f{n}.docx", make_docx_bytes("x")) for n in range(11)]

    too_many = quick_rig.ask("What does this say?", mode="quick", files=many)
    bad_type = quick_rig.ask("What does this say?", mode="quick", files=[("run.exe", b"MZ")])

    assert too_many.status_code == 422 and bad_type.status_code == 422
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_scenario_in_quick_is_offered_thinking(quick_rig):
    """A scenario is preloaded work (FR-INT-11): Quick does not run it."""
    response = quick_rig.ask(SIMPLE_TEXT, mode="quick", scenario="SC-01")

    assert response.status_code == 200, response.text
    assert_offer_shape(response.json(), "scenario")
    assert_no_cost_no_trace(quick_rig)


def test_COST_FAST_1_the_offer_is_the_same_whatever_the_model_would_say(quick_rig):
    """The model cannot talk a rules verdict out of its answer: for work, no model is asked at all."""
    quick_rig.classifier_reply = json.dumps({"kind": "simple"})
    quick_rig.answer = "Sure, I did it."

    response = quick_rig.ask("Send an email to the supplier asking for a new quote.")

    assert_offer_shape(response.json(), "side_effect")
    assert quick_rig.provider_requests == []


def test_COST_FAST_1_a_simple_question_is_answered_not_offered_whatever_the_model_would_say(quick_rig):
    quick_rig.classifier_reply = json.dumps({"kind": "work", "reason": "deliverable"})

    response = quick_rig.ask(SIMPLE_TEXT)

    assert_answer_shape(response.json())
    assert response.json()["text"] == ANSWER
    assert quick_rig.classifier_calls == [], "a plain question needs no classifier call"


def test_COST_FAST_1_the_same_text_gets_the_same_verdict_every_time(quick_rig):
    verdicts = []
    for text in [t for t, _ in WORK] + [SIMPLE_TEXT]:
        for _ in range(2):
            body = quick_rig.ask(text, mode="quick").json()
            verdicts.append((text, body["outcome"], body.get("reason")))
    for text in {t for t, _, _ in verdicts}:
        assert len({v for v in verdicts if v[0] == text}) == 1, text


# --- the vetted model fallback: only for a text no rule reads ----------------------------------------------------

UNSURE = ["hmm", "thoughts on the quarterly numbers?", "tell me about Q3", "what do you think about this plan", "help"]
BAD_VERDICTS = [
    json.dumps({"kind": "simple", "reason": "deliverable"}),  # an extra key
    json.dumps({"kind": "work"}),  # a missing reason
    json.dumps({"kind": "work", "reason": "drop table users"}),  # a reason outside the fixed set
    json.dumps({"kind": "work", "reason": "deliverable", "approve": True}),
    json.dumps({"kind": ["simple"]}),
    json.dumps({"verdict": "work"}),
    '{"kind": "simple", "kind": "work", "reason": "deliverable"}',  # a duplicate key
    '{"kind": "work", "reason": "deliverable"} and then some prose',
    "Sure! It is a simple question.",
    '{"kind": "work", "reason": NaN}',
    "[]",
    '"simple"',
    "",
]


@pytest.mark.parametrize("reply", BAD_VERDICTS)
def test_COST_FAST_1_a_bad_classifier_reply_is_no_verdict_and_never_an_answer(quick_rig, reply):
    quick_rig.classifier_reply = reply
    for text in UNSURE:
        quick_rig.reset()

        response = quick_rig.ask(text)

        assert response.status_code == 200, (text, response.text)
        body = response.json()
        if quick_rig.classifier_calls:  # the rules left this text to the model, and its reply was not a verdict
            assert_offer_shape(body, "unclear")
            assert quick_rig.answer_calls == [], "no answer is written on the strength of a bad verdict"
        assert not any(c.is_director or c.is_approaches for c in quick_rig.calls)
        quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_valid_classifier_verdict_decides_and_the_whole_ask_stays_inside_half_a_credit(quick_rig):
    for text in UNSURE:
        check_valid_verdicts(quick_rig, text)


def check_valid_verdicts(quick_rig, text):
    for verdict, expected in (
        ({"kind": "simple"}, "answered"),
        ({"kind": "work", "reason": "needs_tools"}, "switch_to_thinking"),
    ):
        quick_rig.reset()
        quick_rig.classifier_reply = json.dumps(verdict)
        response = quick_rig.ask(text)
        assert response.status_code == 200, response.text
        body = response.json()
        if not quick_rig.classifier_calls:
            continue  # the rules decided this one
        assert body["outcome"] == expected
        assert all(c.role == "assistant" for c in quick_rig.calls)
        if expected == "switch_to_thinking":
            assert body["reason"] == "needs_tools" and quick_rig.answer_calls == []
        else:
            assert_answer_shape(body)
            assert body["cost"]["model_calls"] == len(quick_rig.calls) == 2
            assert 0 < body["cost"]["credits"] <= 0.5, "the classifier call and the answer share one half credit"
            assert quick_rig.calls[0].budget is not None and quick_rig.calls[0].budget <= 0.5
        quick_rig.assert_nothing_stored()
