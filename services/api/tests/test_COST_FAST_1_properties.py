"""COST-FAST-1 property tests: invariants that hold for any text, any chosen mode and any model reply.

* Quick never creates a task, world, artifact, policy or event, never calls the Director, and its response is exactly
  the answer shape or the offer shape (or a 422); a model reply of any shape cannot make it anything else.
* Thinking chosen is never Quick-shaped, whatever was typed: the classifier only suggests.
* A verdict is deterministic: the same text, mode and scripted model give the same outcome and reason.
* The cost of a Quick answer never exceeds half a credit.
* Flagged text, anywhere in the text and in any case, reaches no model in either mode.

Hypothesis, derandomised and bounded, over the same fakes as the example tests. No network, no paid call.
"""

from __future__ import annotations

import json

from _api_contracts_lib import INJECTION_PHRASE
from _costfast1_lib import ANSWER_KEYS, OFFER_KEYS, assert_answer_shape, assert_offer_shape
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SIMPLE_FRAGMENTS = [
    "What is the capital of France?",
    "Why is the sky blue?",
    "Convert 5 miles to kilometres.",
    "hmm",
    "thoughts on the numbers?",
]
WORK_FRAGMENTS = [
    "Send an email to the supplier.",
    "Create a 12-slide presentation.",
    "Search the web and compare the results.",
    "First gather the data, then compare it, then rank it.",
    "Delete the old files.",
    "Book a flight.",
]
VERDICTS = [
    json.dumps({"kind": "simple"}),
    json.dumps({"kind": "work", "reason": "needs_tools"}),
    json.dumps({"kind": "work", "reason": "nonsense"}),
    json.dumps({"kind": "simple", "extra": 1}),
    '{"kind": "simple", "kind": "work"}',
    "not json at all",
    "",
]
texts = st.one_of(
    st.sampled_from(SIMPLE_FRAGMENTS + WORK_FRAGMENTS),
    st.lists(st.sampled_from(SIMPLE_FRAGMENTS + WORK_FRAGMENTS), min_size=1, max_size=4).map(" ".join),
    st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=700),
)
bounded = settings(
    max_examples=25, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck), print_blob=False
)


@bounded
@given(text=texts, verdict=st.sampled_from(VERDICTS))
def test_COST_FAST_1_property_quick_is_always_a_typed_answer_or_offer_and_creates_nothing(quick_rig, text, verdict):
    quick_rig.reset()
    quick_rig.classifier_reply = verdict
    before = quick_rig.stored()

    response = quick_rig.ask(text, mode="quick")
    again = quick_rig.ask(text, mode="quick")

    assert response.status_code in (200, 422), response.text
    assert quick_rig.stored() == before, "Quick stores nothing"
    assert "director" not in quick_rig.roles and not any(c.is_approaches for c in quick_rig.calls)
    assert all(c.role == "assistant" for c in quick_rig.calls)
    assert (again.status_code, again.json().get("outcome"), again.json().get("reason")) == (
        response.status_code,
        response.json().get("outcome"),
        response.json().get("reason"),
    ), "the same text gets the same verdict"
    if response.status_code == 200:
        body = response.json()
        assert set(body) in (ANSWER_KEYS, OFFER_KEYS), sorted(body)
        if body["outcome"] == "answered":
            assert_answer_shape(body)
            assert 0 < body["cost"]["credits"] <= 0.5
            assert body["cost"]["model_calls"] >= 1
        else:
            assert_offer_shape(body)
    else:
        assert quick_rig.calls == [], "a refusal asks no model"


@bounded
@given(text=texts)
def test_COST_FAST_1_property_thinking_chosen_is_never_quick_shaped(quick_rig, text):
    quick_rig.reset()

    response = quick_rig.ask(text, mode="thinking")

    assert response.status_code in (201, 422), response.text
    body = response.json()
    if response.status_code == 201:
        assert body["mode"] == "thinking" and "outcome" not in body and body["task_id"]
        assert "assistant" not in quick_rig.roles
    else:
        assert "outcome" not in body


@bounded
@given(
    before=st.text(max_size=80),
    after=st.text(max_size=80),
    mode=st.sampled_from(["quick", "thinking", None]),
    case=st.sampled_from(["upper", "lower", "title"]),
)
def test_COST_FAST_1_property_flagged_text_reaches_no_model_in_either_mode(quick_rig, before, after, mode, case):
    quick_rig.reset()
    phrase = getattr(INJECTION_PHRASE, case)()

    response = quick_rig.ask(f"{before} {phrase} {after}", mode=mode)

    assert response.status_code == 422, response.text
    assert quick_rig.calls == [] and quick_rig.provider_requests == []
