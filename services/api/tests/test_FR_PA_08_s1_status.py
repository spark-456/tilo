"""FR-PA-08 slice 1, STATUS (API_FR_PA_08.md sections 1 to 3, 5): one line per running task and one per item changed
since yesterday, from the signed-in person's own plate (rows and the `done` lane of `parked`), as a template with the
sources cited. "Yesterday" is the start of the previous local day in the person's own time zone, against the request's
clock. Acceptance (PRD addendum FR-PA-08): equals world and item state on 5 fixtures.

Written before any implementation: every test here fails today because the question is answered by an older intent
(`tasks` or `changed`) and not by the `status` intent. The whole file is a strict xfail until the builder deletes
`test_FR_PA_08_s1_` from `SLICE_PENDING` in `_fr_pa_08_lib.py`; to see the real failures run it with `--runxfail`.
"""

from __future__ import annotations

import copy
import json

import pytest
from _fr_pa_08_lib import (
    CAP,
    IST,
    NEW_YORK,
    STATUS_QUESTIONS,
    TEXT,
    add_task_worlds,
    day_start,
    done_row,
    expected_status,
    fixtures_five,
    hostile_titles,
    instant,
    key_of,
    set_zone,
    shift,
    stamp_of,
    with_parked,
)
from _ppl11b_lib import (
    ANSWER,
    C_GATE,
    C_MINUTES,
    C_QUESTION,
    DECLINES,
    FAKE_KEY,
    MAIL_ID,
    NOW,
    ORG,
    PRIYA,
    PRIYA_TITLES,
    SAM,
    UNMATCHED,
    W_LAUNCH,
    W_PRIYA,
    W_VENDOR,
    AccessSpy,
    ScriptedDecider,
    assert_body_shape,
    assert_events_valid,
    assert_no_leak,
    body_lines,
    build_world,
    lines_of,
    make_plate,
    model_decision,
    plate_buggy,
    plate_row,
    plate_s0,
    plate_s1,
    principal,
    run_answer,
    s1_rows,
    sources_of,
    strip_volatile,
    ulid,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from _ppl11b_lib import world as world  # noqa: PLC0414  (the fixture)
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from tilo_api import deps

FIVE = fixtures_five()
S1_LITERAL = [
    (TEXT["tasks_header"], None),
    ("Launch site refresh: blocked", ("world", W_LAUNCH)),
    ("Vendor onboarding: running", ("world", W_VENDOR)),
    (TEXT["changed_header"], None),
    ("Send the quote to Acme?: waiting for your approval", ("card", C_GATE)),
    ("Share the budget notes (due 2026-10-04)", ("work_item", "wi_budget_notes")),
    ("Weekly sync minutes: minutes to confirm", ("card", C_MINUTES)),
    ("Which logo for the deck?: waiting for your answer", ("card", C_QUESTION)),
    ("Mail that needs your reply", ("mail", MAIL_ID)),
]


def _rows_and_parked(plate):
    return [*plate["rows"], *plate["parked"]]


def _probe(at: str):
    """A plate whose only row is a card created at `at`: listed as changed exactly when `at` is in the window."""
    return make_plate(SAM, [plate_row("card", ulid(77), "gate", "attention", "Probe card", at=at)])


def _lists_probe(answer) -> bool:
    return ("card", ulid(77)) in sources_of(answer)


# --------------------------------------------------------------------------------------------- the acceptance fixtures
@pytest.mark.parametrize("name", list(FIVE))
def test_FR_PA_08_status_equals_world_and_item_state_on_5_fixtures(world, name):
    plate = FIVE[name]
    decider = ScriptedDecider()
    answer = run_answer(world, plate, "Status", decider=decider)
    want = expected_status(plate)
    assert (answer.outcome, answer.decided_by, answer.intent, answer.decline) == (
        want.outcome,
        "rules",
        "status",
        want.decline,
    )
    assert lines_of(answer) == want.lines
    assert answer.ui_action == want.ui_action
    sources = sources_of(answer)
    assert len(sources) == len(set(sources)) <= 20, "one line per record: no ref twice, at most 20 sources"
    assert set(sources) <= {key_of(r) for r in _rows_and_parked(plate)}, (
        "every source is a record of the person's plate"
    )
    assert decider.calls == 0 and answer.model is None, "STATUS is answered by rules (FR-PA-19)"


def test_FR_PA_08_status_exact_lines_on_the_s1_fixture(world):
    """Pins the oracle to the spec text, worked by hand from the S1 plate at NOW in Asia/Kolkata: since yesterday is
    2026-10-04T18:30Z, a work item created 2026-10-04T09:00Z (14:30 local, two days ago) is out, one created
    2026-10-05T12:00Z is in, a calendar entry is never a change and the two worlds are listed once, as tasks."""
    answer = run_answer(world, plate_s1(), "Give me a status update")
    assert (answer.outcome, answer.intent) == ("answered", "status")
    assert lines_of(answer) == S1_LITERAL
    assert answer.ui_action is None
    assert expected_status(plate_s1()).lines == S1_LITERAL


def test_FR_PA_08_a_done_item_is_listed_from_the_parked_lane_even_when_flagged(world):
    plate = FIVE["mixed_with_done"]
    answer = run_answer(world, plate, "Status")
    assert lines_of(answer)[-2:] == [
        ("Tidy shelf 01: done", ("work_item", "wi_s2_01")),
        ("Tidy shelf 02: done" + ANSWER["flagged_suffix"], ("work_item", "wi_s2_02")),
    ], "PE-27: every `done` row was finished in the last 24 hours, so it is a change since yesterday"


@pytest.mark.parametrize("question", STATUS_QUESTIONS)
def test_FR_PA_08_status_phrasings_are_answered_by_rules_with_no_model_call(world, question):
    decider = ScriptedDecider()
    answer = run_answer(world, plate_s1(), question, decider=decider)
    assert (answer.outcome, answer.decided_by, answer.intent) == ("answered", "rules", "status"), question
    assert lines_of(answer) == S1_LITERAL
    assert decider.calls == 0


@pytest.mark.parametrize("question", STATUS_QUESTIONS)
def test_FR_PA_08_nothing_running_and_nothing_changed_is_declined_with_the_empty_text(world, question):
    answer = run_answer(world, plate_s0(), question, decider=ScriptedDecider())
    assert (answer.outcome, answer.decided_by, answer.decline) == ("declined", "rules", "empty")
    assert lines_of(answer) == [(TEXT["status_empty"], None)]
    assert sources_of(answer) == [] and answer.ui_action is None, "an answer with no source is never `answered` (HR-1)"


def test_FR_PA_08_a_model_may_only_choose_the_status_read_model(world):
    decider = ScriptedDecider(model_decision("intent", intent="status", credits=0.1))
    answer = run_answer(world, plate_s1(), UNMATCHED, decider=decider)
    assert (answer.outcome, answer.decided_by, answer.intent) == ("answered", "model", "status")
    assert lines_of(answer) == S1_LITERAL, "the lines are the template over the rows, never the model's words"
    assert decider.calls == 1


# --------------------------------------------------------------------------------------------- the clock and the zone
WINDOWS = [
    # (zone, now, since): the instant the window opens, worked by hand
    pytest.param(IST, NOW, "2026-10-04T18:30:00.000Z", id="kolkata-midday"),
    pytest.param(IST, "2026-10-05T18:29:59.000Z", "2026-10-03T18:30:00.000Z", id="kolkata-1s-before-midnight"),
    pytest.param(IST, "2026-10-05T18:30:00.000Z", "2026-10-04T18:30:00.000Z", id="kolkata-at-midnight"),
    pytest.param(NEW_YORK, "2026-11-02T12:00:00.000Z", "2026-11-01T04:00:00.000Z", id="new_york-after-fall-back"),
    pytest.param(NEW_YORK, "2026-03-09T12:00:00.000Z", "2026-03-08T05:00:00.000Z", id="new_york-after-spring-forward"),
    pytest.param(None, NOW, "2026-10-05T00:00:00.000Z", id="no-zone-is-utc"),
    pytest.param("Not/AZone", NOW, "2026-10-05T00:00:00.000Z", id="unknown-zone-is-utc"),
]


@pytest.mark.parametrize(("zone", "now", "since"), WINDOWS)
def test_FR_PA_08_since_yesterday_is_the_start_of_the_previous_local_day_inclusive(world, zone, now, since):
    assert day_start(now, zone, 1) == instant(since), "the test's own oracle agrees with the hand-worked instant"
    start = instant(since)
    for at, listed in [
        (shift(start, milliseconds=-1), False),
        (stamp_of(start), True),
        (shift(start, hours=5), True),
        (now, True),
        (shift(instant(now), milliseconds=1), False),
    ]:
        answer = run_answer(world, _probe(at), "Status", tz=zone, now=now)
        assert answer.intent == "status"
        assert _lists_probe(answer) is listed, f"a row at {at} with now {now} in {zone}"


def test_FR_PA_08_the_window_moves_at_local_midnight_not_at_utc_midnight(world):
    probe = _probe("2026-10-04T10:00:00.000Z")  # 15:30 on 4 Oct in Kolkata
    before = run_answer(world, probe, "Status", now="2026-10-05T18:29:59.000Z")  # 23:59:59 on 5 Oct, Kolkata
    after = run_answer(world, probe, "Status", now="2026-10-05T18:30:00.000Z")  # 00:00:00 on 6 Oct, Kolkata
    assert _lists_probe(before) is True and _lists_probe(after) is False


def test_FR_PA_08_the_person_zone_is_read_from_their_own_record(rig_factory):
    """Through the route: the zone is the person's record, the clock is `events.now` read once for the request."""
    world = build_world()
    set_zone(world, SAM, NEW_YORK)
    now = "2026-11-02T12:00:00.000Z"
    plate = make_plate(
        SAM,
        [
            plate_row("card", ulid(78), "gate", "attention", "Just inside", at="2026-11-01T04:00:00.000Z"),
            plate_row("card", ulid(79), "question", "soon", "Just outside", at="2026-11-01T03:59:59.999Z"),
        ],
    )
    rig = rig_factory(world=world, plates={SAM: plate}, now=now)
    body = rig.ask("Status").json()
    assert body["outcome"] == "answered"
    assert body_lines(body) == [
        (TEXT["tasks_header"], None),
        (TEXT["tasks_empty"], None),
        (TEXT["changed_header"], None),
        ("Just inside: waiting for your approval", ("card", ulid(78))),
    ]
    assert rig.now_calls == 1, "the clock is read once per request and passed everywhere"


# --------------------------------------------------------------------------------------------- one line per record
def test_FR_PA_08_an_item_changed_twice_is_one_line(world):
    """The plate holds one row per record: a work item created yesterday and finished today is a single `done` row."""
    plate = with_parked(plate_s0(), [done_row("wi_s2_01", "Tidy shelf 01", at="2026-10-05T12:00:00.000Z")])
    answer = run_answer(world, plate, "Status")
    assert lines_of(answer) == [
        (TEXT["tasks_header"], None),
        (TEXT["tasks_empty"], None),
        (TEXT["changed_header"], None),
        ("Tidy shelf 01: done", ("work_item", "wi_s2_01")),
    ]


def test_FR_PA_08_a_ref_in_both_lanes_or_twice_in_rows_is_listed_once_with_its_rows_copy(world):
    rows = [
        plate_row("work_item", "wi_s2_01", "work_item", "rest", "Tidy shelf 01", at="2026-10-06T08:00:00.000Z"),
        plate_row("work_item", "wi_s2_02", "work_item", "rest", "Tidy shelf 02", at="2026-10-06T07:00:00.000Z"),
    ]
    plate = with_parked(make_plate(SAM, rows), [done_row("wi_s2_01", "Tidy shelf 01", at="2026-10-06T08:00:00.000Z")])
    plate["rows"].append(copy.deepcopy(plate["rows"][0]))  # a builder bug: the same ref twice
    answer = run_answer(world, plate, "Status")
    claims = [ln.text for ln in answer.lines if ln.source is not None]
    assert claims == ["Tidy shelf 02", "Tidy shelf 01"], "first occurrence wins; the rows copy beats the parked copy"
    assert len(sources_of(answer)) == len(claims) == 2


def test_FR_PA_08_a_deleted_item_has_no_line_and_is_logged_as_a_refused_row(world, caplog):
    current = world.stores.work_items.get(ORG, "wi_budget_notes")
    world.stores.work_items.delete(ORG, "wi_budget_notes", expected_version=current.version)
    answer = run_answer(world, plate_s1(), "Status")
    texts = " ".join(ln.text for ln in answer.lines)
    assert "budget notes" not in texts and ("work_item", "wi_budget_notes") not in sources_of(answer)
    assert "assistant.plate_row_refused work_item" in caplog.text
    assert [ln for ln in lines_of(answer) if ln[1] is not None] == [
        ln for ln in S1_LITERAL if ln[1] is not None and ln[1][1] != "wi_budget_notes"
    ]


def test_FR_PA_08_parked_rows_pass_the_same_oracle_gate_as_rows(world, caplog):
    """A builder bug puts Priya's finished item in Sam's `done` lane: it is neither listed nor named anywhere."""
    plate = with_parked(
        plate_s1(),
        [
            done_row("wi_priya_1", PRIYA_TITLES["wi_priya_1"], at=NOW),
            done_row("wi_s2_01", "Tidy shelf 01", at="2026-10-05T09:00:00.000Z"),
        ],
    )
    answer = run_answer(world, plate, "Status")
    assert lines_of(answer) == [*S1_LITERAL, ("Tidy shelf 01: done", ("work_item", "wi_s2_01"))]
    assert "PRIYA" not in " ".join(ln.text for ln in answer.lines) and "wi_priya_1" not in repr(answer)
    assert "assistant.plate_row_refused work_item" in caplog.text
    assert "wi_priya_1" not in caplog.text and "PRIYA" not in caplog.text, "logs carry kinds only"


def test_FR_PA_08_snoozed_and_asked_parked_rows_are_not_changes(world):
    snoozed = plate_row("work_item", "wi_s2_03", "work_item", "snoozed", "Tidy shelf 03", at=NOW)
    asked = plate_row("work_item", "wi_s2_04", "work_item", "asked", "Tidy shelf 04", at=NOW)
    answer = run_answer(world, with_parked(plate_s0(), [snoozed, asked]), "Status")
    assert (answer.outcome, answer.decline) == ("declined", "empty")
    assert lines_of(answer) == [(TEXT["status_empty"], None)]


# --------------------------------------------------------------------------------------------- order and caps
def _capped_plate(world, tasks: int, changed: int):
    ids = add_task_worlds(world, tasks)
    rows = [
        plate_row("world", wid, "run", "rest", f"Task {n:02d}", at=shift(instant(NOW), hours=-n - 1))
        for n, wid in enumerate(ids, start=1)
    ]
    rows += [
        plate_row("card", ulid(200 + n), "question", "soon", f"Question {n:02d}", at=shift(instant(NOW), minutes=-n))
        for n in range(1, changed + 1)
    ]
    return make_plate(SAM, rows)


@pytest.mark.parametrize(
    ("tasks", "changed"), [(0, 0), (1, 0), (0, 1), (1, 1), (10, 10), (11, 3), (3, 11), (12, 25), (0, 25)]
)
def test_FR_PA_08_each_section_is_capped_at_ten_claim_lines_then_one_more_line(world, tasks, changed):
    plate = _capped_plate(world, tasks, changed)
    answer = run_answer(world, plate, "Status")
    want = expected_status(plate)
    assert lines_of(answer) == want.lines and answer.ui_action == want.ui_action
    if tasks or changed:
        claims = [ln for ln in answer.lines if ln.source is not None]
        assert len(claims) == min(tasks, CAP) + min(changed, CAP) and len(sources_of(answer)) <= 20
        cut = tasks > CAP or changed > CAP
        assert (answer.lines[-1].text == ANSWER["more"]) is cut
        assert answer.ui_action == ({"kind": "navigate", "route": "plate", "target": None} if cut else None)


def test_FR_PA_08_tasks_come_first_in_plate_order_then_changed_items_rows_before_done(world):
    answer = run_answer(world, FIVE["mixed_with_done"], "Status")
    heads = [i for i, ln in enumerate(answer.lines) if ln.source is None]
    assert [answer.lines[i].text for i in heads] == [TEXT["tasks_header"], TEXT["changed_header"]]
    kinds = [ln.source.kind for ln in answer.lines if ln.source is not None]
    assert kinds[:2] == ["world", "world"] and kinds[-2:] == ["work_item", "work_item"]


# --------------------------------------------------------------------------------------------- hostile text
@pytest.mark.parametrize("title", hostile_titles())
def test_FR_PA_08_a_hostile_title_is_data_and_never_changes_the_template(world, title):
    rows = [
        plate_row("world", W_LAUNCH, "run", "rest", title, at="2026-10-01T09:00:00.000Z"),
        plate_row("card", ulid(90), "gate", "attention", title, at=NOW),
        plate_row("work_item", "wi_s2_01", "work_item", "rest", title, at=NOW),
    ]
    benign = [dict(r, title="Plain title") for r in rows]
    answer = run_answer(world, make_plate(SAM, rows), "Status")
    plain = run_answer(world, make_plate(SAM, benign), "Status")
    assert lines_of(answer) == expected_status(make_plate(SAM, rows)).lines
    assert [ln.source is None for ln in answer.lines] == [ln.source is None for ln in plain.lines]
    assert [ln.text for ln in answer.lines if ln.source is None] == [ln.text for ln in plain.lines if ln.source is None]
    assert sources_of(answer) == sources_of(plain)
    assert (answer.outcome, answer.intent, answer.ui_action) == (plain.outcome, plain.intent, plain.ui_action)


# --------------------------------------------------------------------------------------------- the invariants
_CATALOGUE = [r for r in s1_rows()] + [
    plate_row("work_item", f"wi_s2_{n:02d}", "work_item", "rest", f"Tidy shelf {n:02d}", at=NOW) for n in range(1, 5)
]
_ZONES = [IST, NEW_YORK, None, "UTC", "Pacific/Auckland", "Not/AZone"]
_NOWS = [
    NOW,
    "2026-10-05T18:29:59.000Z",
    "2026-11-02T12:00:00.000Z",
    "2026-03-09T12:00:00.000Z",
    "2026-11-01T06:30:00.000Z",
]
_TITLES = st.one_of(
    st.sampled_from(hostile_titles()), st.text(alphabet="abc XYZ019$${}%:.<>'", min_size=1, max_size=40)
)


@st.composite
def _plates(draw):
    now = draw(st.sampled_from(_NOWS))
    picks = draw(st.lists(st.integers(0, len(_CATALOGUE) - 1), unique=True, max_size=len(_CATALOGUE)))
    rows, parked = [], []
    for index in picks:
        row = copy.deepcopy(_CATALOGUE[index])
        row["at"] = shift(instant(now), minutes=draw(st.integers(-6000, 120)))
        row["flagged"] = draw(st.booleans())
        if row["ref"]["kind"] != "mail":
            row["title"] = draw(_TITLES)
        if row["ref"]["id"].startswith("wi_s2_") and draw(st.booleans()):
            parked.append(done_row(row["ref"]["id"], row["title"], at=row["at"], flagged=row["flagged"]))
        else:
            rows.append(row)
    return now, draw(st.sampled_from(_ZONES)), with_parked(make_plate(SAM, rows, as_of=now), parked)


@settings(
    max_examples=40,
    deadline=None,
    phases=[Phase.explicit, Phase.generate],  # no shrinking: a failing run stays fast
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(case=_plates())
def test_FR_PA_08_property_status_is_the_oracle_deterministic_capped_and_cites_only_plate_rows(world, case):
    now, zone, plate = case
    first = run_answer(world, plate, "Status", tz=zone, now=now)
    again = run_answer(world, plate, "Status", tz=zone, now=now)
    want = expected_status(plate, now, zone)
    assert (first.outcome, first.decided_by) == (want.outcome, "rules")
    assert lines_of(first) == want.lines == lines_of(again)
    sources = sources_of(first)
    assert len(sources) == len(set(sources)) <= 20
    assert set(sources) <= {key_of(r) for r in _rows_and_parked(plate)}
    assert [ln.text for ln in first.lines if ln.source is None].count(TEXT["tasks_header"]) <= 1


# --------------------------------------------------------------------------------------------- through the route
def test_FR_PA_08_route_status_answers_with_the_documented_body_and_the_two_existing_events(rig_factory):
    rig = rig_factory(decider=ScriptedDecider())
    response = rig.ask("Status")
    assert response.status_code == 200
    body = response.json()
    assert_body_shape(body)
    assert (body["outcome"], body["decided_by"], body["cached"], body["ui_action"]) == (
        "answered",
        "rules",
        False,
        None,
    )
    assert body_lines(body) == S1_LITERAL and len(body["sources"]) == 7
    assert body["cost"] == {"model_calls": 0, "credits": 0.0, "saved_credits": 0.0}
    evs = rig.events()
    assert [e["type"] for e in evs] == ["assistant.asked", "assistant.replied"], (
        "no new event type (registry unchanged)"
    )
    assert_events_valid(evs)
    assert evs[1]["data"]["sources"] == body["sources"] and evs[1]["data"]["outcome"] == "answered"
    assert evs[1]["summary"] == "The assistant answered from 7 records."
    assert rig.decider.calls == 0 and rig.now_calls == 1
    assert rig.plate_source.calls == [(SAM, NOW)]


def test_FR_PA_08_route_the_injected_clock_decides_what_changed_since_yesterday(rig_factory):
    rig = rig_factory()
    today = rig.ask("Status").json()
    rig.now = "2026-10-07T10:00:00.000Z"  # a day later: only what is newer than 2026-10-05T18:30Z stays
    later = rig.ask("Status").json()
    assert body_lines(today) == expected_status(plate_s1(), NOW).lines
    assert body_lines(later) == expected_status(plate_s1(), rig.now).lines
    assert body_lines(today) != body_lines(later)


def test_FR_PA_08_route_other_people_and_buggy_plates_never_reach_the_answer(rig_factory, monkeypatch):
    clean = with_parked(plate_s1(), [done_row("wi_s2_01", "Tidy shelf 01", at="2026-10-05T09:00:00.000Z")])
    buggy = plate_buggy(SAM)
    buggy["rows"].append(plate_row("world", W_PRIYA, "run", "rest", PRIYA_TITLES["wi_priya_2"], at=NOW))
    buggy = with_parked(
        buggy,
        [
            done_row("wi_s2_01", "Tidy shelf 01", at="2026-10-05T09:00:00.000Z"),
            done_row("wi_priya_3", PRIYA_TITLES["wi_priya_3"], at=NOW),
        ],
    )
    priya = with_parked(plate_s0(PRIYA), [done_row("wi_priya_1", PRIYA_TITLES["wi_priya_1"], at=NOW)])
    world = build_world()
    spy = AccessSpy(monkeypatch)
    rig = rig_factory(world=world, plates={SAM: buggy, PRIYA: priya})
    response = rig.ask("Status")
    body = response.json()
    assert body_lines(body) == expected_status(clean).lines
    assert {r.actor for r in spy.all_requests()} == {SAM} and {r.action for r in spy.all_requests()} == {"read_full"}
    assert rig.plate_source.calls == [(SAM, NOW)], "Priya's plate is never built"
    assert_no_leak(rig.surfaces(response), world.sentinels, where="status")
    for kind in ("work_item", "pinboard_item", "world"):
        assert f"assistant.plate_row_refused {kind}" in rig.logs()


def test_FR_PA_08_route_role_and_districts_of_the_principal_change_nothing(rig_factory):
    rig = rig_factory()
    owner = strip_volatile(rig.ask("Status").json())
    assert body_lines(owner) == S1_LITERAL
    world = rig.world
    world.store.worlds[W_LAUNCH].districts = {"d_secret": deps.DistrictRecord("d_secret", "DISTRICT-SECRET-SUMMARY")}
    rig.set_principal(
        deps.Principal(user_id=SAM, role="viewer", world_id=W_PRIYA, channel="web", districts=("d_hidden",))
    )
    viewer = rig.ask("Status")
    assert strip_volatile(viewer.json()) == owner, "the panel is person-scoped: role, world and districts are ignored"
    assert_no_leak(rig.surfaces(viewer), ["DISTRICT-SECRET-SUMMARY", "d_secret"], where="districts")
    rig.set_principal(principal(SAM, channel="email"))
    assert rig.ask("Status").status_code == 403


def test_FR_PA_08_route_titles_stay_out_of_events_and_logs_and_secrets_are_redacted_in_the_archive(rig_factory):
    titles = ["Token " + FAKE_KEY] + [t for t in hostile_titles() if not t.startswith("Token")]
    rows = [plate_row("card", ulid(300 + n), "question", "soon", t, at=NOW) for n, t in enumerate(titles)] + [
        plate_row("world", W_LAUNCH, "run", "rest", "Launch site refresh", at="2026-10-01T09:00:00.000Z")
    ]
    rig = rig_factory(plates={SAM: make_plate(SAM, rows)})
    response = rig.ask("Status")
    assert response.status_code == 200
    body = response.json()
    assert body["lines"][0]["text"] == TEXT["tasks_header"] and len(body["lines"]) == 1 + 1 + 1 + CAP + 1
    surfaces = rig.surfaces(response, archive=False)
    surfaces.pop("body")
    secrets = [FAKE_KEY, "Launch site refresh", *[t for t in titles if len(t) > 8 and not t.startswith("$")]]
    assert_no_leak(surfaces, secrets, where="status")
    archive = json.dumps(rig.archive_records(), sort_keys=True)
    assert "sk-" not in archive and "[REDACTED]" in archive, "the raw archive keeps the answer text, redacted (PE-16)"


def test_FR_PA_08_route_status_works_in_replay_only_mode_with_no_model(rig_factory):
    rig = rig_factory(decider=ScriptedDecider(model_decision("intent", intent="plate", credits=0.5)))
    rig.flags.set("replay_only", True, reason="NFR-24 test")
    body = rig.ask("Status").json()
    assert (body["outcome"], body["decided_by"]) == ("answered", "rules") and body_lines(body) == S1_LITERAL
    assert rig.decider.calls == 0
    unmatched = rig.ask(UNMATCHED).json()
    assert unmatched["text"] == DECLINES["rules_only"]
