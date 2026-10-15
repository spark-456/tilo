"""SKILL-TEACH-422 (FR-SKL-01, FR-SKL-02): the live Studio teach flow answered 422 not_understood on the version call.

The web sends exactly what the route takes (an empty JSON body on POST .../version), so the request was never the
problem: the model's pairs were all outside config/connectors.yaml, and every step was dropped (no invented channel).
These tests pin what makes the flow work for a text-only description: the pair list the model is shown names `tool`
and `action` as separate fields, a pair joined or cased the way a model writes it is read as the listed pair, and a
reply with no listed pair gets one more ask (the same call, told what was wrong) before the 422.
"""

from __future__ import annotations

import json

from _skills4_lib import ORG, plan
from tilo_providers.interfaces import GenerateResponse

FEEDBACK = (
    "Collect this week's customer feedback notes, group them by theme, and write a five-bullet summary "
    "with the top request first."
)
FEEDBACK_STEPS = [
    "Collect this week's customer feedback notes",
    "Group the notes by theme",
    "Write a five-bullet summary with the top request first",
]
GOOD = plan(
    ("Collect this week's customer feedback notes", "google_drive", "list_files", "read"),
    ("Group the notes by theme", "google_drive", "read_file", "read"),
    ("Write the five-bullet summary", "google_drive", "save_file", "write"),
)


def _teach(skills4):
    skills4.model.captures[FEEDBACK] = FEEDBACK_STEPS
    skills4.model.versions[FEEDBACK] = {"steps": GOOD, "question": None}
    return skills4.made(FEEDBACK)


def _replies(skills4, *replies):
    """The version call answers `replies` in order (the last one again after that); the capture call is unchanged."""
    first, queue = skills4.model.generate, list(replies)

    def generate(request):
        if "<<<STEPS" not in request.prompt:
            return first(request)
        skills4.model.calls.append(request)
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        return GenerateResponse(text=json.dumps(text), profile_id=skills4.model.profile_id, usage={})

    skills4.model.generate = generate


def test_FR_SKL_02_SKILL_TEACH_422_the_teach_flow_runs_from_description_to_a_listed_skill(skills4):
    capture_id = _teach(skills4)
    version = skills4.version(capture_id)  # the web sends `{}`; `rig.post` does the same
    assert version.status_code == 200, version.text
    steps = version.json()["plan_steps"]
    assert [s["action"] for s in steps] == ["list_files", "read_file", "save_file"]
    saved = skills4.rig.post(
        "/v1/skills",
        {
            "name": "Weekly feedback summary",
            "scope": {"kind": "just_me", "team": None},
            "trigger": {"kind": "on_demand"},
            "plan_steps": [
                {k: s[k] for k in ("text", "tool", "action", "verb")} | {"ask_first": s["ask_first"]} for s in steps
            ],
            "captured_steps": [{"text": t} for t in FEEDBACK_STEPS],
        },
    )
    assert saved.status_code == 201, saved.text
    listed = skills4.rig.get("/v1/skills").json()["skills"]
    assert [r["name"] for r in listed] == ["Weekly feedback summary"]
    assert skills4.store.get(ORG, capture_id)["status"] == "draft"  # the draft stays; the saved skill is its own row


def test_FR_SKL_02_SKILL_TEACH_422_the_pair_list_names_tool_and_action_as_separate_fields(skills4):
    assert skills4.version(_teach(skills4)).status_code == 200
    system = skills4.model.calls[-1].system
    assert 'tool "gmail", action "read_email"' in system and "gmail.read_email" not in system
    assert "never join" in system.lower()


def test_FR_SKL_02_SKILL_TEACH_422_a_pair_joined_or_cased_as_a_model_writes_it_is_read_as_the_listed_pair(skills4):
    capture_id = _teach(skills4)
    rows = [
        ("Collect the notes", "google_drive.list_files", "list_files", "read"),
        ("Group the notes", "Google Drive", "Read File", "read"),
        ("Write the summary", "google_drive", "google_drive.save_file", "write"),
    ]
    _replies(skills4, {"steps": plan(*rows), "question": None})
    response = skills4.version(capture_id)
    assert response.status_code == 200, response.text
    assert [(s["tool"], s["action"]) for s in response.json()["plan_steps"]] == [
        ("google_drive", "list_files"),
        ("google_drive", "read_file"),
        ("google_drive", "save_file"),
    ]


def test_FR_SKL_02_SKILL_TEACH_422_a_reply_with_no_listed_pair_is_asked_once_more_before_the_422(skills4):
    capture_id = _teach(skills4)
    invented = {"steps": plan(("Group the notes", "analysis", "group_by_theme", "read")), "question": None}
    _replies(skills4, invented, {"steps": GOOD, "question": None})
    calls = len(skills4.model.calls)
    response = skills4.version(capture_id)
    assert response.status_code == 200, response.text
    assert len(response.json()["plan_steps"]) == 3 and len(skills4.model.calls) == calls + 2
    assert "not on the list" in skills4.model.calls[-1].prompt  # the second ask says what was wrong, without echoing it
    assert "group_by_theme" not in skills4.model.calls[-1].prompt
    assert [e["type"] for e in skills4.all_events()].count("skill.version_proposed") == 1

    again = skills4.made(FEEDBACK)
    _replies(skills4, invented)
    refused = skills4.version(again)
    assert refused.status_code == 422 and refused.json() == {"detail": "not_understood"}
    assert [e["type"] for e in skills4.all_events()].count("skill.version_proposed") == 1
