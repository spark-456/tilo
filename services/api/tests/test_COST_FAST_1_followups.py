"""COST-FAST-1 fix pass (review follow-ups): a billed call stays charged, the rules see all of a long text, the cleaned
text is screened, a live ask without a ledger is refused, a reply is plain text, linear splitting, explicit output cap.
Fakes only; no network, no paid call."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from _api_contracts_lib import INJECTION_PHRASE
from _clint1_lib import FLOW_USER
from _costfast1_lib import SIMPLE_TEXT, assert_answer_shape, assert_offer_shape, sec16_rig
from _sec16_lib import JUDGE_A
from tilo_providers.errors import OutputTruncatedError, RequestError

BIG = {"rate_limit_requests": 1_000}


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def test_COST_FAST_1_a_truncated_reply_is_charged_not_released(quick_rig):
    quick_rig.fail = OutputTruncatedError("cut (fake)", output_tokens=1000)
    for _ in range(5):
        assert quick_rig.ask(SIMPLE_TEXT).status_code == 502
    assert quick_rig.allowance.spent(FLOW_USER, today()) > 0


def test_COST_FAST_1_SEC_16_a_truncated_reply_settles_the_unit(sec16_factory, monkeypatch, repo_root):
    h = sec16_factory(**BIG)
    rig = sec16_rig(h, monkeypatch, repo_root)
    rig.fail = OutputTruncatedError("cut (fake)", output_tokens=1000)
    for _ in range(2):
        assert rig.ask(SIMPLE_TEXT).status_code == 502
    assert h.ledger.writes == ["reserve", "settle"] * 2
    assert h.ledger.settled_minor(JUDGE_A) == 2 * h.caps.unit_reserve_minor


@pytest.mark.parametrize("reply", ["", "  \n "])
def test_COST_FAST_1_an_empty_reply_was_billed_and_is_charged(quick_rig, reply):
    quick_rig.answer = reply
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 502
    assert quick_rig.allowance.spent(FLOW_USER, today()) == pytest.approx(quick_rig.credits_for(400, 80))


def test_COST_FAST_1_a_classifier_that_ran_then_a_failed_answer_charges_the_classifier(quick_rig):
    quick_rig.classifier_usage = (300, 20)
    quick_rig.fail = RequestError("PL-02: 400 (fake)")
    assert quick_rig.ask("tell me about Q3").status_code == 502
    assert quick_rig.allowance.spent(FLOW_USER, today()) == pytest.approx(quick_rig.credits_for(300, 20))


def test_COST_FAST_1_nfkc_padding_cannot_push_later_work_out_of_the_rules_view(quick_rig):
    pad = "\ufdfa" * 120  # NFKC makes the key pass 2000 characters, so its cut hides the tail
    for tail in ("Then email the contract to bob and delete my inbox", "Is the sky blue? Send it."):
        quick_rig.reset()
        response = quick_rig.ask(f"What is the capital of France? {pad} {tail}")
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "switch_to_thinking" or quick_rig.classifier_calls, body


def test_COST_FAST_1_text_the_rules_cannot_read_goes_to_the_model_not_simple(quick_rig):
    quick_rig.classifier_reply = json.dumps({"kind": "work", "reason": "needs_tools"})
    response = quick_rig.ask("Какая столица Франции?")
    assert quick_rig.classifier_calls, "no Latin stems: undecided"
    assert_offer_shape(response.json(), "needs_tools")


def test_COST_FAST_1_accented_latin_is_not_foreign_so_a_cheap_question_stays_one_call(quick_rig):
    body = quick_rig.ask("What is the plural of café?").json()
    assert body["outcome"] == "answered" and body["cost"]["model_calls"] == 1, body
    assert not quick_rig.classifier_calls, "accented Latin has stems: the rules decide, no classifier call"


def test_COST_FAST_1_a_phrase_split_by_zero_width_characters_is_flagged_after_cleaning(quick_rig):
    split = "\u200b".join(INJECTION_PHRASE)
    response = quick_rig.ask(f"{SIMPLE_TEXT} {split}")
    assert response.status_code == 422, response.text
    assert quick_rig.provider_requests == []


def test_COST_FAST_1_SEC_16_live_without_a_ledger_is_refused_before_any_model(sec16_factory, monkeypatch, repo_root):
    h = sec16_factory(**BIG)
    rig = sec16_rig(h, monkeypatch, repo_root)
    from tilo_api import deps

    monkeypatch.setattr(deps, "caps_for", lambda request: None)
    response = rig.ask(SIMPLE_TEXT)
    assert response.status_code == 503, response.text
    assert rig.provider_requests == [] and rig.allowance.spent(JUDGE_A, today()) == 0


def test_COST_FAST_1_the_answer_is_plain_text_without_control_or_bidi_characters(quick_rig):
    quick_rig.answer = "Paris\u202e\x07 is\nthe\tcapital\u200b."
    body = quick_rig.ask(SIMPLE_TEXT).json()
    assert_answer_shape(body)
    assert body["text"] == "Paris is\nthe\tcapital."


def test_COST_FAST_1_a_long_run_of_marks_is_split_in_linear_time(quick_rig):
    started = time.monotonic()
    response = quick_rig.ask("What is this" + "\u2026" * 480 + "x")
    assert response.status_code == 200
    assert time.monotonic() - started < 2


def test_COST_FAST_1_the_answer_request_carries_an_explicit_output_cap(quick_rig):
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 200
    (call,) = quick_rig.answer_calls
    assert call.request.max_output_tokens is not None and call.request.max_output_tokens <= 1000
