"""COST-FAST-1 (requirement 1): `POST /intake` carries the person's chosen mode, `quick` or `thinking`.

User decision, 8 Oct 2026: the person picks the mode on the website. "Thinking" is the full Director flow exactly as
today (FR-INT-06: approaches are not skipped for work). The field is an optional multipart form field `mode`; absent it
means `thinking`, so nothing existing changes. An unknown value is a 422 like a bad `scenario` (FR-INT-11) and
stores and asks nothing. Shapes: `API_COST_FAST_1.md`. Written from the ticket before any builder touches it:
tests/COST-FAST-1.
"""

from __future__ import annotations

import pytest
from _costfast1_lib import SIMPLE_TEXT

WORK_TEXT = "Prepare the weekly supplier summary."
TODAYS_KEYS = {"task_id", "world_id", "run_id", "brief", "questions", "files", "gaps", "scenario"}


def test_COST_FAST_1_no_mode_means_thinking_and_the_response_is_todays_plus_the_mode(quick_rig):
    response = quick_rig.ask(WORK_TEXT, mode=None)

    assert response.status_code == 201, response.text
    body = response.json()
    assert TODAYS_KEYS <= set(body), sorted(TODAYS_KEYS - set(body))
    assert body["mode"] == "thinking"
    assert quick_rig.roles == ["director"], "the Director drafts the brief; nothing else is asked"


def test_COST_FAST_1_explicit_thinking_is_the_same_flow_and_approaches_are_not_skipped(quick_rig):
    """FR-INT-06: work gets 2 to 3 approaches. Thinking chosen explicitly changes nothing about that."""
    response = quick_rig.ask(WORK_TEXT, mode="thinking")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "thinking" and TODAYS_KEYS <= set(body)
    approaches = quick_rig.flow.approaches(body["task_id"])
    assert approaches.status_code == 200, approaches.text
    assert 2 <= len(approaches.json()["approaches"]) <= 3
    assert any(c.is_approaches for c in quick_rig.calls), "the approaches call was made"
    assert "assistant" not in quick_rig.roles


def test_COST_FAST_1_thinking_chosen_runs_thinking_even_for_a_trivial_question(quick_rig):
    """The classifier only suggests: a person who chose Thinking gets Thinking, whatever they typed."""
    response = quick_rig.ask(SIMPLE_TEXT, mode="thinking")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "thinking" and body["task_id"]
    assert "outcome" not in body, "never the Quick answer or the switch offer"
    assert quick_rig.roles == ["director"] and "assistant" not in quick_rig.roles
    assert quick_rig.stored()["tasks"] == 1


@pytest.mark.parametrize(
    "value",
    [
        "fast",
        "Quick",
        "QUICK",
        " quick",
        "quick ",
        "Thinking",
        "",
        "quick,thinking",
        "think",
        "thinking\x00",
        "0",
        "<script>alert(1)</script>",
        "q" * 5000,
    ],
)
def test_COST_FAST_1_an_unknown_mode_is_a_422_that_stores_and_asks_nothing(quick_rig, value):
    response = quick_rig.ask(WORK_TEXT, mode=value)

    assert response.status_code == 422, response.text
    body = response.json()
    assert type(body["error"]) is str and body["error"].strip()
    assert "<script>" not in response.text and "q" * 50 not in response.text, "the value is never echoed"
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_two_mode_fields_are_refused_not_resolved_silently(quick_rig):
    """The person's choice is never silently overridden, so an ambiguous one is refused."""
    response = quick_rig.ask(WORK_TEXT, mode="quick", extra=[("mode", "thinking")])

    assert response.status_code == 422, response.text
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_the_mode_is_read_from_the_form_only(quick_rig):
    """A query string cannot choose the mode: with no form field the request is Thinking, as today."""
    response = quick_rig.ask(WORK_TEXT, mode=None, params={"mode": "quick"})

    assert response.status_code == 201, response.text
    assert response.json()["mode"] == "thinking"
    assert quick_rig.roles == ["director"]


def test_COST_FAST_1_a_bad_scenario_is_still_a_422_in_either_mode(quick_rig):
    for mode in ("quick", "thinking"):
        response = quick_rig.ask(WORK_TEXT, mode=mode, scenario="no-such-scenario")
        assert response.status_code == 422, (mode, response.text)
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_the_assistant_role_is_the_cheap_capped_tier_in_config(quick_rig):
    """Quick runs on the existing `assistant` role (config/models.yaml): the lite tier, at most 8k in / 1k out."""
    roles = quick_rig.providers.roles
    assistant, director = roles["assistant"], roles["director"]
    assert assistant.max_input_tokens is not None and assistant.max_input_tokens <= 8000
    assert assistant.max_output_tokens is not None and assistant.max_output_tokens <= 1000
    cheap, dear = quick_rig.providers.price(assistant.primary), quick_rig.providers.price(director.primary)
    assert cheap.input < dear.input and cheap.output < dear.output
    assert assistant.thinking in (None, "minimal", "low")
