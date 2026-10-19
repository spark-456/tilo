"""FR-CAL-07 part (a), "what should I prepare for the 3pm" (API_FR_CAL_07a.md sections 3 to 5): a new fact intent
`calendar_prepare` resolves the person's own accepted entry that starts at the named time today (their time zone),
answers a short preparation list from the entry's own fields and from the records linked to it that the person may
read (the oracle, as the principal), and opens the entry. No entry, or more than one, is the `which_entry` decline.
Requirement (docs/prd-addendum-people-agents.md, FR-CAL-07): the panel answers "what should I prepare for the 3pm" and
navigates to the entry; FR-CAL-05 (prep view from records, no model) is the same idea on the calendar screen.

Written before any implementation: every test here fails today because no rule reads these questions. The whole file
is a strict xfail until the builder deletes `test_FR_CAL_07a_prepare` from `SLICE_PENDING` in `_fr_cal_07a_lib.py`; to
see the real failures run it with `--runxfail`.
"""

from __future__ import annotations

import pytest
import yaml
from _fr_cal_07a_lib import (
    NOT_A_TIME,
    PREPARE,
    PREPARE_KEYS,
    PREPARE_QUESTIONS,
    TEXT,
    TIME_FORMS,
    cal_plate,
    cal_world,
    entry,
    expected_prepare,
    ist,
    linked_priya,
    linked_sam,
    navigate_entry,
    quiet_decider,
    shape_of,
    stored,
    which_entry,
)
from _fr_pa_08_lib import hostile_titles
from _ppl11b_lib import (
    ORG,
    REPO_ROOT,
    UNMATCHED,
    ScriptedDecider,
    mod,
    model_decision,
    plate_s1,
    run_answer,
)
from tilo_policy.schemas import conforms

GET_READY = "Help me get ready for the 3pm"  # no rule reads it ("ready" is not a rule word): only a model could


def _ask(world, plate, question, *, decided_by="rules", **kw):
    decider = kw.pop("decider", None) or quiet_decider()
    answer = run_answer(world, plate, question, decider=decider, **kw)
    assert answer.decided_by == decided_by, f"{question!r}: no rule reads it (decided by {answer.decided_by})"
    if decided_by == "rules":
        assert decider.calls == 0 and answer.model is None, "rules answer; no model call (FR-PA-19)"
    return answer


def _declined(answer):
    assert shape_of(answer) == which_entry()
    assert answer.lines[0].source is None and answer.ui_action is None


@pytest.mark.parametrize("question", PREPARE_QUESTIONS)
def test_FR_CAL_07_prepare_the_3pm_resolves_the_entry_lists_its_fields_and_opens_it(question):
    """Given one accepted entry at 15:00 (Asia/Kolkata), the answer is the template over that entry and navigates."""
    world = cal_world(keep_plan=True)  # ce_plan1: "Team planning", 15:00 to 16:00 IST, nothing linked
    answer = _ask(world, plate_s1(), question)
    assert answer.intent == PREPARE
    assert shape_of(answer) == expected_prepare(stored(world, "ce_plan1"))
    assert [ln.text for ln in answer.lines] == [
        "To prepare:",
        "Team planning at 15:00 to 16:00",
        "Nothing else is linked to it.",
    ]
    assert [ln.source for ln in answer.lines][0] is None and answer.lines[1].source.id == "ce_plan1"
    assert answer.ui_action == navigate_entry("ce_plan1")
    assert conforms("ui_action.schema.json", answer.ui_action)


@pytest.mark.parametrize(("phrase", "local"), TIME_FORMS)
def test_FR_CAL_07_prepare_reads_these_forms_of_a_time_of_day(phrase, local):
    hour, minute = (int(x) for x in local.split(":"))
    rec = entry("ce_form1", "Form check", ist(hour, minute))
    other = entry("ce_form2", "Other slot", ist(20, 10), ist(20, 40))  # never the one asked for
    world = cal_world([rec, other])
    answer = _ask(world, cal_plate([rec, other]), f"What should I prepare for the {phrase}?")
    assert shape_of(answer) == expected_prepare(stored(world, "ce_form1")), phrase
    assert answer.lines[1].text == f"Form check at {local}", "an entry with no end shows only its start"


@pytest.mark.parametrize("question", NOT_A_TIME)
def test_FR_CAL_07_prepare_without_a_time_of_day_is_the_which_entry_decline(question):
    world = cal_world(keep_plan=True)
    answer = _ask(world, plate_s1(), question)
    _declined(answer)


def test_FR_CAL_07_prepare_naming_two_times_or_another_day_is_the_which_entry_decline():
    a = entry("ce_a1", "Morning slot", ist(15), ist(16))
    b = entry("ce_b1", "Evening slot", ist(17), ist(18))
    world = cal_world([a, b])
    plate = cal_plate([a, b])
    for question in (
        "What should I prepare for the 3pm and the 5pm?",
        "What should I prepare for the 3pm or the 17:00?",
        "What should I prepare for tomorrow's 3pm?",
        "What should I prepare for the 3pm yesterday?",
    ):
        _declined(_ask(world, plate, question))
    # the same entry named twice is one time, not two
    again = _ask(world, plate, "What should I prepare for the 3pm, I mean the 15:00?")
    assert shape_of(again) == expected_prepare(stored(world, "ce_a1"))


def test_FR_CAL_07_prepare_no_entry_at_that_time_is_the_which_entry_decline():
    world = cal_world(keep_plan=True)
    _declined(_ask(world, plate_s1(), "What should I prepare for the 4pm?"))
    _declined(_ask(world, plate_s1(), "What should I prepare for the 3:01pm?"))  # to the minute


def test_FR_CAL_07_prepare_two_entries_at_that_time_is_the_which_entry_decline():
    a = entry("ce_a1", "First slot", ist(15), ist(16))
    b = entry("ce_b1", "Second slot", ist(15), ist(15, 30))
    world = cal_world([a, b])
    answer = _ask(world, cal_plate([a, b]), "What should I prepare for the 3pm?")
    _declined(answer)
    assert "slot" not in " ".join(ln.text for ln in answer.lines), "no title of the candidates is offered"


def test_FR_CAL_07_prepare_a_proposed_entry_is_not_an_entry_to_prepare_for():
    mine = entry("ce_mine1", "Design review", ist(15), ist(16))
    proposed = entry("ce_prop1", "Tilo review slot", ist(15), ist(16), state="proposed", tilo_ref="mt_samsync1")
    world = cal_world([mine, proposed])
    both = _ask(world, cal_plate([mine, proposed]), "What should I prepare for the 3pm?")
    assert shape_of(both) == expected_prepare(stored(world, "ce_mine1")), "the proposed one does not make it ambiguous"
    only = cal_world([proposed])
    answer = _ask(only, cal_plate([proposed]), "What should I prepare for the 3pm?")
    _declined(answer)
    assert "Tilo review slot" not in " ".join(ln.text for ln in answer.lines)


def test_FR_CAL_07_prepare_means_today_in_the_persons_time_zone():
    tomorrow = entry("ce_tom1", "Tomorrow slot", ist(15, day=1), ist(16, day=1))
    yesterday = entry("ce_yes1", "Yesterday slot", ist(15, day=-1), ist(16, day=-1))
    world = cal_world([tomorrow, yesterday])
    plate = cal_plate([tomorrow, yesterday])
    _declined(_ask(world, plate, "What should I prepare for the 3pm?"))
    midnight = entry("ce_mid1", "Midnight slot", ist(0), ist(1))  # 2026-10-05T18:30Z: still the 6th in Kolkata
    next_midnight = entry("ce_mid2", "Next midnight", ist(0, day=1), ist(1, day=1))  # 2026-10-06T18:30Z: the 7th
    world = cal_world([midnight, next_midnight])
    plate = cal_plate([midnight, next_midnight])
    answer = _ask(world, plate, "What should I prepare for the 12am?")
    assert shape_of(answer) == expected_prepare(stored(world, "ce_mid1"))
    la = _ask(cal_world(keep_plan=True), plate_s1(), "What should I prepare for the 2:30am?", tz="America/Los_Angeles")
    assert la.outcome == "answered"
    assert la.lines[1].text == "Team planning at 02:30 to 03:30", "the clock is the person's own, not the server's"


def test_FR_CAL_07_prepare_lists_attendee_count_and_the_meeting_the_person_owns():
    rec = entry("ce_att1", "Vendor call", ist(17), ist(17, 30), attendees=3)
    sync = entry("ce_sync1", "Sync slot", ist(18), None, tilo_ref="mt_samsync1")
    world = cal_world([rec, sync])
    plate = cal_plate([rec, sync])
    first = _ask(world, plate, "What should I prepare for the 5pm?")
    assert shape_of(first) == expected_prepare(stored(world, "ce_att1"))
    assert [ln.text for ln in first.lines][2] == "Other attendees: 3"
    second = _ask(world, plate, "What should I prepare for the 6pm?")
    meeting = dict(world.stores.meetings.get(ORG, "mt_samsync1").record)
    assert shape_of(second) == expected_prepare(stored(world, "ce_sync1"), meeting=meeting)
    assert [ln.text for ln in second.lines] == ["To prepare:", "Sync slot at 18:00", "Meeting: Sam sync"]
    assert second.lines[2].source.kind == "meeting" and second.lines[2].source.id == "mt_samsync1"


def test_FR_CAL_07_prepare_lists_the_linked_meeting_and_action_item_the_person_may_read():
    world, rec, meeting, item = linked_sam()
    plate = cal_plate([rec])
    answer = _ask(world, plate, "What should I prepare for the 5pm?")
    assert shape_of(answer) == expected_prepare(rec, meeting=meeting, item=item)
    assert [ln.text for ln in answer.lines] == [
        "To prepare:",
        "Budget review at 17:00 to 17:45",
        "Other attendees: 2",
        "Meeting: Sam sync",
        "Action item: Send the budget deck (due 2026-10-09)",
    ]
    assert answer.ui_action == navigate_entry("ce_prep1"), "it opens the entry, not the meeting"
    assert [(s.kind, s.id) for s in (ln.source for ln in answer.lines) if s] == [
        ("calendar_entry", "ce_prep1"),
        ("calendar_entry", "ce_prep1"),
        ("meeting", "mt_samsync1"),
        ("work_item", "wi_prep1"),
    ]


def test_FR_CAL_07_prepare_a_released_item_is_listed_but_the_meeting_the_person_cannot_read_is_not():
    world, rec, item = linked_priya()
    answer = _ask(world, cal_plate([rec]), "What should I prepare for the 5pm?")
    assert shape_of(answer) == expected_prepare(rec, item=item)
    assert [ln.text for ln in answer.lines] == [
        "To prepare:",
        "Follow-up slot at 17:00 to 17:30",
        "Action item: Released action item",
    ]
    text = " ".join(ln.text for ln in answer.lines) + str(answer.ui_action)
    assert "PRIYA-PRIVATE" not in text and "mt_priya1" not in text, "Priya's meeting is not Sam's to read or to name"


def test_FR_CAL_07_prepare_an_entry_whose_source_meeting_is_gone_is_not_read_at_all():
    """Fail closed (PE-19): the oracle refuses a Tilo-made entry whose source meeting is deleted, so the entry is not
    an entry the panel can name; the answer is the same decline as for an unknown time."""
    world, rec, _ = linked_priya()
    world.stores.meetings.delete(ORG, "mt_priya1", expected_version=2)
    answer = _ask(world, cal_plate([rec]), "What should I prepare for the 5pm?")
    _declined(answer)
    assert "Follow-up slot" not in " ".join(ln.text for ln in answer.lines)


def test_FR_CAL_07_prepare_titles_are_data_never_a_template_or_an_instruction():
    titles = hostile_titles()
    slots = [(8 + n // 6, (n % 6) * 10) for n in range(len(titles))]  # 08:00 ... 10:20, one title each
    recs = [entry(f"ce_h{n:02d}", t, ist(h, m), ist(h, m + 5)) for n, (t, (h, m)) in enumerate(zip(titles, slots))]
    world = cal_world(recs)
    plate = cal_plate(recs)
    for n, rec in enumerate(recs):
        h, m = slots[n]
        answer = _ask(world, plate, f"What should I prepare for the {h}:{m:02d}am?")
        assert shape_of(answer) == expected_prepare(stored(world, rec["id"])), titles[n]
        assert answer.lines[1].text.startswith(titles[n]), "the title is substituted verbatim, once"


def test_FR_CAL_07_prepare_can_be_picked_by_a_model_by_id_and_code_does_the_rest():
    """A question no rule reads goes to the model, which may only pick the intent by id (FR-PA-14); the entry and the
    lines still come from code. Without a time in the question the pick is the which_entry decline."""
    world = cal_world(keep_plan=True)
    pick = model_decision("intent", intent=PREPARE, credits=0.1)
    decider = ScriptedDecider(pick)
    answer = _ask(world, plate_s1(), GET_READY, decided_by="model", decider=decider)
    assert decider.calls == 1 and answer.intent == PREPARE
    assert shape_of(answer) == expected_prepare(stored(world, "ce_plan1"))
    decider = ScriptedDecider(model_decision("intent", intent=PREPARE, credits=0.1))
    vague = _ask(world, plate_s1(), UNMATCHED, decided_by="model", decider=decider)
    _declined(vague)


def test_FR_CAL_07_prepare_words_win_over_the_older_intents_and_sit_before_them_in_the_config():
    """ "need" belongs to `waiting` and "calendar" to `calendar_today`; the prepare words must be read first."""
    raw = yaml.safe_load((REPO_ROOT / "config" / "assistant.yaml").read_text(encoding="utf-8"))
    ids = [f["id"] for f in raw["facts"]]
    assert PREPARE in ids and ids.index(PREPARE) < ids.index("waiting") < ids.index("calendar_today")
    intent = next(f for f in raw["facts"] if f["id"] == PREPARE)
    assert intent["when"] == [["prepare", "prep", "preparation"]]
    assert raw["declines"]["which_entry"] == TEXT["which_entry"]
    assert raw["answer"]["prepare"] == {k: TEXT[k] for k in PREPARE_KEYS}
    config = mod("tilo_api.assistant.config").load_assistant_config()  # the strict loader accepts the file
    assert PREPARE in [f.id for f in config.facts] and config.declines["which_entry"] == TEXT["which_entry"]
