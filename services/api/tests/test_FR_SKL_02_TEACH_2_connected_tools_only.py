"""TEACH-2 / TEACH-PAIRS (FR-SKL-01, FR-SKL-02): the live teach flow bound step 1 of "Weekly feedback summary" to
hubspot · read_hubspot for a person who has not connected HubSpot. The step-writer is told which tools the person can
use (their connected connectors; the Google sign-in tools when nothing is connected), is not shown the others, and a
pair on a tool they have not connected is dropped and asked again once. The scripted model here returns a hubspot pair.
"""

from __future__ import annotations

import json

from _skills4_lib import ORG, plan
from tilo_providers.interfaces import GenerateResponse

FEEDBACK = (
    "Collect this week's customer feedback notes, group them by theme, and write a five-bullet summary "
    "with the top request first."
)
STEPS = ["Collect this week's feedback notes", "Group them by theme", "Write the five-bullet summary"]
HUBSPOT = ("Collect this week's feedback notes", "hubspot", "read_hubspot", "read")
DRIVE_SAVE = ("Write the five-bullet summary", "google_drive", "save_as_google_file", "write")
DRIVE_READ = ("Collect this week's feedback notes", "google_drive", "list_files", "read")


class _Views:
    """The read-only connection seam: `view(user, connector)` -> (state, scopes, connected_at)."""

    def __init__(self, connected: set[str]) -> None:
        self.connected = connected

    def view(self, user_id: str, connector: str):
        return ("connected" if connector in self.connected else None, [], None)


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


def _teach(skills4, connected: set[str] | None = None):
    skills4.model.captures[FEEDBACK] = STEPS
    ov = skills4.rig.app.dependency_overrides
    ov[skills4.rig.deps.get_connection_views] = lambda: _Views(connected or set())
    return skills4.made(FEEDBACK)


def _pairs(response):
    return [(s["tool"], s["action"]) for s in response.json()["plan_steps"]]


def test_FR_SKL_02_TEACH_2_nothing_connected_the_writer_is_shown_only_the_google_sign_in_tools(skills4):
    capture_id = _teach(skills4)
    _replies(skills4, {"steps": plan(DRIVE_READ, DRIVE_SAVE), "question": None})
    assert skills4.version(capture_id).status_code == 200
    system = skills4.model.calls[-1].system
    assert "gmail, google_drive, google_calendar" in system
    assert 'tool "google_drive"' in system and 'tool "hubspot"' not in system and 'tool "slack"' not in system


def test_FR_SKL_02_TEACH_2_a_hubspot_pair_for_a_person_without_hubspot_is_steered_to_the_listed_tool(skills4):
    capture_id = _teach(skills4)
    _replies(
        skills4,
        {"steps": plan(HUBSPOT, DRIVE_SAVE), "question": None},
        {"steps": plan(DRIVE_READ, DRIVE_SAVE), "question": None},
    )
    calls = len(skills4.model.calls)
    response = skills4.version(capture_id)
    assert response.status_code == 200, response.text
    assert _pairs(response) == [("google_drive", "list_files"), ("google_drive", "save_as_google_file")]
    assert len(skills4.model.calls) == calls + 2  # the existing one retry, no more
    assert "hubspot" not in json.dumps(response.json())
    assert "gmail, google_drive, google_calendar" in skills4.model.calls[-1].prompt  # the retry names the tools too


def test_FR_SKL_02_TEACH_2_a_hubspot_only_reply_twice_is_the_422_not_a_hubspot_step(skills4):
    capture_id = _teach(skills4)
    _replies(skills4, {"steps": plan(HUBSPOT), "question": None})
    response = skills4.version(capture_id)
    assert response.status_code == 422 and response.json() == {"detail": "not_understood"}
    assert skills4.store.get(ORG, capture_id)["plan"] == []


def test_FR_SKL_02_TEACH_2_a_connected_hubspot_is_offered_and_kept(skills4):
    capture_id = _teach(skills4, {"hubspot"})
    _replies(skills4, {"steps": plan(HUBSPOT, DRIVE_SAVE), "question": None})
    calls = len(skills4.model.calls)
    response = skills4.version(capture_id)
    assert response.status_code == 200, response.text
    assert _pairs(response) == [("hubspot", "read_hubspot"), ("google_drive", "save_as_google_file")]
    assert len(skills4.model.calls) == calls + 1  # nothing was dropped, so no second ask
    system = skills4.model.calls[-1].system
    assert (
        "gmail, google_drive, google_calendar, hubspot" in system and 'tool "hubspot", action "read_hubspot"' in system
    )


def test_FR_SKL_02_TEACH_2_a_views_seam_that_fails_counts_as_nothing_connected(skills4):
    capture_id = _teach(skills4)

    class Down:
        def view(self, *_):
            raise RuntimeError("down")

    skills4.rig.app.dependency_overrides[skills4.rig.deps.get_connection_views] = lambda: Down()
    _replies(skills4, {"steps": plan(DRIVE_READ, DRIVE_SAVE), "question": None})
    assert skills4.version(capture_id).status_code == 200
    assert 'tool "hubspot"' not in skills4.model.calls[-1].system
