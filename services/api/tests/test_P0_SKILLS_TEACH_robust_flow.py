"""P0-SKILLS-TEACH: teaching Tilo by words (and by a recording) never ends on an error page.

A model reply is tidied (a long or multi-line step is cut, a missing verb defaulted, a question with the wrong number
of options dropped) instead of refused; a reply the Router cannot take, or none, gives an editable draft built by code
from the person's own words (`fallback: true`, 201/200). Fakes only: a scripted provider, no network, no paid call.
"""

from __future__ import annotations

import json

import pytest
from _skills4_lib import CLEAR, ORG, plan, steps
from tilo_api import skills_reply

MONDAY = "Every Monday, read my unread Gmail, summarise it and draft replies."


# --- skills_reply: pure functions ----------------------------------------------------------------------------------


def test_P0_SKILLS_TEACH_parse_json_takes_a_fence_or_words_around_the_object():
    assert skills_reply.parse_json('```json\n{"steps": []}\n```') == {"steps": []}
    assert skills_reply.parse_json('Here you go: {"steps": [1]} Hope that helps') == {"steps": [1]}
    with pytest.raises(ValueError):
        skills_reply.parse_json("no object here")


def test_P0_SKILLS_TEACH_tidy_capture_reads_strings_cuts_long_lines_and_caps_the_count():
    reply = {"steps": ["1. Read the mail", {"step": "Summarise\nit"}, "x" * 400, *[f"Step {n}" for n in range(20)]]}
    texts = [s["text"] for s in skills_reply.tidy_capture(reply)["steps"]]
    assert texts[:2] == ["Read the mail", "Summarise it"] and len(texts) == 12
    assert all(len(t) <= 200 and "\n" not in t for t in texts)
    assert skills_reply.tidy_capture({"nothing": 1}) == {"steps": []}


def test_P0_SKILLS_TEACH_tidy_version_defaults_a_verb_and_drops_a_question_that_is_not_one():
    reply = {
        "steps": [{"text": "Read mail", "tool": "gmail", "action": "read_email"}, {"text": "Write up"}],
        "question": {"text": "Which?", "options": ["only one"]},
        "extra": "ignored",
    }
    out = skills_reply.tidy_version(reply)
    assert out == {
        "steps": [
            {"text": "Read mail", "tool": "gmail", "action": "read_email", "verb": "read"},
            {"text": "Write up", "tool": "none", "action": "none", "verb": "draft"},
        ],
        "question": None,
    }


def test_P0_SKILLS_TEACH_split_steps_makes_steps_from_one_sentence_a_list_or_nothing():
    assert skills_reply.split_steps(MONDAY) == ["read my unread Gmail", "summarise it", "draft replies"]
    assert skills_reply.split_steps("1. Open the sheet\n2) Total the column\n- Email me the total") == [
        "Open the sheet",
        "Total the column",
        "Email me the total",
    ]
    assert skills_reply.split_steps("", example=True) == [skills_reply.NO_EXAMPLE_WORDS]
    assert skills_reply.split_steps("") == []


# --- the routes -----------------------------------------------------------------------------------------------------


def test_P0_SKILLS_TEACH_a_long_multiline_or_oversized_reply_is_tidied_not_refused(skills4):
    rows = [*[f"Step number {n}" for n in range(13)]]
    rows[2] = "A very long step " + "word " * 80
    rows[3] = "Two\nlines"
    skills4.model.override["capture"] = json.dumps({"steps": steps(*rows)})
    response = skills4.capture(CLEAR)
    assert response.status_code == 201, response.text
    body = response.json()
    assert "fallback" not in body and len(body["captured_steps"]) == 12
    assert all(len(s["text"]) <= 200 and "\n" not in s["text"] for s in body["captured_steps"])


def test_P0_SKILLS_TEACH_two_steps_are_a_draft_too(skills4):
    skills4.model.override["capture"] = json.dumps({"steps": steps("Read the mail", "Summarise it")})
    response = skills4.capture(CLEAR)
    assert response.status_code == 201 and len(response.json()["captured_steps"]) == 2


def test_P0_SKILLS_TEACH_words_become_numbered_steps_bound_to_the_tools_they_name_when_the_model_fails(skills4):
    """The model is down for both calls: the person still gets reviewable steps (Gmail read, then text steps)."""
    skills4.model.override["capture"] = RuntimeError("down")
    skills4.model.override["version"] = RuntimeError("down")
    captured = skills4.capture(MONDAY)
    assert captured.status_code == 201 and captured.json()["fallback"] is True
    texts = [s["text"] for s in captured.json()["captured_steps"]]
    assert len(texts) >= 3 and any("Gmail" in t for t in texts)
    version = skills4.version(captured.json()["capture_id"])
    assert version.status_code == 200, version.text
    body = version.json()
    assert body["fallback"] is True and len(body["plan_steps"]) == len(texts)
    pairs = {(s["tool"], s["action"]) for s in body["plan_steps"]}
    assert ("gmail", "search_email") in pairs and ("writer", "compose") in pairs
    assert not any(s["action"] in ("send_email", "create_draft") for s in body["plan_steps"])
    assert skills4.store.get(ORG, body["capture_id"])["plan"] != []


def test_P0_SKILLS_TEACH_a_step_for_a_tool_that_cannot_be_used_is_listed_and_the_rest_stays_reviewable(skills4):
    capture_id = skills4.made(CLEAR)
    skills4.model.override["version"] = json.dumps(
        {"steps": plan(("Post it", "slack", "post_message", "post")), "question": None}
    )
    response = skills4.version(capture_id)
    body = response.json()
    assert response.status_code == 200 and body["plan_steps"]
    assert [c["text"] for c in body["cannot"]] == ["Post it"]


def test_P0_SKILLS_TEACH_a_step_the_person_wrote_is_kept_word_for_word_in_the_draft(skills4):
    skills4.model.override["capture"] = RuntimeError("down")
    captured = skills4.capture("Open the Q3 sheet\nTotal the revenue column\nEmail me the total")
    assert [s["text"] for s in captured.json()["captured_steps"]] == [
        "Open the Q3 sheet",
        "Total the revenue column",
        "Email me the total",
    ]
    assert captured.json()["fallback"] is True
