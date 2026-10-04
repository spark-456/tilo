"""FR-AGT-05 (PRD 8.3): the must-ask rules are enforced by deterministic code, not by the model's
good will. A model that says "no question needed" cannot suppress a rule that fires:

- the step touches outside communication, sharing or deletion (an action above T1 in
  config/autonomy.yaml, or an action type the table does not list, which is T3, BQ-44) and no
  autonomy policy covers it: reason sensitive_step (BQ-198);
- a unit has failed `retries.max_attempts` (3) times: reason repeated_failure, no model call needed;
- a reply the harness cannot read is treated as "ask", never as "clear" (BQ-199).

Clear and covered work, and a unit that has failed fewer than 3 times, raise nothing.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from agt_must_ask_support import REASONS, make_must_ask, tasks_of, unit_for
from agt_scripted import ScriptedProvider
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

CLEAR = json.dumps({"ask": False})
TITLE = "Process the attached order list"


def _unit(actions=(), title=TITLE):
    return unit_for({"title": title, "actions": list(actions)})


def _assess(tmp_path, reply, unit, *, failures=0, covered=(), **config):
    specialist = ScriptedProvider(default=reply)
    must_ask, _cards, _providers = make_must_ask(tmp_path, specialist, covered_actions=covered, **config)
    ask = asyncio.run(must_ask.assess(unit, failures=failures))
    return ask, specialist


@pytest.mark.parametrize("action", ["send_email", "post_status_update", "share_file", "delete_file", "wire_money"])
def test_FR_AGT_05_an_uncovered_action_above_t1_asks_even_when_the_model_says_clear(tmp_path, action) -> None:
    ask, _ = _assess(tmp_path, CLEAR, _unit([action]))
    assert ask is not None, f"FR-AGT-05: {action} (outside communication or sharing, no policy) must raise a question"
    assert ask.reason == "sensitive_step"
    assert ask.question


@pytest.mark.parametrize("action", ["create_draft", "save_file", "grant_budget"])
def test_FR_AGT_05_a_t1_action_with_a_clear_reply_raises_no_question(tmp_path, action) -> None:
    ask, _ = _assess(tmp_path, CLEAR, _unit([action]))
    assert ask is None, f"{action} is T1 in config/autonomy.yaml: nothing outside Tilo is touched"


@pytest.mark.parametrize("action", ["send_email", "post_status_update"])
def test_FR_AGT_05_a_t2_action_covered_by_an_autonomy_policy_raises_no_question(tmp_path, action) -> None:
    ask, _ = _assess(tmp_path, CLEAR, _unit([action]), covered={action})
    assert ask is None, "PRD 8.3 asks only for outside communication 'not covered by an autonomy policy'"


def test_FR_AGT_05_a_t3_action_is_never_waved_through_by_coverage(tmp_path) -> None:
    ask, _ = _assess(tmp_path, CLEAR, _unit(["share_file"]), covered={"share_file"})
    assert ask is not None and ask.reason == "sensitive_step", "T3 always needs a person (CLAUDE.md hard rules)"


@pytest.mark.parametrize("failures", [0, 1, 2])
def test_FR_AGT_05_a_unit_that_failed_fewer_than_three_times_raises_no_question(tmp_path, failures) -> None:
    ask, _ = _assess(tmp_path, CLEAR, _unit(), failures=failures)
    assert ask is None


@pytest.mark.parametrize("failures", [3, 4, 7])
def test_FR_AGT_05_a_unit_that_failed_three_times_asks_without_asking_the_model(tmp_path, failures) -> None:
    ask, specialist = _assess(tmp_path, CLEAR, _unit(), failures=failures)
    assert ask is not None, "PRD 8.3: 'a unit fails 3 times' is a must-ask"
    assert ask.reason == "repeated_failure"
    assert specialist.call_count == 0, "a deterministic rule needs no model call (EFF: no paid call where code decides)"


def test_FR_AGT_05_the_failure_threshold_follows_config_retries_max_attempts(tmp_path) -> None:
    ask_two, _ = _assess(tmp_path, CLEAR, _unit(), failures=2, retries={"max_attempts": 2})
    ask_one, _ = _assess(tmp_path, CLEAR, _unit(), failures=1, retries={"max_attempts": 2})
    assert ask_two is not None and ask_two.reason == "repeated_failure"
    assert ask_one is None


@pytest.mark.parametrize(
    "reply",
    ["", "not json at all", "[]", '{"ask": "maybe"}', '{"unrelated": 1}', "null", '{"ask": null}'],
    ids=["empty", "prose", "list", "ask_not_bool", "no_ask_key", "null", "ask_null"],
)
def test_FR_AGT_05_an_unreadable_model_reply_asks_instead_of_passing_as_clear(tmp_path, reply) -> None:
    ask, _ = _assess(tmp_path, reply, _unit())
    assert ask is not None, "BQ-199: when the harness cannot tell, it asks; it never proceeds on a guess"
    assert ask.reason == "ambiguous_brief"
    assert ask.question


def test_FR_AGT_05_a_model_ask_raises_a_question_of_its_own_reason(tmp_path) -> None:
    reply = json.dumps(
        {
            "ask": True,
            "reason": "trade_off",
            "question": "Faster means fewer sources. Accept that?",
            "options": ["Fewer sources", "Finish later"],
            "suggested": 1,
            "why": "Evidence stays intact.",
        }
    )
    ask, _ = _assess(tmp_path, reply, _unit())
    assert ask is not None and ask.reason == "trade_off"
    assert "fewer sources" in ask.question.lower()


# --- property: a model can add questions, never remove one a rule requires --------------------

_ACTIONS = [
    "create_draft",
    "save_file",
    "grant_budget",
    "send_email",
    "post_status_update",
    "share_file",
    "delete_file",
    "zz_unlisted",
]
_T1 = {"create_draft", "save_file", "grant_budget"}
_T2 = {"send_email", "post_status_update"}
_REPLIES = st.sampled_from(
    [
        CLEAR,
        "garbage",
        json.dumps(
            {
                "ask": True,
                "reason": "ambiguous_brief",
                "question": "Which one?",
                "options": ["A", "B"],
                "suggested": 0,
                "why": "x",
            }
        ),
        json.dumps(
            {
                "ask": True,
                "reason": "trade_off",
                "question": "Trade?",
                "options": ["A", "B"],
                "suggested": 0,
                "why": "x",
            }
        ),
        json.dumps(
            {
                "ask": True,
                "reason": "sensitive_step",
                "question": "Money?",
                "options": ["A", "B"],
                "suggested": 0,
                "why": "x",
            }
        ),
    ]
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    reply=_REPLIES,
    actions=st.lists(st.sampled_from(_ACTIONS), max_size=4, unique=True),
    covered=st.lists(st.sampled_from(sorted(_T1 | _T2)), max_size=4, unique=True),
    failures=st.integers(min_value=0, max_value=6),
)
def test_FR_AGT_05_property_no_model_reply_can_suppress_a_rule_that_fires(reply, actions, covered, failures) -> None:
    with tempfile.TemporaryDirectory() as folder:
        ask, _ = _assess(Path(folder), reply, _unit(actions), failures=failures, covered=covered)

    uncovered_sensitive = [a for a in actions if a not in _T1 and not (a in _T2 and a in covered)]
    reply_asks = reply != CLEAR  # garbage and every ask:true reply produce a question

    must = failures >= 3 or bool(uncovered_sensitive)
    if must or reply_asks:
        assert ask is not None, f"actions={actions} covered={covered} failures={failures} reply={reply!r}"
    else:
        assert ask is None, f"nothing fired but a question was raised: {ask}"
    if ask is not None:
        assert ask.reason in REASONS


def test_FR_AGT_05_the_recorded_ask_replies_fit_the_card_they_become() -> None:
    """Fixture self-check: each recorded ask reply can become a schema-valid card (2 or 3 options of
    at most 20 characters, a suggested index, a reason of at most 200 characters)."""
    for task in tasks_of("ask"):
        reply = task["model_reply"]
        assert reply["ask"] is True and 2 <= len(reply["options"]) <= 3, task["id"]
        assert all(1 <= len(label) <= 20 for label in reply["options"]), task["id"]
        assert 0 <= reply["suggested"] < len(reply["options"]), task["id"]
        assert reply["reason"] in REASONS and 1 <= len(reply["why"]) <= 200, task["id"]
        assert len(reply["question"]) <= 140, task["id"]
