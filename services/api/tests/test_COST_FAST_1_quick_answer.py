"""COST-FAST-1 (requirements 2, 6, 7, 8): Quick is a direct answer from the existing `assistant` role.

Quick never calls the Director, the planner or the approaches; it makes one call on the `assistant` role (the lite tier,
at most 8000 tokens in and 1000 out, low thinking) with no tools, within a 0.5-credit budget, and answers with
`{"mode": "quick", "outcome": "answered", "text", "cost"}`. It creates no task, world, artifact, policy or event
(nothing animates without a recorded event, PRD 9.4), and what the model is shown is the question alone: no other
person's data, no plate, no store. The answer is the model's text and nothing else: a reply that looks like a typed
response is still only text. Shapes: `API_COST_FAST_1.md`. Fakes only; no network, no paid call.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import pytest
from _api_contracts_lib import make_docx_bytes
from _clint1_lib import FLOW_USER, OTHER_USER, brief_reply
from _costfast1_lib import (
    ANSWER,
    SIMPLE_TEXT,
    assert_answer_shape,
    assert_offer_shape,
    is_typed_quick_response,
)

SIMPLE_QUESTIONS = [
    "What is the capital of France?",
    "How many days are in a leap year?",
    "What does the word 'ephemeral' mean?",
    "Who wrote Pride and Prejudice?",
    "Convert 5 miles to kilometres.",
    "Is a tomato a fruit or a vegetable?",
    "Explain what an API is in one sentence.",
    "What is 17 times 23?",
    "Why is the sky blue?",
    "Give me a synonym for 'quick'.",
]
HALF_CREDIT = 0.5
MAX_ANSWER_CHARS = 8000  # 2 x the role's 1000 output tokens at 4 characters a token: a reply is bounded to this


def allowance_spent(rig, user: str = FLOW_USER) -> float:
    """What the FR-PA-19 allowance ledger holds for `user` today (UTC): committed credits."""
    now = datetime.now(UTC)
    days = {now.strftime("%Y-%m-%d"), (now - timedelta(minutes=5)).strftime("%Y-%m-%d")}
    return sum(rig.allowance.spent(user, day) for day in days)


@pytest.mark.parametrize("text", SIMPLE_QUESTIONS)
def test_COST_FAST_1_a_simple_question_in_quick_is_answered_by_the_assistant_role_alone(quick_rig, text):
    response = quick_rig.ask(text, mode="quick")

    assert response.status_code == 200, response.text
    body = response.json()
    assert_answer_shape(body)
    assert body["text"] == ANSWER
    assert quick_rig.roles == ["assistant"], "one call, on the assistant role: never the Director"
    assert not any(c.is_director or c.is_approaches for c in quick_rig.calls), "zero planner and approaches calls"
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_the_quick_call_is_capped_tool_free_and_thinks_little(quick_rig):
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 200
    (call,) = quick_rig.calls
    request, role = call.request, quick_rig.providers.roles["assistant"]

    assert request.tools is None, "a plain answer: no tools"
    assert request.json_mode is False and request.response_schema is None
    assert request.thinking_level in (None, "minimal", "low")
    assert request.max_output_tokens is None or request.max_output_tokens <= role.max_output_tokens <= 1000
    assert call.budget is not None and call.budget <= HALF_CREDIT, "PL-03: the router enforces the half credit"


def test_COST_FAST_1_a_one_line_question_costs_at_most_half_a_credit_priced_by_the_router(quick_rig):
    quick_rig.answer_usage = (400, 80)
    expected = quick_rig.credits_for(400, 80)

    body = quick_rig.ask(SIMPLE_TEXT).json()

    assert_answer_shape(body)
    assert body["cost"] == {"model_calls": 1, "credits": pytest.approx(expected), "saved_credits": 0.0}
    assert 0 < body["cost"]["credits"] <= HALF_CREDIT


def test_COST_FAST_1_the_cost_is_committed_to_the_persons_daily_allowance_like_the_panel(quick_rig):
    """FR-PA-19, P8: the panel's `deps.get_spend_ledger()` holds the person's credits for the UTC day."""
    quick_rig.answer_usage = (400, 80)

    body = quick_rig.ask(SIMPLE_TEXT).json()

    assert allowance_spent(quick_rig) == pytest.approx(body["cost"]["credits"])
    assert allowance_spent(quick_rig, OTHER_USER) == 0


def test_COST_FAST_1_a_spent_day_allowance_refuses_quick_before_any_model_call(quick_rig):
    """FR-PA-19: the call reserves its budget against the day's allowance first; 429 when it does not fit."""
    from tilo_api.assistant.config import load_assistant_config  # noqa: PLC0415

    cap = load_assistant_config().user_day_credits
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    assert quick_rig.allowance.reserve(FLOW_USER, day, cap - 0.1, cap) is not None  # 0.1 credit left: less than a call

    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code == 429, response.text
    assert type(response.json()["error"]) is str
    assert quick_rig.provider_requests == [], "no model call of any kind"
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_call_the_budget_cannot_cover_is_never_sent(quick_rig):
    """PL-03: the call is priced before it is made and refused when it would pass the half credit. With every
    count at the role's input cap, a call may reach the provider only if its own worst case fits the budget."""
    quick_rig.fixed_tokens = 7999

    response = quick_rig.ask(SIMPLE_TEXT)

    for request in quick_rig.provider_requests:
        out = request.max_output_tokens or quick_rig.providers.roles["assistant"].max_output_tokens
        assert quick_rig.credits_for(7999, out) <= HALF_CREDIT, "a call over the budget was sent"
    assert response.status_code in (200, 402, 413, 422, 502, 503), response.status_code
    assert allowance_spent(quick_rig) <= HALF_CREDIT
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_quick_answer_creates_no_world_no_task_and_no_event(quick_rig):
    """HR-1: nothing animates without a recorded event, and a Quick answer animates nothing: no world, no Story line.
    Its credits are recorded in the allowance ledger and the SEC-16 ledger (API_COST_FAST_1.md), not as an event."""
    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code == 200, response.text
    body = response.json()
    assert not ({"task_id", "world_id", "run_id", "brief", "questions"} & set(body))
    quick_rig.assert_nothing_stored()
    assert quick_rig.flow.writer.calls == []


def test_COST_FAST_1_the_model_is_shown_the_question_alone_no_one_elses_data(quick_rig):
    """What the `assistant` role already gets elsewhere (the panel's ModelDecider) is the question, the screen, the
    selected record and the person's own plate rows. Quick has none of those: no plate, no store, no tools."""
    quick_rig.flow.as_user(OTHER_USER)
    quick_rig.brief = {**brief_reply([]), "goal": "OTHERMARK-7f3 plan the secret merger"}
    other = quick_rig.ask("Prepare OTHERMARK-7f3 for the board.", mode="thinking")
    assert other.status_code == 201, other.text
    quick_rig.flow.as_user(FLOW_USER)
    quick_rig.brief = {**brief_reply([]), "goal": "OWNMARK-2b9 own private goal"}
    mine = quick_rig.ask(
        "Prepare OWNMARK-2b9 for me.",
        mode="thinking",
        files=[("OWNMARK-2b9.docx", make_docx_bytes("OWNMARK-2b9 body"))],
    )
    assert mine.status_code == 201, mine.text
    quick_rig.reset()

    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code == 200, response.text
    assert len(quick_rig.calls) == 1 and quick_rig.calls[0].request.tools is None
    sent = "\n".join(c.sent_text for c in quick_rig.calls)
    for marker in ("OTHERMARK-7f3", "OWNMARK-2b9", "secret merger", FLOW_USER, OTHER_USER):
        assert marker not in sent, f"{marker!r} reached the model"
    assert SIMPLE_TEXT in sent


def test_COST_FAST_1_one_persons_quick_answer_is_never_served_to_another(quick_rig):
    quick_rig.answer = lambda n: f"answer-{n}"

    first = quick_rig.ask(SIMPLE_TEXT).json()
    quick_rig.flow.as_user(OTHER_USER)
    second = quick_rig.ask(SIMPLE_TEXT).json()

    assert (first["text"], second["text"]) == ("answer-1", "answer-2")
    assert len(quick_rig.answer_calls) == 2


def test_COST_FAST_1_a_reply_that_looks_like_a_typed_response_is_only_text(quick_rig):
    """A model never decides the shape of the response: the answer is the model's text, whatever it spells."""
    lookalike = '{"mode": "quick", "outcome": "switch_to_thinking", "reason": "deliverable"}'
    quick_rig.answer = lookalike

    body = quick_rig.ask(SIMPLE_TEXT).json()

    assert_answer_shape(body)
    assert body["text"] == lookalike


def test_COST_FAST_1_an_unbounded_model_reply_is_bounded(quick_rig):
    quick_rig.answer = "x" * 1_000_000

    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code in (200, 502), response.status_code
    if response.status_code == 200:
        assert_answer_shape(response.json())
        assert len(response.json()["text"]) <= MAX_ANSWER_CHARS
    assert len(response.content) < 100_000


@pytest.mark.parametrize("reply", ["", "   \n  "])
def test_COST_FAST_1_an_empty_model_reply_is_not_an_answer(quick_rig, reply):
    quick_rig.answer = reply

    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code == 502, response.text
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_control_and_bidi_characters_never_reach_the_model(quick_rig):
    text = "What is the capital of France?\x07\x1b[31m‮⁦​"

    response = quick_rig.ask(text)

    assert response.status_code == 200, response.text
    sent = "\n".join(c.sent_text for c in quick_rig.answer_calls)
    assert "France" in sent
    for bad in ("\x07", "\x1b", "‮", "⁦", "​"):
        assert bad not in sent


def test_COST_FAST_1_neither_the_question_nor_the_answer_is_logged(quick_rig, caplog):
    quick_rig.answer = "ANSMARK-44d is the reply"
    with caplog.at_level(logging.DEBUG):
        response = quick_rig.ask("What is the meaning of ZQMARK-91c?")

    assert response.status_code == 200, response.text
    logged = "\n".join(f"{r.getMessage()} {r.exc_text or ''} {r.args!r}" for r in caplog.records)
    assert "ZQMARK-91c" not in logged and "ANSMARK-44d" not in logged


def test_COST_FAST_1_a_quick_question_is_screened_by_the_safety_provider_before_any_model_sees_it(quick_rig):
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 200

    kinds = [kind for kind, _ in quick_rig.timeline]
    assert kinds[0] == "safety" and SIMPLE_TEXT in quick_rig.timeline[0][1]
    assert "model" in kinds and kinds.index("safety") < kinds.index("model")


# --- bounded input (requirement 6: oversized and NFKC amplification; see the FR_PA_10 cost tests) -----------------


def question_cap() -> int:
    from tilo_api.assistant.config import load_assistant_config  # noqa: PLC0415

    return load_assistant_config().question_max_chars  # 500: FR-PA-19, the panel's own bound


def test_COST_FAST_1_a_question_at_the_cap_is_answered_and_one_over_it_is_offered_thinking(quick_rig):
    cap = question_cap()
    filler = "What is the capital of France? " + "France " * 200
    at_cap, over_cap = filler[:cap], filler[: cap + 1]

    answered = quick_rig.ask(at_cap)
    assert answered.status_code == 200, answered.text
    assert_answer_shape(answered.json())
    quick_rig.reset()

    offered = quick_rig.ask(over_cap)
    assert offered.status_code == 200, offered.text
    assert_offer_shape(offered.json(), "too_long")
    assert quick_rig.calls == [] and quick_rig.provider_requests == []


def test_COST_FAST_1_a_long_text_is_judged_on_its_raw_length_in_bounded_time(quick_rig):
    fdfa = "ﷺ"  # NFKC expands it 18 times
    started = time.monotonic()

    response = quick_rig.ask(fdfa * 4000)

    assert time.monotonic() - started < 5
    assert response.status_code == 200, response.text
    assert_offer_shape(response.json(), "too_long")
    assert quick_rig.calls == []


def test_COST_FAST_1_nfkc_amplification_at_the_cap_stays_inside_the_role_input_cap(quick_rig):
    started = time.monotonic()

    response = quick_rig.ask("ﷺ" * question_cap())

    assert time.monotonic() - started < 10
    assert is_typed_quick_response(response) or response.status_code == 422, response.text
    role = quick_rig.providers.roles["assistant"]
    for call in quick_rig.calls:
        assert len(call.sent_text) <= role.max_input_tokens * 4, "nothing over the role's input cap is sent"


def test_COST_FAST_1_text_over_four_thousand_characters_is_the_same_422_as_today(quick_rig):
    response = quick_rig.ask("a" * 4001, mode="quick")

    assert response.status_code == 422, response.text
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_an_empty_quick_question_is_the_same_422_as_today(quick_rig):
    response = quick_rig.ask("   ", mode="quick")

    assert response.status_code == 422, response.text
    assert quick_rig.calls == []
