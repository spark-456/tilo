"""FR-CAL-07 part (a) guards (API_FR_CAL_07a.md sections 2, 6 and 7): behaviour that is true today and must stay true
when the two calendar answers land, and checks that the fixtures and oracles of this ticket match the spec text. This
file is never pending: it passes now and a builder who breaks one of these has broken the panel, not the new feature.
(Nothing here is the new behaviour; see `test_FR_CAL_07a_today.py`, `_prepare.py` and `_privacy.py`.)
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from _fr_cal_07a_lib import (
    TODAY_INTENT,
    cal_plate,
    cal_world,
    entry,
    expected_prepare,
    expected_today,
    ist,
    linked_priya,
    linked_sam,
    quiet_decider,
    shape_of,
    stored,
)
from _fr_pa_08_lib import hostile_titles
from _ppl11b_lib import (
    DECLINES,
    ORG,
    SAM,
    ScriptedDecider,
    make_gate,
    mod,
    model_decision,
    plate_s1,
    principal,
    run_answer,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from tilo_api.assistant.gate import Ref


# --------------------------------------------------------------------------------------------- the fixtures
def test_FR_CAL_07_guard_the_fixtures_are_what_the_oracle_says_they_are():
    plate = plate_s1()
    world = cal_world(keep_plan=True)
    gate = make_gate(world, plate)
    assert ist(15) == "2026-10-06T09:30:00.000Z" == stored(world, "ce_plan1")["start"], "15:00 Kolkata"
    assert ist(17, 30) == "2026-10-06T12:00:00.000Z" == stored(world, "ce_priya_shared")["start"]
    assert gate.allows(Ref("calendar_entry", "ce_priya_shared")), "teammates read a shared entry: owner must be checked"
    assert not gate.allows(Ref("calendar_entry", "ce_priya_private"))
    assert world.stores.calendar.get(ORG, "ce_plan1") is not None
    assert cal_world().stores.calendar.get(ORG, "ce_plan1") is None

    sam, rec, meeting, item = linked_sam()
    gate = make_gate(sam, cal_plate([rec]))
    assert all(
        gate.allows(Ref(kind, rid))
        for kind, rid in (("calendar_entry", "ce_prep1"), ("meeting", "mt_samsync1"), ("work_item", "wi_prep1"))
    )
    priya, rec2, item2 = linked_priya()
    gate = make_gate(priya, cal_plate([rec2]))
    assert gate.allows(Ref("calendar_entry", "ce_rel1")) and gate.allows(Ref("work_item", "wi_released"))
    assert not gate.allows(Ref("meeting", "mt_priya1")), "Sam reads the released item, never Priya's meeting"
    assert meeting["id"] == "mt_samsync1" and item["id"] == "wi_prep1" and item2["owner"] == SAM


def test_FR_CAL_07_guard_a_tilo_entry_is_read_only_while_its_source_meeting_exists():
    """The premise of the fail-closed prepare test: the oracle refuses a Tilo-made entry once its meeting is gone."""
    sync = entry("ce_sync1", "Sync slot", ist(18), None, tilo_ref="mt_samsync1")
    world = cal_world([sync])
    assert make_gate(world, cal_plate([sync])).allows(Ref("calendar_entry", "ce_sync1"))
    world, rec, _ = linked_priya()
    assert make_gate(world, cal_plate([rec])).allows(Ref("calendar_entry", "ce_rel1"))
    world.stores.meetings.delete(ORG, "mt_priya1", expected_version=2)
    assert not make_gate(world, cal_plate([rec])).allows(Ref("calendar_entry", "ce_rel1"))


def test_FR_CAL_07_guard_the_oracles_are_pinned_to_the_spec_text():
    """So a wrong oracle cannot make a wrong builder pass."""
    world = cal_world(keep_plan=True)
    today = expected_today(world, plate_s1())
    assert today["lines"] == [
        ("On your calendar today:", None),
        ("15:00 Team planning", ("calendar_entry", "ce_plan1")),
    ]
    assert today["ui_action"] == {
        "kind": "navigate",
        "route": "calendar",
        "target": {"kind": "calendar_entry", "id": "ce_plan1"},
    }
    plain = expected_prepare(stored(world, "ce_plan1"))
    assert [t for t, _ in plain["lines"]] == [
        "To prepare:",
        "Team planning at 15:00 to 16:00",
        "Nothing else is linked to it.",
    ]
    open_ended = expected_prepare(entry("ce_x1", "Quick call", ist(9, 5), None, attendees=1))
    assert [t for t, _ in open_ended["lines"]] == [
        "To prepare:",
        "Quick call at 09:05",
        "Other attendees: 1",
        "Nothing else is linked to it.",
    ]


# --------------------------------------------------------------------------------------------- calendar_today
def _today(world, plate, question="What is on my calendar today?", **kw):
    decider = quiet_decider()
    answer = run_answer(world, plate, question, decider=decider, **kw)
    assert decider.calls == 0 and answer.model is None
    return answer


def test_FR_CAL_07_guard_several_entries_are_listed_in_start_order_in_the_persons_zone_with_no_offer():
    late = entry("ce_late1", "Late call", ist(18), ist(19))
    early = entry("ce_early1", "Early call", ist(9, 30), ist(10))
    noon = entry("ce_noon1", "Lunch talk", ist(12), ist(13))
    world = cal_world([late, early, noon])
    plate = cal_plate([late, early, noon])
    answer = _today(world, plate)
    assert shape_of(answer) == expected_today(world, plate)
    assert [t for t, _ in shape_of(answer)["lines"]] == [
        "On your calendar today:",
        "09:30 Early call",
        "12:00 Lunch talk",
        "18:00 Late call",
    ]
    assert answer.ui_action is None, "the person picks one; there is nothing to open by itself"
    assert (answer.outcome, answer.intent) == ("answered", TODAY_INTENT)


def test_FR_CAL_07_guard_no_entry_today_is_the_empty_answer_with_no_source():
    world = cal_world()
    answer = _today(world, cal_plate([]))
    assert (answer.outcome, answer.decline, answer.ui_action) == ("declined", "empty", None)
    assert [(ln.text, ln.source) for ln in answer.lines] == [("Nothing is on your calendar today.", None)]


def test_FR_CAL_07_guard_titles_are_data_in_the_today_list():
    titles = hostile_titles()[:9]
    recs = [entry(f"ce_h{n:02d}", t, ist(8 + n), ist(8 + n, 30)) for n, t in enumerate(titles)]
    world = cal_world(recs)
    plate = cal_plate(recs)
    answer = _today(world, plate)
    assert shape_of(answer) == expected_today(world, plate)


def test_FR_CAL_07_guard_a_refused_entry_is_dropped_before_the_answer_is_built():
    world = cal_world(keep_plan=True)
    plate = plate_s1()
    gate_mod = mod("tilo_api.assistant.gate")

    class Refusing(gate_mod.RefGate):
        def allows(self, ref):
            return (ref.kind, ref.id) != ("calendar_entry", "ce_plan1") and super().allows(ref)

    answer = _today(world, plate, gate=make_gate(world, plate, gate_cls=Refusing))
    assert (answer.outcome, answer.decline, answer.ui_action) == ("declined", "empty", None)


def test_FR_CAL_07_guard_the_older_questions_keep_their_intents():
    world = cal_world(keep_plan=True)
    for question, intent in (
        ("What is on my calendar this week?", TODAY_INTENT),
        ("What needs my approval?", "waiting"),
        ("What do I need to do?", "waiting"),
        ("What is due today?", "due_soon"),
        ("What is on my plate?", "plate"),
    ):
        answer = run_answer(world, plate_s1(), question, decider=quiet_decider())
        assert (answer.outcome, answer.decided_by, answer.intent) == ("answered", "rules", intent), question


def test_FR_CAL_07_guard_open_the_3pm_one_is_still_a_question_for_the_model_not_a_prepare_rule():
    """PPL-11b acceptance question 27: no rule reads it (no prepare word), so only the model may decide it."""
    decider = ScriptedDecider(model_decision("decline"))
    answer = run_answer(cal_world(keep_plan=True), plate_s1(), "Open the 3pm one", decider=decider)
    assert decider.calls == 1 and answer.decided_by == "model" and answer.ui_action is None


# --------------------------------------------------------------------------------------------- failure and static
@pytest.mark.parametrize("question", ["What is on my calendar today?", "What should I prepare for the 3pm?"])
def test_FR_CAL_07_guard_a_failing_plate_source_is_a_failed_answer_an_email_principal_403_an_unwired_seam_503(
    rig_factory, question
):
    rig = rig_factory(world=cal_world(keep_plan=True))

    class Down:
        def build(self, user, now):
            raise RuntimeError("plate source down (test double)")

    good = rig.plate_source
    rig.plate_source = Down()
    rig.activate()
    body = rig.ask(question).json()
    assert (body["outcome"], body["decided_by"], body["sources"], body["text"]) == (
        "failed",
        "rules",
        [],
        DECLINES["failed"],
    )
    assert "RuntimeError" in rig.logs() and "plate source down" not in rig.logs()
    rig.plate_source = good
    rig.set_principal(principal(SAM, channel="email"))
    refused = rig.ask(question)
    assert refused.status_code == 403 and refused.json() == {"error": "channel"}
    rig.set_principal(principal(SAM))
    rig.unwire("get_plate_source")
    unwired = rig.ask(question)
    assert unwired.status_code == 503 and unwired.json() == {"detail": "not_configured"}


def test_FR_CAL_07_guard_nothing_in_the_assistant_package_writes_a_people_record():
    """The panel answers and offers; it never creates, replaces or deletes a record (FR-CAL-07 is read-only)."""
    root = pathlib.Path(mod("tilo_api.assistant").__file__).parent
    writes: dict[str, list[str]] = {}
    for path in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver = ast.unparse(node.func.value)  # `datetime.replace(tzinfo=...)` is not a store write
                on_store = any(
                    k in receiver for k in ("calendar", "work_items", "meetings", "persons", "pins", "people")
                )
                if node.func.attr in {"create", "delete", "erase_person", "create_founder"} or (
                    node.func.attr == "replace" and on_store
                ):
                    writes.setdefault(path.name, []).append(node.func.attr)
    assert writes == {}, writes
