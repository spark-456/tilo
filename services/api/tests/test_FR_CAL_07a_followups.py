"""FR-CAL-07 part (a) review follow-ups: label cleaning, ASCII-only digits, the released item behind the oracle, and
another person's item with the same source ref. Same rig as test_FR_CAL_07a_prepare.py."""

from __future__ import annotations

from _fr_cal_07a_lib import (
    cal_plate,
    cal_world,
    entry,
    expected_prepare,
    ist,
    linked_sam,
    quiet_decider,
    shape_of,
    stored,
    which_entry,
)
from _ppl11b_lib import PRIYA, SAM, hist, maker, run_answer, stamp, work_item
from tilo_api.assistant.gate import RefGate

QUESTION = "What should I prepare for the 5pm?"


def _ask(world, plate, question):
    return run_answer(world, plate, question, decider=quiet_decider())


def test_FR_CAL_07_prepare_labels_drop_line_separators_and_bidi_overrides():
    title = "Plan" + chr(0x2028) + "ning" + chr(0x202E) + "gnp"
    rec = entry("ce_ctl1", title, ist(17), ist(18))
    world = cal_world([rec])
    answer = _ask(world, cal_plate([rec]), QUESTION)
    assert answer.lines[1].text == "Planninggnp" + " at 17:00 to 18:00"
    assert not {chr(0x2028), chr(0x202E)} & set(" ".join(ln.text for ln in answer.lines))


def test_FR_CAL_07_prepare_reads_ascii_digits_only():
    world = cal_world(keep_plan=True)
    answer = _ask(world, cal_plate([stored(world, "ce_plan1")]), "What should I prepare for the " + chr(0x663) + "pm?")
    assert shape_of(answer) == which_entry()


def test_FR_CAL_07_prepare_does_not_name_an_item_the_oracle_refuses(monkeypatch):
    world, rec, meeting, item = linked_sam()
    real = RefGate.record
    monkeypatch.setattr(RefGate, "record", lambda self, ref: None if ref.kind == "work_item" else real(self, ref))
    answer = _ask(world, cal_plate([rec]), QUESTION)
    assert shape_of(answer) == expected_prepare(rec, meeting=meeting)


def test_FR_CAL_07_prepare_ignores_another_persons_item_with_the_same_source_ref():
    world, rec, meeting, item = linked_sam()
    other = work_item("wi_other1", PRIYA, "Priya copy of the item", due="2026-10-09")
    other.update(
        created_by=maker("A_notes", "tilo"),
        assigned_by=stamp(PRIYA),
        confirmed_by=stamp(PRIYA, "2026-10-02T09:00:00.000Z"),
        source={"kind": "meeting", "ref": "mt_samsync1#ai1", "evidence": ["u0004"]},
        history=[hist("A_notes", "created", "proposed"), hist(PRIYA, "confirmed", "open", "2026-10-02T09:00:00.000Z")],
    )
    world.stores.work_items.create(other)
    answer = _ask(world, cal_plate([rec]), QUESTION)
    assert shape_of(answer) == expected_prepare(rec, meeting=meeting, item=item)
    assert SAM and "Priya copy" not in " ".join(ln.text for ln in answer.lines)
