"""FR-HIL-10 through the API, issue #338 (found by the Opus reviews of PRs #336 and #351; PRD 10.3 "Same-type cards from
one district within 60 s merge", 10.6 FR-HIL-02 / FR-HIL-10 "answering resumes the agent in <= 2 s", BQ-74, BQ-239):
a question a unit waits on is never merged. Each such card is listed on its own and its answer resumes its own unit
only; no answer is ever mapped onto another card (a hidden card must never run a step nobody saw).

Given two units of one district that ask within 60 s (two question.routed, two listed cards) When the person answers
one card Then only that unit resumes within 2.0 s, the other keeps waiting for its own answer or its own deadline
default, whichever card id the answer is filed under. A group that is resolving or closed accepts no new member (the
code-written confirmation card of a sensitive step, raised the moment the answer commits, must be listed and answerable,
and its "Prepare it" runs the unit). Also the QuestionWait claim races: a commit-then-raise of one answer followed by a
different answer resolves the wait, and a tick failure after a committed deadline default never fails the unit.

Scripted models and runner, the in-process app, the real CardStore: no model, no network, no timer other than the
1 to 6 s card timeouts the tests set through `must_ask.QUESTION_TIMEOUT_S` (a deadline in the test names).
The harness half of the claim races is in services/harness/tests/test_FR_HIL_10_claim_races_and_option_ids.py.
"""

from __future__ import annotations

import copy
import json
import threading
import time

import pytest
from _agt05_lib import (
    ASK,
    CLEAR,
    RESUME_BUDGET_S,
    ScriptedProvider,
    build_ask_flow,
    needs_you_cards,
    start_and_approve,
    task,
    tasks_provider,
    worker_of,
)
from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, add_seconds, clone_card, load_valid_card
from _clint2_lib import wait_for

pytestmark = pytest.mark.usefixtures("must_ask_ask_mode")  # these suites pin the cards (BQ-ASSUME-1)

ASK01 = task("ASK-01")  # "Update the pricing sheet with the new numbers": a model-written ambiguity card
ASK10 = task("ASK-10")  # "Pay the outstanding supplier invoice": a model-raised sensitive_step card
START = "2026-09-29T09:30:00.000Z"
U1_TITLE = "Compare the two vendor quotes by hand"
U2_TITLE = "Archive the old supplier folder quietly"
U1_REPLY = json.dumps(
    {
        "ask": True,
        "reason": "ambiguous_brief",
        "question": "Should I use the newest quote only?",
        "options": ["Go ahead", "Wait for me"],
        "suggested": 1,
        "why": "Waiting costs nothing.",
    }
)


# --------------------------------------------------------------------------------------------------------------------
# helpers


def _ask_flow(repo_root, titles, *, timeout_s=None, monkeypatch=None):
    """A run whose U1, U2 and U3 are titled by `titles` (tasks.json entries), all independent. U1 and U2 are in district
    D1 and so in one Workshop; U3 is in D2 (the plan fixture's districts, laid out by `_clint2_lib.layout_for`)."""
    if timeout_s is not None:
        import tilo_harness.must_ask as must_ask  # noqa: PLC0415

        monkeypatch.setattr(must_ask, "QUESTION_TIMEOUT_S", timeout_s)
    rf = build_ask_flow(repo_root, tasks_provider(*titles, *CLEAR), first=titles[0], independent=True)
    original = rf.compile_plan

    def compile_plan(*, brief, approach, budget_cap, context=None):
        plan = original(brief=brief, approach=approach, budget_cap=budget_cap, context=context)
        for unit, source in zip(plan["units"], titles, strict=True):
            unit["title"], unit["depends_on"] = source["title"], []
        rf.last_plan = plan
        return copy.deepcopy(plan)

    rf.compile_plan = compile_plan
    return rf


@pytest.fixture()
def flows():
    made = []
    yield made
    for rf in made:
        rf.close()


def _two_units_asked_in_one_district(repo_root, flows, *, timeout_s=None, monkeypatch=None):
    """U1 and U2 (both D1) ask; U3 is clear. Returns (rf, U1's card, U2's card): two cards, listed separately."""
    rf = _ask_flow(repo_root, (ASK, ASK01, CLEAR[2]), timeout_s=timeout_s, monkeypatch=monkeypatch)
    flows.append(rf)
    start_and_approve(rf)
    wait_for(lambda: len(rf.events("question.routed")) >= 2, what="two question.routed")
    rf.quiet_stream()
    routed = [e["data"]["card_id"] for e in rf.events("question.routed")]
    assert len(set(routed)) == 2, "each asking unit has a card of its own"
    listed = {c["id"]: c for c in needs_you_cards(rf)}
    assert set(listed) == set(routed), "a question a unit waits on is never merged: both cards are listed"
    return rf, listed[routed[0]], listed[routed[1]]


def _resumes_only(rf, unit, other, t0):
    wait_for(lambda: unit in rf.runner.started_at, timeout=RESUME_BUDGET_S + 2, what=f"{unit} to resume")
    assert rf.runner.started_at[unit] - t0 <= RESUME_BUDGET_S, "FR-HIL-10: answering resumes its unit in <= 2 s"
    assert rf.runner.answers[unit].answered_by == "person", rf.runner.answers[unit]
    rf.quiet_stream()
    assert other is None or other not in rf.runner.started_at, f"{other} waits for an answer of its own"


# --------------------------------------------------------------------------------------------------------------------
# 1. same-district question cards are not merged


def test_FR_HIL_10_each_question_card_of_one_district_is_answered_separately_and_resumes_only_its_own_unit_within_2_s(
    repo_root, flows
):
    rf, first, second = _two_units_asked_in_one_district(repo_root, flows)
    assert rf.runner.started_at.keys().isdisjoint({"U1", "U2"}), "both asked units wait for a person"

    t0 = time.monotonic()
    response = rf.answer(first["id"], first["options"][0]["id"])

    assert response.status_code == 200 and response.json() == {"outcome": "answered"}, response.text
    _resumes_only(rf, "U1", "U2", t0)
    assert [c["id"] for c in needs_you_cards(rf)] == [second["id"]], "the other card is still open and listed"

    t1 = time.monotonic()
    chosen = second["options"][1]["id"]
    assert rf.answer(second["id"], chosen).status_code == 200
    _resumes_only(rf, "U2", None, t1)
    assert rf.runner.answers["U2"].option == chosen, "U2 resumed with the option its own card was answered with"
    assert rf.runner.answers["U1"].option == first["options"][0]["id"]
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    events = rf.quiet_stream()
    answered = [e["data"]["answered_by"] for e in events if e["type"] == "question.answered"]
    assert answered == ["person", "person"] and "world.failed" not in [e["type"] for e in events]
    assert rf.runner.ran.count("U1") == 1 and rf.runner.ran.count("U2") == 1
    assert [c for c in rf.cards().json() if c["kind"] == "needs_you"] == []


def test_FR_HIL_10_an_answer_filed_under_one_card_never_touches_the_other_units_card_or_wait(
    repo_root, flows, monkeypatch
):
    """Answering U2's card resumes U2 only. U1's card stays open and unanswered, so U1 gets its own deadline default
    (the Director's nudge), and a late answer to U1's card is refused as already resolved."""
    rf, first, second = _two_units_asked_in_one_district(repo_root, flows, timeout_s=4, monkeypatch=monkeypatch)

    t0 = time.monotonic()
    assert rf.answer(second["id"], "o1").status_code == 200
    _resumes_only(rf, "U2", "U1", t0)
    assert [c["id"] for c in needs_you_cards(rf)] == [first["id"]], "U1's card is untouched and still listed"

    wait_for(lambda: "U1" in rf.runner.started_at, timeout=8, what="U1 to resume with its own deadline default")
    assert rf.runner.answers["U1"].answered_by == "default", "U1 was never answered by U2's answer"
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    events = rf.quiet_stream()
    answered = sorted(e["data"]["answered_by"] for e in events if e["type"] == "question.answered")
    assert answered == ["default", "person"], answered
    late = rf.answer(first["id"], "o2")
    assert late.status_code == 400 and late.json()["reason"] == "already_resolved", late.text
    rf.quiet_stream()
    assert rf.runner.ran.count("U1") == 1 and rf.runner.ran.count("U2") == 1


class _SlowU2(ScriptedProvider):
    def generate(self, request):
        if U2_TITLE in request.prompt:
            time.sleep(0.6)  # U1's card is the first one stored and listed
        return super().generate(request)


def _model_card_and_rule_card(repo_root, flows):
    """U1 asks with a model-written card ("Go ahead" / "Wait for me", runs on any answer); U2's reply is unreadable, so
    code raises its rule card (o1 "Hold this step", o2 "Go ahead"; only o2 runs the unit, the safe default is o1).
    Returns (rf, U1's card, U2's rule card), both listed."""
    provider = _SlowU2({U1_TITLE: U1_REPLY, CLEAR[2]["title"]: json.dumps({"ask": False})})
    rf = build_ask_flow(repo_root, provider, independent=True)
    flows.append(rf)
    original = rf.compile_plan

    def compile_plan(*, brief, approach, budget_cap, context=None):
        plan = original(brief=brief, approach=approach, budget_cap=budget_cap, context=context)
        for unit, title in zip(plan["units"], (U1_TITLE, U2_TITLE, CLEAR[2]["title"]), strict=True):
            unit["title"], unit["depends_on"] = title, []
        rf.last_plan = plan
        return copy.deepcopy(plan)

    rf.compile_plan = compile_plan
    start_and_approve(rf)
    wait_for(lambda: len(rf.events("question.routed")) >= 2, what="two question.routed")
    rf.quiet_stream()
    cards = needs_you_cards(rf)
    assert len(cards) == 2, "U2's rule card is listed beside U1's: nobody answers a card they cannot see"
    mine = next(c for c in cards if c["what_happened"].startswith("Should I use"))
    rule = next(c for c in cards if c["id"] != mine["id"])
    assert {o["label"] for o in rule["options"]} >= {"Hold this step", "Go ahead"}
    return rf, mine, rule


def test_FR_HIL_10_a_label_picked_on_one_card_never_runs_the_other_unit_whose_rule_card_nobody_has_seen(
    repo_root, flows
):
    """The shape of the Opus review blocker (P1): U1's model card offers "Go ahead" and "Wait for me"; U2's reply is
    unreadable, so code raises its rule card ("Hold this step" / "Go ahead", only the second runs the unit). The person
    picks "Go ahead" on U1's card: U1 resumes, U2 must NOT start from that choice. Its card stays listed with its own
    options, and only an answer to it decides U2."""
    rf, mine, rule = _model_card_and_rule_card(repo_root, flows)
    go = next(o["id"] for o in mine["options"] if o["label"] == "Go ahead")

    assert rf.answer(mine["id"], go).status_code == 200

    wait_for(lambda: "U1" in rf.runner.started_at, timeout=RESUME_BUDGET_S + 2, what="U1 to resume")
    time.sleep(1.5)  # long enough for a wrongly mapped answer to start U2
    rf.quiet_stream()
    assert "U2" not in rf.runner.started_at, "U2 must not run on the label the person picked for U1"
    assert [c["id"] for c in needs_you_cards(rf)] == [rule["id"]], "U2's rule card is still open"
    hold = next(o["id"] for o in rule["options"] if o["label"] == "Hold this step")
    assert rf.answer(rule["id"], hold).status_code == 200
    wait_for(lambda: rf.events("agent.retired"), what="U2 held by its own answer")
    rf.quiet_stream()
    assert "U2" not in rf.runner.started_at
    assert any("the answer held this step" in e["summary"] for e in rf.events("agent.retired"))


def _commit_then_raise_first_answer(monkeypatch, rf, *, fail_next=False):
    """The first question.answered the writer sees is committed and then raises (its caller sees a 503). With
    `fail_next` the second one fails outright, nothing committed."""
    original, seen = rf.writer.append, {"n": 0}

    def append(world_id, event):
        if event["type"] != "question.answered":
            return original(world_id, event)
        seen["n"] += 1
        if seen["n"] == 1:
            original(world_id, event)
            raise RuntimeError("the connection dropped after the event was committed")
        if fail_next and seen["n"] == 2:
            raise RuntimeError("the writer is down")
        return original(world_id, event)

    monkeypatch.setattr(rf.writer, "append", append)


def _hold_and_go(rule):
    return (
        next(o["id"] for o in rule["options"] if o["label"] == "Hold this step"),
        next(o["id"] for o in rule["options"] if o["label"] == "Go ahead"),
    )


def test_FR_HIL_10_a_rule_card_whose_committed_answer_is_hold_stays_held_when_the_same_answerer_then_says_go_ahead(
    repo_root, flows, monkeypatch
):
    """Review r1 of #359: the owner picks Hold on U2's rule card, it commits and then the request fails (503). The
    owner changes their mind and sends Go ahead. An event id carries no option, so the writer cannot tell the two
    apart; the committed answer is Hold and U2 must stay held (never agent.working), whoever sends the second answer."""
    rf, _mine, rule = _model_card_and_rule_card(repo_root, flows)
    hold, go = _hold_and_go(rule)
    _commit_then_raise_first_answer(monkeypatch, rf)

    first = rf.answer(rule["id"], hold)
    assert first.status_code == 503, first.text
    second = rf.answer(rule["id"], go)

    assert second.status_code == 400 and second.json()["reason"] == "already_resolved", second.text
    wait_for(lambda: rf.events("agent.retired"), what="U2 held")
    time.sleep(1.0)
    rf.quiet_stream()
    assert "U2" not in rf.runner.started_at, "the unit ran on an option that never committed"
    assert [e["data"]["answered_by"] for e in rf.events("question.answered")] == ["person"], "one event, Hold's"
    assert rule["id"] not in [c["id"] for c in needs_you_cards(rf)], "the card closed with the committed answer"


def test_FR_HIL_10_a_rule_card_held_by_a_committed_answer_stays_held_when_a_second_team_lead_says_go_ahead(
    repo_root, flows, monkeypatch
):
    rf, _mine, rule = _model_card_and_rule_card(repo_root, flows)
    hold, go = _hold_and_go(rule)
    district = rf.events("question.routed")[0]["district"]
    _commit_then_raise_first_answer(monkeypatch, rf)
    rf.as_member("u_lead_one", "team_lead", districts=(district,))
    assert rf.answer(rule["id"], hold).status_code == 503
    rf.as_member("u_lead_two", "team_lead", districts=(district,))

    second = rf.answer(rule["id"], go)

    assert second.status_code == 400, f"a second Team Lead's other option is refused: {second.text}"
    wait_for(lambda: rf.events("agent.retired"), what="U2 held")
    time.sleep(1.0)
    rf.as_member()
    rf.quiet_stream()
    assert "U2" not in rf.runner.started_at, "the unit ran on an option that never committed"
    assert [e["data"]["answered_by"] for e in rf.events("question.answered")] == ["team_lead"]


def test_FR_HIL_10_a_held_rule_card_stays_held_at_its_deadline_after_a_failed_go_ahead(repo_root, flows, monkeypatch):
    """Review r1 of #359 (P2): Hold commits then raises; Go ahead then fails too; nobody retries. At the deadline the
    unit resumes with what committed (Hold), never with the Go ahead that was only attempted."""
    import tilo_harness.must_ask as must_ask  # noqa: PLC0415

    monkeypatch.setattr(must_ask, "QUESTION_TIMEOUT_S", 3)
    rf, _mine, rule = _model_card_and_rule_card(repo_root, flows)
    hold, go = _hold_and_go(rule)
    _commit_then_raise_first_answer(monkeypatch, rf, fail_next=True)

    assert rf.answer(rule["id"], hold).status_code == 503
    assert rf.answer(rule["id"], go).status_code in (400, 503)

    wait_for(lambda: rf.events("agent.retired"), timeout=8, what="U2 held")
    time.sleep(4.0)  # past the card's deadline
    rf.quiet_stream()
    assert "U2" not in rf.runner.started_at, "the held step ran on an option that never committed"
    assert [e["data"]["answered_by"] for e in rf.events("question.answered")] == ["person"], "one event for the card"
    assert rule["id"] not in [c["id"] for c in needs_you_cards(rf)], "the card does not stay listed"


def test_FR_HIL_10_cards_of_different_districts_are_answered_separately_and_each_resumes_only_its_own_unit(
    repo_root, flows
):
    rf = _ask_flow(repo_root, (ASK, CLEAR[1], ASK01))  # U1 asks in D1, U3 asks in D2
    flows.append(rf)
    start_and_approve(rf)
    wait_for(lambda: len(rf.events("question.routed")) >= 2, what="two question.routed")
    rf.quiet_stream()
    cards = needs_you_cards(rf)
    assert len(cards) == 2, "cards of different districts never merge"
    first = next(c for c in cards if c["header"]["agent"] == worker_of(rf, "U1"))
    second = next(c for c in cards if c["id"] != first["id"])

    t0 = time.monotonic()
    assert rf.answer(first["id"], first["options"][0]["id"]).status_code == 200
    wait_for(lambda: "U1" in rf.runner.started_at, timeout=RESUME_BUDGET_S + 2, what="U1 to resume")
    assert rf.runner.started_at["U1"] - t0 <= RESUME_BUDGET_S
    rf.quiet_stream()
    assert "U3" not in rf.runner.started_at, "the other district's unit still waits for its own answer"
    assert [c["id"] for c in needs_you_cards(rf)] == [second["id"]]

    t1 = time.monotonic()
    assert rf.answer(second["id"], second["options"][1]["id"]).status_code == 200
    wait_for(lambda: "U3" in rf.runner.started_at, timeout=RESUME_BUDGET_S + 2, what="U3 to resume")
    assert rf.runner.started_at["U3"] - t1 <= RESUME_BUDGET_S
    assert rf.runner.answers["U3"].option == second["options"][1]["id"]
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    assert [e["data"]["answered_by"] for e in rf.events("question.answered")] == ["person", "person"]


def test_FR_HIL_10_the_confirmation_card_raised_while_the_answers_group_is_resolving_is_listed_and_answerable(
    repo_root, flows, monkeypatch
):
    """The model-raised sensitive step (ASK-10): the person picks "Pay the full amount", the answer commits, the unit
    resumes and code raises its confirmation card at once, in the same Workshop and within 60 s. The answering request
    is held between the write and the close of the group (the window the unit's thread wins in production), so the new
    card reaches the CardStore while the first card's group is still resolving. It must not merge into that group:
    an answer closes every open member of its group, which would hide the new card for good."""
    from tilo_api.cards import CardStore  # noqa: PLC0415
    from tilo_api.runs import Run  # noqa: PLC0415

    confirmation_reached_the_store = threading.Event()
    submits = []
    original_submit, original_write = CardStore.submit, Run.write

    def submit(self, card, **kwargs):
        submits.append(card["id"])
        if len(submits) >= 2:
            confirmation_reached_the_store.set()
        return original_submit(self, card, **kwargs)

    held = []

    def write(self, part):
        original_write(self, part)  # committed, and the unit is resumed on its loop
        if part["type"] == "question.answered" and not held:
            held.append(part["card_id"])
            confirmation_reached_the_store.wait(timeout=5)
            time.sleep(0.3)  # let that submit finish before this request closes the group

    monkeypatch.setattr(CardStore, "submit", submit)
    monkeypatch.setattr(Run, "write", write)
    rf = build_ask_flow(repo_root, tasks_provider(ASK10, *CLEAR[1:]), first=ASK10, independent=True)
    flows.append(rf)
    start_and_approve(rf)
    wait_for(lambda: rf.events("question.routed"), what="question.routed")
    rf.quiet_stream()
    (first,) = needs_you_cards(rf)
    pay = next(o["id"] for o in first["options"] if o["label"].startswith("Pay"))
    assert not next(o for o in first["options"] if o["id"] == pay)["suggested"], "the model's suggestion is to hold"

    response = rf.answer(first["id"], pay)

    assert response.status_code == 200, response.text
    assert held == [first["id"]] and len(submits) == 2, "the confirmation card was submitted during the held answer"
    wait_for(lambda: len(rf.events("question.routed")) >= 2, what="the confirmation's question.routed")
    rf.quiet_stream()
    listed = [c for c in needs_you_cards(rf) if c["id"] != first["id"]]
    assert len(listed) == 1, "the confirmation card must be listed (it merged into the closing group and is hidden)"
    (confirmation,) = listed
    assert confirmation["id"] == rf.events("question.routed")[1]["data"]["card_id"]
    prepare = next(o["id"] for o in confirmation["options"] if o["label"].startswith("Prepare"))
    assert "U1" not in rf.runner.started_at, "nothing runs on the first, choice-only answer"

    t0 = time.monotonic()
    answered = rf.answer(confirmation["id"], prepare)

    assert answered.status_code == 200, (
        f"the confirmation card must be answerable: {answered.status_code} {answered.text}"
    )
    wait_for(lambda: "U1" in rf.runner.started_at, timeout=RESUME_BUDGET_S + 2, what="U1 to run after 'Prepare it'")
    assert rf.runner.started_at["U1"] - t0 <= RESUME_BUDGET_S
    assert rf.runner.answers["U1"].option == prepare and rf.runner.answers["U1"].answered_by == "person"
    wait_for(lambda: rf.events("world.completed"), what="world.completed")


def test_FR_HIL_10_a_card_submitted_while_its_groups_answer_is_being_written_starts_its_own_group():
    """CardStore alone, deterministic: the writer is held inside the write of the first card's answer."""
    from tilo_api.cards import CardStore  # noqa: PLC0415

    base = load_valid_card("needs_you_compare_basis")
    world = base["world_id"]
    entered, release = threading.Event(), threading.Event()

    class HeldWriter(FakeEventWriter):
        def write(self, part):
            entered.set()
            release.wait(timeout=5)
            super().write(part)

    store = CardStore(clock=FakeClock(START), writer=HeldWriter(), world_owners={world: "u_owner"})
    first = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V301", created_at=START)
    second = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V302", created_at=add_seconds(START, 5))
    assert store.submit(first, district="D1").outcome == "accepted"
    answer = {}
    thread = threading.Thread(
        target=lambda: answer.setdefault("result", store.answer(
            world, first["id"], option=first["options"][0]["id"], channel="web", principal=OWNER_P
        )),
    )  # fmt: skip
    thread.start()
    try:
        assert entered.wait(timeout=5), "the answer reached the writer"

        result = store.submit(second, district="D1")

        assert result.outcome == "accepted" and result.card_id == second["id"], (
            f"a group that is resolving accepts no new member, got {result}"
        )
    finally:
        release.set()
        thread.join(timeout=5)
    assert answer["result"].outcome == "answered"
    assert [c["id"] for c in store.list_for_world(world, principal=OWNER_P)] == [second["id"]], (
        "the new card stays open and listed after the first group closes"
    )
    assert store.answer(
        world, second["id"], option=second["options"][0]["id"], channel="web", principal=OWNER_P
    ).outcome == "answered"  # fmt: skip


def test_FR_HIL_10_a_card_submitted_after_its_groups_answer_starts_its_own_group():
    from tilo_api.cards import CardStore  # noqa: PLC0415

    base = load_valid_card("needs_you_compare_basis")
    world = base["world_id"]
    store = CardStore(clock=FakeClock(START), writer=FakeEventWriter(), world_owners={world: "u_owner"})
    first = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V311", created_at=START)
    later = clone_card(base, id_="01J8Z3K4M5N6P7Q8R9S0T1V312", created_at=add_seconds(START, 5))
    store.submit(first, district="D1")
    assert (
        store.answer(world, first["id"], option=first["options"][0]["id"], channel="web", principal=OWNER_P).outcome
        == "answered"
    )

    result = store.submit(later, district="D1")

    assert result.outcome == "accepted" and result.card_id == later["id"]
    assert [c["id"] for c in store.list_for_world(world, principal=OWNER_P)] == [later["id"]]


# --------------------------------------------------------------------------------------------------------------------
# 2. QuestionWait claim races, through the API (harness half: services/harness/tests)


def test_FR_HIL_10_a_different_answer_after_a_commit_then_raise_resolves_the_wait_and_no_default_follows(
    repo_root, flows, monkeypatch
):
    """Answer A (the owner, "person") commits and then its caller sees a failure (503). Answer B, another role with
    different data but the same derived event id, then meets the committed event (the writer refuses an id reused under
    other content). The question is resolved by A: the card closes AND the waiting unit resumes; nothing is left to
    answer at the card's deadline, so no second question.answered is ever written for it."""
    rf = _ask_flow(repo_root, (ASK, CLEAR[1], CLEAR[2]), timeout_s=6, monkeypatch=monkeypatch)
    flows.append(rf)
    start_and_approve(rf)
    wait_for(lambda: rf.events("question.routed"), what="question.routed")
    rf.quiet_stream()
    seen_at = time.monotonic()
    (card,) = needs_you_cards(rf)
    district = rf.events("question.routed")[0]["district"]
    original, state = rf.writer.append, {"raised": False}

    def append(world_id, event):
        committed = original(world_id, event)
        if event["type"] == "question.answered" and not state["raised"]:
            state["raised"] = True
            raise RuntimeError("the connection dropped after the event was committed")
        return committed

    monkeypatch.setattr(rf.writer, "append", append)

    first = rf.answer(card["id"], "o1")
    assert first.status_code == 503, first.text
    rf.as_member("u_lead_here", "team_lead", districts=(district,))
    t0 = time.monotonic()
    second = rf.answer(card["id"], "o2")

    assert second.status_code in (200, 400), second.text
    wait_for(lambda: "U1" in rf.runner.started_at, timeout=RESUME_BUDGET_S + 1, what="U1 to resume (resolved by A)")
    assert rf.runner.started_at["U1"] - t0 <= RESUME_BUDGET_S
    assert rf.runner.answers["U1"].answered_by in ("person", "team_lead"), "resumed by a person's answer, not a default"
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    time.sleep(max(0.0, seen_at + 7.5 - time.monotonic()))  # past the card's deadline (created + 6 s)
    assert [e["data"]["answered_by"] for e in rf.events("question.answered")] == ["person"], (
        "exactly one question.answered for the card, and none from its deadline"
    )
    assert rf.runner.ran.count("U1") == 1


# --------------------------------------------------------------------------------------------------------------------
# 3. a tick failure after a committed harness default


def test_FR_HIL_10_a_tick_failure_after_a_committed_deadline_default_does_not_fail_the_unit(
    repo_root, flows, monkeypatch
):
    """The harness applied the deadline default (question.answered, nudge, committed). `Run.emit` then asks the
    CardStore to close the card (`tick`) and that raises. The default is on the record: the waiting unit must resume
    with it, not be handed an error, and the run must not fail."""
    from tilo_api.cards import CardStore  # noqa: PLC0415

    def tick(self):
        raise RuntimeError("the card store is down")

    monkeypatch.setattr(CardStore, "tick", tick)
    rf = _ask_flow(repo_root, (ASK, CLEAR[1], CLEAR[2]), timeout_s=1, monkeypatch=monkeypatch)
    flows.append(rf)
    start_and_approve(rf)

    answered = wait_for(lambda: rf.events("question.answered"), timeout=8, what="the deadline default")
    wait_for(lambda: "U1" in rf.runner.started_at, timeout=4, what="U1 to resume with the default")

    assert (answered[0]["data"]["answered_by"], answered[0]["severity"]) == ("default", "nudge")
    assert rf.runner.answers["U1"].answered_by == "default"
    wait_for(lambda: rf.events("world.completed") or rf.events("world.failed"), what="the run to end")
    events = rf.quiet_stream()
    types = [e["type"] for e in events]
    assert types.count("world.completed") == 1 and "world.failed" not in types
    assert len([e for e in events if e["type"] == "question.answered"]) == 1
    assert rf.runner.ran.count("U1") == 1
