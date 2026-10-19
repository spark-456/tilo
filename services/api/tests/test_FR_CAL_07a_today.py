"""FR-CAL-07 part (a), "what is on my calendar today" (API_FR_CAL_07a.md section 2): the panel lists the signed-in
person's own, accepted calendar entries of today in their own time zone, in order, each citing its entry, and opens
the entry when exactly one is listed. Requirement (docs/prd-addendum-people-agents.md, FR-CAL-07): the panel answers
"what is on my calendar today" ... and navigates to the entry.

Written before any implementation. Every test here fails today because the existing `calendar_today` intent lists
proposed entries and entries of other people that the plate carries, and never offers the navigation. The whole file
is a strict xfail until the builder deletes `test_FR_CAL_07a_today` from `SLICE_PENDING` in `_fr_cal_07a_lib.py`; to
see the real failures run it with `--runxfail`.
"""

from __future__ import annotations

import pytest
from _fr_cal_07a_lib import (
    TODAY_INTENT,
    cal_plate,
    cal_world,
    entry,
    expected_today,
    ist,
    navigate_entry,
    quiet_decider,
    shape_of,
    shape_of_body,
    stored,
)
from _ppl11b_lib import (
    NOW,
    SAM,
    assert_body_shape,
    assert_events_valid,
    plate_s1,
    run_answer,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from tilo_policy.schemas import conforms

QUESTIONS = ("What is on my calendar today?", "What's my schedule for today?", "What are my meetings today?")


def _ask(world, plate, question, **kw):
    decider = quiet_decider()
    answer = run_answer(world, plate, question, decider=decider, **kw)
    assert decider.calls == 0 and answer.model is None, "rules answer; no model call (FR-PA-19)"
    assert (answer.decided_by, answer.intent) == ("rules", TODAY_INTENT)
    return answer


@pytest.mark.parametrize("question", QUESTIONS)
def test_FR_CAL_07_one_entry_today_is_listed_and_opened(question):
    """Given exactly one accepted entry today, the answer lists it at its local time and navigates to it."""
    world = cal_world(keep_plan=True)  # ce_plan1: 15:00 to 16:00 IST, "Team planning"
    plate = plate_s1()
    answer = _ask(world, plate, question)
    want = expected_today(world, plate)
    assert shape_of(answer) == want
    assert want["lines"][1] == ("15:00 Team planning", ("calendar_entry", "ce_plan1"))
    assert answer.ui_action == navigate_entry("ce_plan1")
    assert conforms("ui_action.schema.json", answer.ui_action), "the offer is a document of the ui_action allow-list"


def test_FR_CAL_07_the_person_time_zone_decides_the_shown_time_and_the_offer_stays():
    world = cal_world(keep_plan=True)
    answer = _ask(world, plate_s1(), "What is on my calendar today?", tz="America/Los_Angeles")
    assert [t for t, _ in shape_of(answer)["lines"]][1] == "02:30 Team planning"
    assert answer.ui_action == navigate_entry("ce_plan1")


def test_FR_CAL_07_a_proposed_entry_is_never_listed_and_does_not_count_for_the_offer():
    """Given one accepted and one proposed own entry today, only the accepted one is listed, and it is opened."""
    mine = entry("ce_mine1", "Design review", ist(10), ist(11))
    proposed = entry("ce_prop1", "Tilo review slot", ist(16), ist(17), state="proposed", tilo_ref="mt_samsync1")
    world = cal_world([mine, proposed])
    plate = cal_plate([mine, proposed])
    answer = _ask(world, plate, "What is on my calendar today?")
    assert shape_of(answer) == expected_today(world, plate)
    assert [t for t, _ in shape_of(answer)["lines"]] == ["On your calendar today:", "10:00 Design review"]
    assert answer.ui_action == navigate_entry("ce_mine1")


def test_FR_CAL_07_only_a_proposed_entry_today_is_the_empty_answer_with_no_source():
    proposed = entry("ce_prop1", "Tilo review slot", ist(16), ist(17), state="proposed", tilo_ref="mt_samsync1")
    world = cal_world([proposed])
    plate = cal_plate([proposed])
    answer = _ask(world, plate, "What is on my calendar today?")
    assert (answer.outcome, answer.decline, answer.ui_action) == ("declined", "empty", None)
    assert [(ln.text, ln.source) for ln in answer.lines] == [("Nothing is on your calendar today.", None)]


def test_FR_CAL_07_another_persons_entries_are_never_listed_even_when_a_buggy_plate_names_them():
    """Priya's entry shared with Sam's team is readable by Sam through the team calendar (PE-04) but is not on Sam's
    calendar: the panel lists the signed-in person's own entries only."""
    mine = entry("ce_mine1", "Design review", ist(10), ist(11))
    world = cal_world([mine])
    theirs = [stored(world, "ce_priya_shared"), stored(world, "ce_priya_private")]
    plate = cal_plate([mine, *theirs])
    answer = _ask(world, plate, "What is on my calendar today?")
    assert shape_of(answer) == expected_today(world, plate)
    text = " ".join(ln.text for ln in answer.lines)
    assert "PRIYA-PRIVATE" not in text and "ce_priya" not in str(answer.ui_action)
    assert [ln.source.id for ln in answer.lines if ln.source] == ["ce_mine1"]
    assert answer.ui_action == navigate_entry("ce_mine1"), "the shared entry of Priya does not count as a second one"


def test_FR_CAL_07_route_answers_opens_the_entry_and_writes_nothing_else(rig_factory):
    world = cal_world(keep_plan=True)
    rig = rig_factory(world=world, decider=quiet_decider())
    before = world.snapshot()
    response = rig.ask("What is on my calendar today?")
    assert response.status_code == 200
    body = response.json()
    assert_body_shape(body)
    assert shape_of_body(body, None)["lines"][1] == ("15:00 Team planning", ("calendar_entry", "ce_plan1"))
    assert (body["outcome"], body["decided_by"], body["cached"]) == ("answered", "rules", False)
    assert body["ui_action"] == navigate_entry("ce_plan1") and body["sources"][0] == {
        "kind": "calendar_entry",
        "id": "ce_plan1",
    }
    assert body["cost"] == {"model_calls": 0, "credits": 0.0, "saved_credits": 0.0}
    evs = rig.events()
    assert [e["type"] for e in evs] == ["assistant.asked", "assistant.replied"], "no new event type"
    assert_events_valid(evs)
    assert evs[1]["data"]["ui_action"] == navigate_entry("ce_plan1") and evs[1]["data"]["sources"] == body["sources"]
    assert rig.decider.calls == 0 and rig.now_calls == 1 and rig.plate_source.calls == [(SAM, NOW)]
    assert world.snapshot() == before, "the panel writes no people record"
    assert not [c for c in world.calls_after_setup() if c[1] in ("create", "replace", "delete")]
