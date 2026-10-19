"""P0-RUNS-FIX: a must-ask reply whose labels or reason run long is the model's real question, so it is clipped to the
card's limits instead of thrown away; a reply that is still the wrong shape becomes "no question" in assume mode and
the unit goes on (live runs logged `ask reply has the wrong shape` on every web unit)."""

from __future__ import annotations

import asyncio
import json

from agt_must_ask_support import make_must_ask, unit_for
from agt_scripted import ScriptedProvider
from tilo_harness.must_ask import Assumption

LONG = {
    "ask": True,
    "reason": "ambiguous_brief",
    "question": "Which meaning of asura should the search cover?",
    "options": ["Hindu and Buddhist mythology", "The video game Asura's Wrath"],
    "suggested": 0,
    "why": "The word has several meanings. " * 10,
}


def _assess(tmp_path, reply, mode="assume"):
    specialist = ScriptedProvider(default=json.dumps(reply))
    must_ask, cards, _ = make_must_ask(tmp_path, specialist, model_questions=mode)
    return asyncio.run(must_ask.assess(unit_for({"title": "Search for asura", "actions": []}))), cards


def test_P0_RUNS_FIX_long_labels_are_clipped_not_rejected(tmp_path) -> None:
    result, cards = _assess(tmp_path, LONG)
    assert isinstance(result, Assumption) and result.reason == "ambiguous_brief"
    assert result.assumed.startswith("Hindu and Buddhist")
    assert cards == []


def test_P0_RUNS_FIX_a_long_label_question_in_ask_mode_fits_the_card(tmp_path) -> None:
    result, _ = _assess(tmp_path, LONG, mode="ask")
    assert result is not None and not isinstance(result, Assumption)
    assert all(1 <= len(option) <= 20 for option in result.options) and len(result.why) <= 200


def test_P0_RUNS_FIX_a_wrong_shape_reply_is_no_question_in_assume_mode(tmp_path) -> None:
    result, cards = _assess(tmp_path, {**LONG, "options": ["only one"], "suggested": 3})
    assert isinstance(result, Assumption) and result.reason == "no_question"
    assert cards == []
