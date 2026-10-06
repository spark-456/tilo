"""PPL-11b slice 11b-1, FR-PA-13 "facts from read models" (API_PPL_11b.md sections 5, 7 and 10.1): the panel answers
what is waiting, overdue, due soon, on the calendar, pinned, in the mail or running by a TEMPLATE over the signed-in
person's own plate rows, citing the records it stands on, and declines what it cannot back (HR-1).

Acceptance (PRD addendum FR-PA-13): 20 questions, each answered by its template over the read-model rows citing at
least one source; an unknown question is declined with what the panel can show. Tests call `core.answer` with the
REAL `tilo_people` oracle (in-memory stores) behind a `RefGate`; the expected text is the tests' own oracle of
section 5 (`_ppl11b_lib.expected_facts`), which reads config/assistant.yaml itself.

Written before any implementation: every test fails today with ModuleNotFoundError for `tilo_api.assistant`.
"""

from __future__ import annotations

import pytest
from _ppl11b_lib import (
    ANSWER,
    DECLINES,
    FLAGGED_TITLE,
    INTENTS,
    MAIL_ID,
    NOW,
    PRIYA,
    SAM,
    UNMATCHED,
    W_LAUNCH,
    W_VENDOR,
    AccessSpy,
    ScriptedDecider,
    expected_facts,
    lines_of,
    load_questions,
    load_unknown_questions,
    make_gate,
    make_plate,
    mod,
    model_decision,
    plate_row,
    plate_s0,
    plate_s1,
    plate_s2,
    run_answer,
    s1_rows,
    sources_of,
    u,
    work_item,
)
from _ppl11b_lib import world as world  # noqa: PLC0414  (the fixture)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

QUESTIONS = load_questions()
S1_REFS = {(r["ref"]["kind"], r["ref"]["id"]) for r in plate_s1()["rows"]}


def _ids(q):
    return f"q{q['n']:02d}"


def _refusing_gate(world, plate, refused):
    gate_mod = mod("tilo_api.assistant.gate")

    class RefusingGate(gate_mod.RefGate):
        def allows(self, ref):
            return (ref.kind, ref.id) not in refused and super().allows(ref)

    return make_gate(world, plate, gate_cls=RefusingGate)


# --------------------------------------------------------------------------------------------- A13-1, A13-2
@pytest.mark.parametrize("q", QUESTIONS, ids=_ids)
def test_FR_PA_13_A13_1_each_of_20_questions_is_answered_by_its_template_over_the_plate_rows(world, q):
    plate = plate_s1()
    decider = ScriptedDecider()  # any call is an assertion failure and a spy count
    answer = run_answer(world, plate, q["text"], decider=decider)
    want = expected_facts(q["intent"], plate["rows"], narrow_title=q["narrow_title"])
    assert (answer.outcome, answer.decided_by, answer.intent) == ("answered", "rules", q["intent"]), q["text"]
    assert lines_of(answer) == want.lines
    assert answer.ui_action == want.ui_action
    assert answer.decline is None
    claims = [ln for ln in answer.lines if ln.source is not None]
    assert claims, "an answered outcome has at least one claim line"
    sources = sources_of(answer)
    assert 1 <= len(sources) <= 20
    assert set(sources) <= S1_REFS, "every source is a row of the person's own plate"
    assert decider.calls == 0, "the 20 questions are answered by rules: no model call (FR-PA-19)"
    assert answer.model is None


@pytest.mark.parametrize("q", QUESTIONS, ids=_ids)
def test_FR_PA_13_A13_2_the_same_questions_on_an_empty_plate_are_declined_with_the_empty_text(world, q):
    answer = run_answer(world, plate_s0(), q["text"], decider=ScriptedDecider())
    assert (answer.outcome, answer.decided_by, answer.decline) == ("declined", "rules", "empty")
    assert lines_of(answer) == [(INTENTS[q["intent"]]["empty"], None)]
    assert sources_of(answer) == [], "an answer with no source is never `answered` (HR-1)"
    assert answer.ui_action is None


def test_FR_PA_13_A13_1_exact_template_lines_for_pinned_cases(world):
    """Pins the oracle itself to the spec text, so a wrong oracle cannot make a wrong builder pass."""
    mail = run_answer(world, plate_s1(), "Which emails need a reply?")
    assert lines_of(mail) == [("Mail that needs your reply:", None), ("Mail that needs your reply", ("mail", MAIL_ID))]
    cal = run_answer(world, plate_s1(), "What is on my calendar today?")
    assert lines_of(cal)[1] == ("15:00 Team planning", ("calendar_entry", "ce_plan1")), "09:30Z shown in Asia/Kolkata"
    pins = [t for t, s in lines_of(run_answer(world, plate_s1(), "What is pinned for me?"))]
    assert "Vendor review checklist (you are responsible) (due 2026-10-03)" in pins
    assert "Kickoff checklist (you are tagged) (due 2026-10-06)" in pins
    assert f"{FLAGGED_TITLE} (you are tagged) (flagged)" in pins
    waiting = [t for t, s in lines_of(run_answer(world, plate_s1(), "What needs my approval?"))]
    assert waiting[0] == "Waiting for you:"
    assert set(waiting[1:]) == {
        "Send the quote to Acme?: waiting for your approval",
        "Allow Gmail access: waiting for your consent",
        "Launch site refresh: blocked",
        "Weekly sync minutes: minutes to confirm",
        "Which logo for the deck?: waiting for your answer",
    }


# --------------------------------------------------------------------------------------------- A13-3, truncation
def test_FR_PA_13_A13_3_a_long_plate_answer_stops_at_ten_claim_lines_and_offers_my_plate(world):
    answer = run_answer(world, plate_s2(world), "What is on my plate?")
    assert answer.outcome == "answered"
    assert len([ln for ln in answer.lines if ln.source is not None]) == 10
    last = answer.lines[-1]
    assert (last.text, last.source) == ("More on My plate.", None)
    assert answer.ui_action == {"kind": "navigate", "route": "plate", "target": None}
    assert len(sources_of(answer)) == 10


def test_FR_PA_13_A13_3_ten_rows_fit_and_eleven_do_not(world):
    rows = plate_s2(world)["rows"]
    ten = run_answer(world, make_plate(SAM, rows[:10]), "What is on my plate?")
    assert ten.ui_action is None and all(ln.text != "More on My plate." for ln in ten.lines)
    eleven = run_answer(world, make_plate(SAM, rows[:11]), "What is on my plate?")
    assert eleven.lines[-1].text == "More on My plate." and eleven.ui_action is not None
    assert len([ln for ln in eleven.lines if ln.source is not None]) == 10


def test_FR_PA_13_A13_3_the_plate_answer_groups_its_rows_with_the_config_headers(world):
    answer = run_answer(world, plate_s1(), "What is on my plate?")
    assert lines_of(answer) == expected_facts("plate", plate_s1()["rows"]).lines
    headers = [ln.text for ln in answer.lines if ln.source is None]
    assert headers == [
        ANSWER["group_headers"]["attention"],
        ANSWER["group_headers"]["overdue"],
        ANSWER["group_headers"]["soon"],
        ANSWER["more"],
    ]


# --------------------------------------------------------------------------------------------- A13-4 unknown
@pytest.mark.parametrize("text", load_unknown_questions())
def test_FR_PA_13_A13_4_an_unknown_question_is_declined_with_what_the_panel_can_show(world, text):
    answer = run_answer(world, plate_s1(), text, decider=None)
    assert (answer.outcome, answer.decided_by, answer.decline) == ("declined", "rules", "unknown")
    assert lines_of(answer) == [(DECLINES["unknown"], None)]
    assert answer.ui_action is None and sources_of(answer) == [] and answer.model is None


@pytest.mark.parametrize(
    "text",
    [
        "What is due?",  # one of the two `when` groups of due_soon is not enough (AND of ORs)
        "What is soon?",
        "What is on my plateau?",  # a word is a whole token, never a substring
        "What is on my platelet count?",
        "Tell me about unpinning",
        "waitinglist",
        "Quel est mon plan?",
        u(0x041F, 0x043E, 0x043A, 0x0430, 0x0436, 0x0438) + " " + u(0x043F, 0x043B, 0x0430, 0x043D),
        "!!!",
        "   ",
        "plate" + "x" * 3000,
    ],
)
def test_FR_PA_13_unknown_phrasings_match_no_intent(world, text):
    answer = run_answer(world, plate_s1(), text, decider=None)
    assert (answer.outcome, answer.decline) == ("declined", "unknown")


def test_FR_PA_13_a_fact_question_with_a_model_available_still_never_calls_it(world):
    decider = ScriptedDecider()
    for q in QUESTIONS:
        run_answer(world, plate_s1(), q["text"], decider=decider)
    assert decider.calls == 0


# --------------------------------------------------------------------------------------------- matching rules
@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("What is waiting and overdue?", "waiting"),  # config order is precedence
        ("Which emails are overdue?", "mail"),
        ("WHAT IS ON MY PLATE???", "plate"),
        ("what" + u(0x2019) + "s on my plate today", "plate"),
        ("what" + u(0x2018) + "s on my plate today", "plate"),
        ("pla" + u(0x200B) + "te please", "plate"),
        (u(0xFF30, 0xFF2C, 0xFF21, 0xFF34, 0xFF25) + " please", "plate"),  # fullwidth, NFKC folds it
        ("can you please show me what is overdue", "overdue"),
        ("Hey Tilo, what needs my approval", "waiting"),
        ("what is due and coming up", "due_soon"),
    ],
)
def test_FR_PA_13_word_rules_normalise_then_pick_the_first_matching_intent(world, text, intent):
    answer = run_answer(world, plate_s1(), text)
    assert answer.intent == intent and answer.decided_by == "rules", text


def test_FR_PA_13_a_title_containing_template_syntax_is_data_never_a_template(world):
    weird = "Pay $label and ${time} and {0} and %s and $$"
    world.stores.work_items.create(work_item("wi_weird", SAM, weird))
    plate = make_plate(
        SAM, [plate_row("work_item", "wi_weird", "work_item", "rest", weird, at="2026-10-06T08:00:00.000Z")]
    )
    answer = run_answer(world, plate, "What is on my plate?")
    assert (weird, ("work_item", "wi_weird")) in lines_of(answer)


@pytest.mark.parametrize(
    ("tz", "shown"),
    [
        ("Asia/Kolkata", "15:00 Team planning"),
        ("America/Los_Angeles", "02:30 Team planning"),
        (None, "09:30 UTC Team planning"),
        ("Mars/Phobos", "09:30 UTC Team planning"),
    ],
)
def test_FR_PA_13_calendar_times_use_the_persons_own_time_zone_else_utc(world, tz, shown):
    answer = run_answer(world, plate_s1(), "What is on my calendar today?", tz=tz)
    assert lines_of(answer)[1][0] == shown


def test_FR_PA_13_narrowing_by_the_selected_world_or_by_the_title_words(world):
    plate = plate_s1()
    everything = run_answer(world, plate, "How are my tasks going?")
    assert [t for t, _ in lines_of(everything)] == [
        "Your tasks:",
        "Launch site refresh: blocked",
        "Vendor onboarding: running",
    ]
    selected = run_answer(world, plate, "How are my tasks going?", record=W_VENDOR, route=f"/world/{W_VENDOR}")
    assert [t for t, _ in lines_of(selected)] == ["Your tasks:", "Vendor onboarding: running"]
    by_title = run_answer(world, plate, "How is the launch site refresh going?")
    assert [t for t, _ in lines_of(by_title)] == ["Your tasks:", "Launch site refresh: blocked"]
    no_such = run_answer(world, plate, "How is the printer migration going?")
    assert len(lines_of(no_such)) == 3, "words that hold no single row's title narrow nothing"
    not_a_task = run_answer(world, plate, "How are my tasks going?", record="wi_printer")
    assert len(lines_of(not_a_task)) == 3, "a selected record that is not a selected row narrows nothing"


# ---------------------------------------------------------------- A13-5 model picks a read model only
def test_FR_PA_13_A13_5_a_model_may_only_choose_a_fact_intent_and_the_answer_is_still_the_template(world):
    decider = ScriptedDecider(model_decision("intent", intent="pins"))
    answer = run_answer(world, plate_s1(), UNMATCHED, decider=decider)
    assert answer.decided_by == "model" and answer.outcome == "answered" and answer.intent == "pins"
    assert lines_of(answer) == expected_facts("pins", plate_s1()["rows"]).lines
    assert decider.calls == 1
    ask = decider.asks[0]
    assert (ask.user, ask.org_id, ask.now) == (SAM, "org_tilo", NOW)
    assert ask.question == UNMATCHED and ask.plate_fingerprint == plate_s1()["fingerprint"]


@pytest.mark.parametrize("bad", ["not_an_intent", "Pins", "pins ", "navigate", "", None, "plate\n"])
def test_FR_PA_13_A13_5_an_unknown_intent_id_is_dropped_with_the_fixed_text(world, bad):
    answer = run_answer(world, plate_s1(), UNMATCHED, decider=ScriptedDecider(model_decision("intent", intent=bad)))
    assert (answer.outcome, answer.decided_by, answer.decline) == ("declined", "model", "dropped")
    assert lines_of(answer) == [(DECLINES["dropped"], None)] and answer.ui_action is None


def test_FR_PA_13_A13_5_a_model_chosen_intent_narrows_by_the_selection_only_never_by_the_question_words(world):
    plate = plate_s1()
    question = "Tell me about the vendor onboarding thing"  # no rule reads it; its words name one task
    chosen = run_answer(world, plate, question, decider=ScriptedDecider(model_decision("intent", intent="tasks")))
    assert [t for t, _ in lines_of(chosen)] == [
        "Your tasks:",
        "Launch site refresh: blocked",
        "Vendor onboarding: running",
    ]
    selected = run_answer(
        world,
        plate,
        question,
        record=W_LAUNCH,
        route=f"/world/{W_LAUNCH}",
        decider=ScriptedDecider(model_decision("intent", intent="tasks")),
    )
    assert [t for t, _ in lines_of(selected)] == ["Your tasks:", "Launch site refresh: blocked"]


def test_FR_PA_13_A13_5_an_intent_with_no_rows_is_declined_empty_even_when_the_model_picked_it(world):
    answer = run_answer(world, plate_s0(), UNMATCHED, decider=ScriptedDecider(model_decision("intent", intent="mail")))
    assert (answer.outcome, answer.decided_by, answer.decline) == ("declined", "model", "empty")
    assert sources_of(answer) == []


# --------------------------------------------------------------------------------------------- A13-6 gated rows
@pytest.mark.parametrize(
    "refused",
    [
        ("work_item", "wi_budget_notes"),
        ("card", s1_rows()[0]["ref"]["id"]),
        ("pinboard_item", "pb_flagged"),
        ("calendar_entry", "ce_plan1"),
        ("mail", MAIL_ID),
        ("world", W_LAUNCH),
    ],
)
def test_FR_PA_13_A13_6_a_row_the_gate_refuses_is_named_nowhere(world, refused):
    plate = plate_s1()
    title = next(r["title"] for r in plate["rows"] if (r["ref"]["kind"], r["ref"]["id"]) == refused)
    gate = _refusing_gate(world, plate, {refused})
    texts: list[str] = []
    for q in QUESTIONS:
        answer = run_answer(world, plate, q["text"], gate=gate, decider=ScriptedDecider())
        texts += [ln.text for ln in answer.lines]
        assert refused not in sources_of(answer), q["text"]
    assert all(title is None or title not in t for t in texts)
    decider = ScriptedDecider(model_decision("intent", intent="plate"))
    run_answer(world, plate, UNMATCHED, gate=gate, decider=decider)
    menu = decider.asks[0].menu
    assert all((r.ref.kind, r.ref.id) != refused for r in menu.rows) and all(
        (r.kind, r.id) != refused for r in menu.refs
    )


def test_FR_PA_13_A13_6_the_same_call_twice_gives_equal_answers(world):
    plate = plate_s1()
    for q in QUESTIONS[::4]:
        a = run_answer(world, plate, q["text"])
        b = run_answer(world, plate, q["text"])
        assert a == b


def test_FR_PA_13_the_real_oracle_gates_every_row_through_read_as_the_signed_in_person(world, monkeypatch):
    spy = AccessSpy(monkeypatch)
    run_answer(world, plate_s1(), "What is on my plate?")
    people_reads = [r for r in spy.reads if r.record_kind != "person"]
    assert {r.record["id"] for r in people_reads} >= {"wi_budget_notes", "pb_kickoff", "ce_plan1"}
    assert {(r.actor, r.action, r.now) for r in spy.reads} == {(SAM, "read_full", NOW)}
    assert PRIYA not in spy.record_ids()


# --------------------------------------------------------------------------------------------- HR-1, properties
_VOCAB = [
    "what",
    "is",
    "on",
    "my",
    "plate",
    "waiting",
    "overdue",
    "due",
    "soon",
    "calendar",
    "pins",
    "mail",
    "tasks",
    "how",
    "going",
    "new",
    "changed",
    "open",
    "show",
    "priya's",
    "her",
    "the",
    "a",
    "launch",
    "site",
    "refresh",
    "zebraquartz",
    "approval",
    "emails",
    "today",
    "tomorrow",
    "sam's",
    "u_priya",
    "?",
    "!",
    "please",
    "tilo",
]


def test_FR_PA_13_property_every_answer_is_backed_and_nothing_raises(world):
    plate = plate_s1()
    refs = {(r["ref"]["kind"], r["ref"]["id"]) for r in plate["rows"]}
    texts = st.one_of(
        st.lists(st.sampled_from(_VOCAB), min_size=1, max_size=9).map(" ".join),
        st.text(max_size=60),
    )

    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(texts)
    def check(text):
        answer = run_answer(world, plate, text, decider=None)
        assert answer.outcome in {"answered", "declined", "navigated"}
        assert answer.decided_by == "rules" and answer.model is None
        sources = sources_of(answer)
        if answer.outcome == "answered":
            assert sources, "answered with no source (HR-1)"
        assert set(sources) <= refs
        assert len(sources) <= 20 and len(answer.lines) >= 1
        assert all(isinstance(ln.text, str) and "\n" not in ln.text for ln in answer.lines)
        assert run_answer(world, plate, text, decider=None) == answer

    check()


def test_FR_PA_13_flagged_titles_are_shown_to_their_owner_but_never_offered_to_the_model(world):
    shown = run_answer(world, plate_s1(), "What is pinned for me?")
    assert any(FLAGGED_TITLE in ln.text and ln.text.endswith(ANSWER["flagged_suffix"]) for ln in shown.lines)
    decider = ScriptedDecider(model_decision("decline"))
    run_answer(world, plate_s1(), UNMATCHED, decider=decider)
    menu = decider.asks[0].menu
    flagged_rows = [r for r in menu.rows if r.ref.id == "pb_flagged"]
    assert flagged_rows and all(r.title is None for r in flagged_rows), "PE-21: a flagged title is withheld"
    assert FLAGGED_TITLE not in repr(menu)


def test_FR_PA_13_a_question_about_someone_else_looks_nothing_up(world, monkeypatch):
    spy = AccessSpy(monkeypatch)
    gate_mod = mod("tilo_api.assistant.gate")
    calls: list[str] = []

    class CountingGate(gate_mod.RefGate):
        def allows(self, ref):
            calls.append("allows")
            return super().allows(ref)

        def record(self, ref):
            calls.append("record")
            return super().record(ref)

    decider = ScriptedDecider()
    gate = make_gate(world, plate_s1(), gate_cls=CountingGate)
    for text in ("What is on Priya's plate?", "Show her calendar", "what does my manager's plate hold"):
        answer = run_answer(world, plate_s1(), text, gate=gate, decider=decider)
        assert (answer.outcome, answer.decided_by, answer.decline) == ("declined", "rules", "other_person")
        assert lines_of(answer) == [(DECLINES["other_person"], None)] and sources_of(answer) == []
    assert not calls and decider.calls == 0 and spy.reads == [], "the decision rests on the words alone (FR-PA-17)"


def test_FR_PA_13_the_answer_function_reads_no_clock_and_changes_nothing(world, monkeypatch):
    from tilo_api import events  # noqa: PLC0415

    def boom():
        raise AssertionError("core.answer must not read a clock (`now` is an argument)")

    monkeypatch.setattr(events, "now", boom)
    before = world.snapshot()
    run_answer(world, plate_s1(), "What is on my plate?")
    assert world.snapshot() == before and not [c for c in world.log if c[1] in {"create", "replace", "delete"}]
