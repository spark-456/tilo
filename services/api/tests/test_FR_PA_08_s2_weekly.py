"""FR-PA-08 slice 2, the weekly summary (API_FR_PA_08.md sections 1, 2, 4, 5): a fixed template of counts for the
signed-in person, from the same gated plate rows plus the person's own finished work items of the last 7 local days.
Counts only: no title, no free text, no model. The finished items are read through
`people.work_items.list(org, "owner", user)` and each is gated by the PPL-10 oracle as the person, so another
person's items, another org's items and unreadable records are never counted. Tested through the route only (how the
finished items reach the answer is the builder's choice, spec section 4).

Written before any implementation: every test here fails today because no `weekly` intent exists. The whole file is a
strict xfail until the builder deletes `test_FR_PA_08_s2_` from `SLICE_PENDING` in `_fr_pa_08_lib.py`; to see the real
failures run it with `--runxfail`.
"""

from __future__ import annotations

import json

import pytest
from _fr_pa_08_lib import (
    IST,
    NEW_YORK,
    TEXT,
    WEEKLY_QUESTIONS,
    day_start,
    done_in_week,
    done_item,
    expected_weekly,
    fixtures_five,
    hostile_titles,
    instant,
    shift,
    stamp_of,
    week_world,
)
from _ppl11b_lib import (
    C_CONSENT,
    DECLINES,
    NOW,
    OTHER_ORG,
    PRIYA,
    PRIYA_TITLES,
    SAM,
    UNMATCHED,
    W_LAUNCH,
    AccessSpy,
    DirectorySpy,
    ScriptedDecider,
    assert_body_shape,
    assert_events_valid,
    assert_no_leak,
    body_lines,
    hist,
    make_plate,
    model_decision,
    plate_row,
    plate_s0,
    plate_s1,
    work_item,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

IN_WINDOW = "2026-10-06T09:00:00.000Z"
START = day_start(NOW, IST, 6)  # 2026-09-29T18:30:00Z: 00:00 on 30 Sep in Kolkata, six local days before 6 Oct


def week_records() -> list[dict]:
    """Eleven stored work items; exactly four (a, b, e, f) were last marked done inside the window and are Sam's own."""
    reopened = work_item("wi_wk_h", SAM, "Reopened later")
    reopened["history"] = [
        hist(SAM, "created", "open"),
        hist(SAM, "done", "done", IN_WINDOW),
        hist(SAM, "reopened", "open", NOW),
    ]
    dropped = work_item("wi_wk_i", SAM, "Dropped later", status="dropped")
    dropped["history"] = [
        hist(SAM, "created", "open"),
        hist(SAM, "done", "done", IN_WINDOW),
        hist(SAM, "dropped", "dropped", NOW),
    ]
    twice = done_item("wi_wk_e", SAM, "Done twice", "2026-10-04T09:00:00.000Z")
    twice["history"] = [
        hist(SAM, "created", "open"),
        hist(SAM, "done", "done", "2026-10-02T09:00:00.000Z"),
        hist(SAM, "reopened", "open", "2026-10-03T09:00:00.000Z"),
        hist(SAM, "done", "done", "2026-10-04T09:00:00.000Z"),
    ]
    edited_after = done_item("wi_wk_f", SAM, "Edited after done", "2026-10-03T09:00:00.000Z")
    edited_after["history"].append(hist(SAM, "edited", "done", "2026-10-06T09:30:00.000Z"))
    done_long_ago = done_item("wi_wk_g", SAM, "Done long ago", "2026-09-20T09:00:00.000Z")
    done_long_ago["history"].append(hist(SAM, "edited", "done", "2026-10-05T09:00:00.000Z"))
    return [
        done_item("wi_wk_a", SAM, "Done this morning", IN_WINDOW),
        done_item("wi_wk_b", SAM, "Done at the start of the window", stamp_of(START)),
        done_item("wi_wk_c", SAM, "Done a millisecond too early", shift(START, milliseconds=-1)),
        done_item("wi_wk_d", SAM, "Done a millisecond after now", "2026-10-06T10:00:00.001Z"),
        twice,
        edited_after,
        done_long_ago,
        reopened,
        dropped,
        done_item("wi_wk_j", PRIYA, PRIYA_TITLES["wi_priya_1"], IN_WINDOW),
        done_item("wi_wk_k", SAM, "OTHER-ORG-SECRET week", IN_WINDOW, org=OTHER_ORG),
    ]


def _rig(rig_factory, *, records=None, plate=None, now=NOW, zone=None, **kw):
    world = week_world(week_records() if records is None else records, zone=zone)
    return rig_factory(world=world, plates={SAM: plate if plate is not None else plate_s1()}, now=now, **kw)


S1_WEEK_LITERAL = [
    (TEXT["week_header"], None),
    ("Done in the last 7 days: 4", ("work_item", "wi_wk_a")),
    ("Open work items: 4", ("work_item", "wi_budget_notes")),
    ("Overdue: 2", ("pinboard_item", "pb_vendor_review")),
    ("Tasks in progress: 2", ("world", W_LAUNCH)),
    ("Waiting for you: 4", ("card", C_CONSENT)),
]


# --------------------------------------------------------------------------------------------- the template
def test_FR_PA_08_weekly_exact_lines_on_the_s1_fixture(rig_factory):
    """Worked by hand. Done: a, b, e (last done 4 Oct) and f (done 3 Oct, edited later) are in the window; c is a
    millisecond early, d a millisecond after now, g was done on 20 Sep, h was reopened, i dropped, j is Priya's, k is
    another org's. Plate S1: 4 open work items, 2 overdue rows, 2 worlds (one blocked), 4 cards waiting. Each count
    cites the first row of its category in plate order; `Done` cites the latest finished item."""
    rig = _rig(rig_factory)
    response = rig.ask("Weekly summary")
    assert response.status_code == 200
    body = response.json()
    assert_body_shape(body)
    assert (body["outcome"], body["decided_by"], body["ui_action"]) == ("answered", "rules", None)
    assert body_lines(body) == S1_WEEK_LITERAL
    assert len(done_in_week(week_records(), SAM, NOW, IST)) == 4, "the test's own oracle agrees with the hand count"


@pytest.mark.parametrize("name", list(fixtures_five()))
def test_FR_PA_08_weekly_equals_the_counts_of_the_plate_and_the_items_on_5_fixtures(rig_factory, name):
    plate = fixtures_five()[name]
    rig = _rig(rig_factory, plate=plate)
    body = rig.ask("Weekly summary").json()
    done = done_in_week(week_records(), SAM, NOW, IST)
    want = expected_weekly(plate, done)
    assert (body["outcome"], body["decided_by"]) == (want.outcome, "rules")
    assert body_lines(body) == want.lines
    sources = [tuple(s.values()) for s in body["sources"]]
    assert len(sources) == len(set(sources)) <= 6


@pytest.mark.parametrize("question", WEEKLY_QUESTIONS)
def test_FR_PA_08_weekly_phrasings_are_answered_by_rules_with_no_model_call(rig_factory, question):
    rig = _rig(rig_factory, decider=ScriptedDecider())
    body = rig.ask(question).json()
    assert (body["outcome"], body["decided_by"]) == ("answered", "rules"), question
    assert body_lines(body) == S1_WEEK_LITERAL
    assert rig.decider.calls == 0 and body["cost"]["model_calls"] == 0


def test_FR_PA_08_weekly_with_nothing_to_report_is_declined_with_the_empty_text(rig_factory):
    rig = _rig(rig_factory, records=[], plate=plate_s0())
    body = rig.ask("Weekly summary").json()
    assert (body["outcome"], body["decided_by"], body["sources"], body["ui_action"]) == ("declined", "rules", [], None)
    assert body_lines(body) == [(TEXT["week_empty"], None)]
    assert_events_valid(rig.events())


def test_FR_PA_08_weekly_with_only_finished_items_shows_zero_counts_that_claim_nothing(rig_factory):
    rig = _rig(rig_factory, records=week_records()[:1], plate=plate_s0())
    body = rig.ask("Weekly summary").json()
    assert body["outcome"] == "answered"
    assert body_lines(body) == [
        (TEXT["week_header"], None),
        ("Done in the last 7 days: 1", ("work_item", "wi_wk_a")),
        ("Open work items: 0", None),
        ("Overdue: 0", None),
        ("Tasks in progress: 0", None),
        ("Waiting for you: 0", None),
    ]
    assert body["sources"] == [{"kind": "work_item", "id": "wi_wk_a"}]


def test_FR_PA_08_weekly_counts_are_not_capped_and_a_tie_cites_the_smallest_id(rig_factory):
    records = [done_item(f"wi_m_{n:02d}", SAM, f"Many {n:02d}", IN_WINDOW) for n in range(60)]
    body = _rig(rig_factory, records=records, plate=plate_s0()).ask("Weekly summary").json()
    assert body_lines(body)[1] == ("Done in the last 7 days: 60", ("work_item", "wi_m_00"))


def test_FR_PA_08_weekly_routes_events_and_the_clock(rig_factory):
    rig = _rig(rig_factory, decider=ScriptedDecider())
    body = rig.ask("Weekly summary").json()
    evs = rig.events()
    assert [e["type"] for e in evs] == ["assistant.asked", "assistant.replied"], (
        "no new event type (registry unchanged)"
    )
    assert_events_valid(evs)
    assert evs[1]["data"]["sources"] == body["sources"] and len(body["sources"]) == 5
    assert evs[1]["summary"] == "The assistant answered from 5 records."
    assert rig.now_calls == 1 and rig.plate_source.calls == [(SAM, NOW)]


def test_FR_PA_08_a_model_may_only_choose_the_weekly_read_model(rig_factory):
    decider = ScriptedDecider(model_decision("intent", intent="weekly", credits=0.1))
    rig = _rig(rig_factory, decider=decider)
    body = rig.ask(UNMATCHED).json()
    assert (body["outcome"], body["decided_by"]) == ("answered", "model")
    assert body_lines(body) == S1_WEEK_LITERAL, "the lines are the template over the counts, never the model's words"
    assert decider.calls == 1


def test_FR_PA_08_weekly_works_in_replay_only_mode_with_no_model(rig_factory):
    rig = _rig(rig_factory, decider=ScriptedDecider(model_decision("intent", intent="plate", credits=0.5)))
    rig.flags.set("replay_only", True, reason="NFR-24 test")
    body = rig.ask("Weekly summary").json()
    assert (body["outcome"], body["decided_by"]) == ("answered", "rules") and rig.decider.calls == 0


# --------------------------------------------------------------------------------------------- the window
def _boundary_case(zone: str, now: str, start: str):
    return pytest.param(zone, now, start, id=f"{zone.replace('/', '-')}-{now[:10]}T{now[11:19]}")


WEEK_WINDOWS = [
    _boundary_case(IST, NOW, "2026-09-29T18:30:00.000Z"),
    _boundary_case(IST, "2026-10-05T18:29:59.000Z", "2026-09-28T18:30:00.000Z"),
    _boundary_case(IST, "2026-10-05T18:30:00.000Z", "2026-09-29T18:30:00.000Z"),
    _boundary_case(NEW_YORK, "2026-11-02T12:00:00.000Z", "2026-10-27T04:00:00.000Z"),
    _boundary_case(NEW_YORK, "2026-11-04T12:00:00.000Z", "2026-10-29T04:00:00.000Z"),
    _boundary_case(NEW_YORK, "2026-03-09T12:00:00.000Z", "2026-03-03T05:00:00.000Z"),
    _boundary_case("UTC", NOW, "2026-09-30T00:00:00.000Z"),
]


@pytest.mark.parametrize(("zone", "now", "start"), WEEK_WINDOWS)
def test_FR_PA_08_the_last_7_days_are_seven_local_days_ending_now_inclusive(rig_factory, zone, now, start):
    opened = day_start(now, zone, 6)
    assert stamp_of(opened) == start, "the test's own oracle agrees with the hand-worked instant"
    inside = [start, shift(opened, days=3), now]
    outside = [shift(opened, milliseconds=-1), shift(instant(now), milliseconds=1)]
    records = [done_item(f"wi_b_{n}", SAM, f"Probe {n}", at) for n, at in enumerate(inside + outside)]
    rig = _rig(rig_factory, records=records, plate=plate_s0(), now=now, zone=zone)
    body = rig.ask("Weekly summary").json()
    assert body_lines(body)[1][0] == "Done in the last 7 days: 3", f"{zone} at {now}: start-1ms and now+1ms are out"


_ZONES_NOWS = [
    (IST, NOW),
    (NEW_YORK, "2026-11-02T12:00:00.000Z"),
    (NEW_YORK, "2026-03-09T12:00:00.000Z"),
    ("Pacific/Auckland", NOW),
]


@st.composite
def _finished(draw):
    zone, now = draw(st.sampled_from(_ZONES_NOWS))
    items = draw(
        st.lists(
            st.tuples(
                st.integers(-180, 180),  # minutes around the window start, or around now
                st.booleans(),  # near the start (True) or near now (False)
                st.sampled_from(["done", "reopened", "dropped"]),
                st.sampled_from([SAM, SAM, SAM, PRIYA]),
            ),
            max_size=8,
        )
    )
    return zone, now, items


@settings(
    max_examples=20,
    deadline=None,
    phases=[Phase.explicit, Phase.generate],
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(case=_finished())
def test_FR_PA_08_property_the_done_count_is_the_oracle_for_any_stamps_zones_and_states(rig_factory, case):
    zone, now, items = case
    records = []
    for n, (minutes, near_start, state, owner) in enumerate(items):
        base = day_start(now, zone, 6) if near_start else instant(now)
        at = shift(base, minutes=minutes)
        rec = done_item(f"wi_p_{n}", owner, f"Item {n}", at)
        if state != "done":
            rec["status"] = "open" if state == "reopened" else "dropped"
            rec["history"].append(hist(owner, state, rec["status"], at))
        records.append(rec)
    rig = _rig(rig_factory, records=records, plate=plate_s0(), now=now, zone=zone)
    body = rig.ask("Weekly summary").json()
    want = expected_weekly(plate_s0(), done_in_week(records, SAM, now, zone))
    assert (body["outcome"], body_lines(body)) == (want.outcome, want.lines)


# --------------------------------------------------------------------------------------------- privacy and honesty
def test_FR_PA_08_weekly_counts_only_the_signed_in_persons_items_through_the_oracle(rig_factory, monkeypatch):
    spy, dirs = AccessSpy(monkeypatch), DirectorySpy(monkeypatch)
    rig = _rig(rig_factory)
    rig.plate_source.plates[PRIYA] = make_plate(PRIYA, [])
    response = rig.ask("Weekly summary")
    body = response.json()
    assert body_lines(body)[1][0] == "Done in the last 7 days: 4", "not Priya's, not another org's"
    assert {r.actor for r in spy.all_requests()} == {SAM} and {r.action for r in spy.all_requests()} == {"read_full"}
    assert not {"wi_wk_j", "wi_wk_k"} & spy.record_ids(), "another person's or org's item never reaches the oracle"
    lists = [e for e in rig.world.log if e[:2] == ("work_item", "list")]
    assert len(lists) == 1, "the owner index is read once per request"
    assert dirs.calls == 1, "one directory per request, never per item"
    assert rig.plate_source.calls == [(SAM, NOW)]
    assert_no_leak(rig.surfaces(response), [*rig.world.sentinels, "wi_wk_j", "wi_wk_k"], where="weekly")


def test_FR_PA_08_weekly_names_no_title_anywhere_and_a_hostile_title_changes_nothing(rig_factory):
    titles = hostile_titles()
    records = [done_item(f"wi_h_{n:02d}", SAM, t, IN_WINDOW) for n, t in enumerate(titles)]
    rig = _rig(rig_factory, records=records, plate=plate_s0())
    response = rig.ask("Weekly summary")
    body = response.json()
    assert body_lines(body)[:2] == [
        (TEXT["week_header"], None),
        (f"Done in the last 7 days: {len(titles)}", ("work_item", "wi_h_00")),
    ]
    assert len(body["lines"]) == 6, "counts only: the header and five fixed lines"
    for text in (response.text, json.dumps(rig.events()), json.dumps(rig.archive_records()), rig.logs()):
        for title in titles:
            assert title not in text or len(title) < 6


def test_FR_PA_08_weekly_marks_plate_counts_as_at_least_when_the_plate_is_truncated(rig_factory):
    items = [work_item(f"wi_t_{n:03d}", SAM, f"Backlog {n:03d}") for n in range(200)]
    rows = [
        plate_row("work_item", wi["id"], "work_item", "rest", wi["title"], at=f"2026-10-0{1 + n % 5}T09:00:00.000Z")
        for n, wi in enumerate(items)
    ]
    plate = make_plate(SAM, rows)
    plate["truncated"] = True  # the schema asks for a full lane (200 rows), which this is
    rig = _rig(rig_factory, records=items, plate=plate)
    body = rig.ask("Weekly summary").json()
    want = expected_weekly(plate, [])
    assert body_lines(body) == want.lines
    assert [ln[0] for ln in body_lines(body)[1:]] == [
        "Done in the last 7 days: 0",
        "Open work items: 200+",
        "Overdue: 0+",
        "Tasks in progress: 0+",
        "Waiting for you: 0+",
    ]


def test_FR_PA_08_a_failing_item_store_is_a_failed_answer_never_a_partial_summary(rig_factory, monkeypatch):
    rig = _rig(rig_factory)

    def down(*args, **kwargs):
        raise RuntimeError("item store unavailable (test double)")

    monkeypatch.setattr(rig.world.spied.work_items, "list", down)
    response = rig.ask("Weekly summary")
    assert response.status_code == 200
    body = response.json()
    assert (body["outcome"], body["decided_by"], body["sources"]) == ("failed", "rules", [])
    assert body["text"] == DECLINES["failed"] and TEXT["week_header"] not in response.text
    replied = rig.events()[-1]
    assert replied["type"] == "assistant.replied" and replied["data"]["outcome"] == "failed"
    assert "RuntimeError" in rig.logs() and "item store unavailable" not in rig.logs(), "the log names the type only"
