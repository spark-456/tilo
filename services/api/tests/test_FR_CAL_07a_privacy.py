"""FR-CAL-07 part (a), privacy, cost and bounds of the two calendar answers (API_FR_CAL_07a.md sections 5 and 6): every
record the panel names passes the PPL-10 oracle as the signed-in person; another person's entry, title or meeting
never appears and never changes the answer; no model call, no write, no new event type; hostile or oversized text is
read once and bounded.

Written before any implementation: every test here first needs the new `calendar_prepare` answer, which does not
exist today, so each fails today. The whole file is a strict xfail until the builder deletes
`test_FR_CAL_07a_privacy` from `SLICE_PENDING` in `_fr_cal_07a_lib.py`; to see the real failures run it with
`--runxfail`.
"""

from __future__ import annotations

import json
import sys
import time

from _fr_cal_07a_lib import (
    cal_plate,
    cal_world,
    entry,
    expected_prepare,
    ist,
    linked_priya,
    navigate_entry,
    quiet_decider,
    shape_of,
    shape_of_body,
    stored,
    which_entry,
)
from _ppl11b_lib import (
    DECLINES,
    FAKE_KEY,
    NOW,
    ORG,
    SAM,
    UNMATCHED,
    AccessSpy,
    ScriptedDecider,
    assert_body_shape,
    assert_events_valid,
    assert_no_leak,
    mod,
    model_decision,
    run_answer,
    strip_volatile,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)

ZEROS = {"model_calls": 0, "credits": 0.0, "saved_credits": 0.0}
QUESTION = "What should I prepare for the 5pm?"


def test_FR_CAL_07_route_prepare_answers_with_the_documented_body_and_the_two_existing_events(rig_factory):
    world, rec, item = linked_priya()
    rig = rig_factory(world=world, plates={SAM: cal_plate([rec])}, decider=quiet_decider())
    before = world.snapshot()
    first = rig.ask(QUESTION)
    assert first.status_code == 200
    body = first.json()
    assert_body_shape(body)
    assert shape_of_body(body) == expected_prepare(rec, item=item)
    assert (body["outcome"], body["decided_by"], body["cached"], body["ui_action"]) == (
        "answered",
        "rules",
        False,
        navigate_entry("ce_rel1"),
    )
    assert body["sources"] == [{"kind": "calendar_entry", "id": "ce_rel1"}, {"kind": "work_item", "id": "wi_released"}]
    assert body["cost"] == ZEROS
    evs = rig.events()
    assert [e["type"] for e in evs] == ["assistant.asked", "assistant.replied"], (
        "no new event type (registry unchanged)"
    )
    assert_events_valid(evs)
    assert evs[1]["data"]["sources"] == body["sources"] and evs[1]["data"]["ui_action"] == body["ui_action"]
    assert evs[1]["summary"] == "The assistant answered from 2 records." and evs[1]["credits"] == 0
    assert rig.decider.calls == 0 and rig.now_calls == 1 and rig.plate_source.calls == [(SAM, NOW)]
    again = rig.ask(QUESTION)
    assert strip_volatile(again.json()) == strip_volatile(body) and again.json()["cost"] == ZEROS, (
        "rules are not cached"
    )
    assert world.snapshot() == before, "the panel writes no people record"
    assert not [c for c in world.calls_after_setup() if c[1] in ("create", "replace", "delete")]


def test_FR_CAL_07_route_prepare_works_in_replay_only_mode_with_no_model(rig_factory):
    rig = rig_factory(
        world=cal_world(keep_plan=True),
        decider=ScriptedDecider(model_decision("intent", intent="calendar_prepare", credits=0.5)),
    )
    rig.flags.set("replay_only", True, reason="NFR-24 test")
    body = rig.ask("What should I prepare for the 3pm?").json()
    assert (body["outcome"], body["decided_by"]) == ("answered", "rules")
    assert body["ui_action"] == navigate_entry("ce_plan1") and rig.decider.calls == 0
    assert rig.ask(UNMATCHED).json()["text"] == DECLINES["rules_only"]


def test_FR_CAL_07_other_peoples_entries_never_reach_the_answer_nor_change_it(rig_factory, monkeypatch):
    """Priya's entry shared with Sam's team is readable by Sam (team calendar, PE-04) and a buggy plate names it and her
    private one. Whether they exist, or sit at the same minute as Sam's, changes nothing in Sam's answer."""
    rec = entry("ce_mine1", "Design review", ist(17, 30), ist(18, 30))
    answers = {}
    for name, drop in (("with", False), ("without", True)):
        world = cal_world([rec])
        theirs = [stored(world, "ce_priya_shared"), stored(world, "ce_priya_private")]
        assert theirs[0]["start"] == rec["start"], "fixture: Priya's shared entry starts at Sam's minute (17:30 IST)"
        plate = cal_plate([rec, *theirs])
        if drop:
            for cid in ("ce_priya_shared", "ce_priya_private"):
                world.stores.calendar.delete(ORG, cid, expected_version=1)
        spy = AccessSpy(monkeypatch)
        rig = rig_factory(world=world, plates={SAM: plate}, decider=quiet_decider())
        mine = rig.ask("What should I prepare for the 5:30pm?")
        nobody = rig.ask("What should I prepare for the 1:30pm?")  # Priya's private one is at 13:30 IST
        answers[name] = (strip_volatile(mine.json()), strip_volatile(nobody.json()))
        assert shape_of_body(mine.json()) == expected_prepare(stored(world, "ce_mine1")), name
        assert shape_of_body(nobody.json(), "which_entry") == which_entry(), name
        assert {r.actor for r in spy.all_requests()} == {SAM}, "every oracle request is made as the signed-in person"
        assert {r.action for r in spy.all_requests()} == {"read_full"}
        assert_no_leak(rig.surfaces(mine), ["PRIYA-PRIVATE", "ce_priya"], where=name)
        assert rig.plate_source.calls and {user for user, _ in rig.plate_source.calls} == {SAM}
    assert answers["with"] == answers["without"], "the reply never depends on whether someone else's record exists"


def test_FR_CAL_07_route_a_meeting_the_person_cannot_read_leaks_nowhere(rig_factory):
    world, rec, item = linked_priya()
    plate = cal_plate([rec, stored(world, "ce_priya_shared"), stored(world, "ce_priya_private")])
    rig = rig_factory(world=world, plates={SAM: plate}, decider=quiet_decider())
    response = rig.ask(QUESTION)
    assert shape_of_body(response.json()) == expected_prepare(rec, item=item)
    assert_no_leak(rig.surfaces(response), world.sentinels, where="prepare")
    assert_no_leak({"logs": rig.logs()}, ["Released action item", "Follow-up slot", "Budget"], where="logs")


def test_FR_CAL_07_route_titles_stay_out_of_events_and_logs_and_secrets_are_redacted_in_the_archive(rig_factory):
    title = "Token " + FAKE_KEY
    rec = entry("ce_sec1", title, ist(17), ist(18))
    world = cal_world([rec])
    rig = rig_factory(world=world, plates={SAM: cal_plate([rec])})
    response = rig.ask("ECHO-7f3a " + QUESTION)
    body = response.json()
    assert shape_of_body(body)["lines"][1] == (f"{title} at 17:00 to 18:00", ("calendar_entry", "ce_sec1"))
    surfaces = rig.surfaces(response, archive=False)
    surfaces.pop("body")
    assert_no_leak(surfaces, [FAKE_KEY, title, "ECHO-7f3a"], where="prepare")
    assert "ECHO-7f3a" not in body["text"], "the answer never echoes the question"
    archive = json.dumps(rig.archive_records(), sort_keys=True)
    assert "sk-" not in archive and "[REDACTED]" in archive, "the raw archive keeps the answer text, redacted (PE-16)"


def _count_keys(monkeypatch):
    mod("tilo_api.assistant.core")
    calls = [0]
    for name, module in list(sys.modules.items()):
        if name.startswith("tilo_api.assistant") and hasattr(module, "question_key"):
            real = module.question_key

            def spy(text, _real=real):
                calls[0] += 1
                return _real(text)

            monkeypatch.setattr(module, "question_key", spy)
    return calls


def test_FR_CAL_07_cost_hostile_and_oversized_text_costs_no_more_than_a_plain_question(monkeypatch):
    """NFKC amplification (one character that expands 18 times), a flood of times, 150 entries with such titles: the
    question is normalised once, titles at most once each, and the answer comes back in bounded time (pattern of
    FR_PA_10_cost)."""
    fdfa = chr(0xFDFA)
    recs = [entry(f"ce_c{n:03d}", fdfa * 140, ist(n // 12, (n % 12) * 5)) for n in range(150)]  # 00:00 to 12:25
    world = cal_world(recs)
    plate = cal_plate(recs)
    plain = run_answer(world, plate, "What should I prepare for the 9:00am?", decider=quiet_decider())
    assert shape_of(plain) == expected_prepare(stored(world, "ce_c108"))
    calls = _count_keys(monkeypatch)
    hostile = [
        "What should I prepare for the 9:00am " + fdfa * 1900,
        "prepare " + "3pm " * 450,
        "prepare " + " ".join(f"{1 + n % 12}:{(n * 7) % 60:02d}pm" for n in range(250)),
        "prepare " + "in " * 600,
    ]
    for question in hostile:
        calls[0] = 0
        decider = quiet_decider()
        started = time.monotonic()
        answer = run_answer(world, plate, question, decider=decider)
        assert time.monotonic() - started < 10, question[:30]
        assert decider.calls == 0 and answer.outcome in ("answered", "declined"), question[:30]
        assert calls[0] <= 1 + len(recs), f"normalised {calls[0]} times: {question[:30]!r}"
        assert answer.ui_action is None or answer.ui_action["target"]["id"].startswith("ce_c")


def test_FR_CAL_07_a_model_is_never_asked_what_it_cannot_decide_and_never_sees_a_title(rig_factory):
    """A question the rules read costs no model call. A question they do not read reaches the model with the menu of
    the person's own plate rows only; the calendar entries it sees are the ones the gate admits."""
    world, rec, item = linked_priya()
    private = stored(world, "ce_priya_private")
    plate = cal_plate([rec, private])
    decider = ScriptedDecider(model_decision("intent", intent="calendar_prepare", credits=0.1))
    rig = rig_factory(world=world, plates={SAM: plate}, decider=decider)
    body = rig.ask("Help me get ready for the 5pm").json()
    assert (body["outcome"], body["decided_by"]) == ("answered", "model")
    assert shape_of_body(body) == expected_prepare(rec, item=item)
    assert body["cost"]["model_calls"] == 1
    assert (
        decider.asks
        and "PRIYA-PRIVATE" not in repr(decider.asks[0].menu)
        and "ce_priya" not in repr(decider.asks[0].menu)
    )
