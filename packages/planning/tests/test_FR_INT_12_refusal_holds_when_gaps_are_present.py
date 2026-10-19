"""FR-INT-12 must not regress under FR-INT-15 (supplement 2026-10-05 section 4: "A hard refusal is only for safety or
policy (FR-INT-12)"; BQ-INT15-3: a task with a safe and an unsafe part is refused in full). The FR-INT-12 acceptance
is "Eval refusal set: 100% refused with an alternative offered" and the ordinary set is never refused. These tests
re-run both sets with the new reply shape: the Director now may also return `out_of_scope` gaps, and a valid gap list
must neither soften a refusal nor turn an ordinary task into one. Existing FR-INT-12 tests are untouched.
"""

from __future__ import annotations

import pytest
from _fr_int_12_lib import load_refusal_set
from _fr_int_15_lib import StageDirector, gap_item, gap_reply, make_router


def brief():
    import tilo_planning.brief as module  # noqa: PLC0415

    return module


def refusal():
    import tilo_planning.refusal as module  # noqa: PLC0415

    return module


VALID_GAPS = [gap_item("money_movement", "Pay the supplier"), gap_item("calls_and_chat", "Phone the supplier")]


def control_accepts_gaps() -> None:
    """A plain valid gap reply is accepted, so a negative test below cannot pass just because the code does not know
    `out_of_scope` at all."""
    director = StageDirector(default=gap_reply(VALID_GAPS))
    assert len(brief().extract_brief("Compare suppliers.", router=make_router(director)).gaps) == 2


def test_FR_INT_12_the_refusal_set_stays_100_percent_refused_when_every_reply_also_carries_valid_gaps():
    r = refusal()
    policy = r.load_refusal_policy()
    cases = load_refusal_set()["out_of_policy"]
    assert len(cases) >= 20
    categories = list(policy.categories)
    replies = {
        case["task"]: gap_reply(VALID_GAPS, out_of_policy=categories[i % len(categories)].id)
        for i, case in enumerate(cases)
    }
    director = StageDirector(replies)
    router = make_router(director)

    refused = 0
    for i, case in enumerate(cases):
        expected = categories[i % len(categories)]
        with pytest.raises(r.TaskRefused) as raised:
            brief().extract_brief(case["task"], router=router)
        assert (raised.value.reason, raised.value.alternative) == (expected.reason, expected.alternative), case["id"]
        refused += 1

    assert refused == len(cases), f"{refused} of {len(cases)} refused"
    assert len(director.calls) == len(cases), "one Director call per refusal"


def test_FR_INT_12_the_refusal_set_stays_100_percent_refused_when_the_refusal_id_is_in_out_of_scope_only():
    """The dodge: out_of_policy null, the refusal id put in the gap list instead. Still refused, same text."""
    r = refusal()
    cases = load_refusal_set()["out_of_policy"]
    categories = list(r.load_refusal_policy().categories)
    replies = {
        case["task"]: gap_reply(
            [*VALID_GAPS, gap_item(categories[i % len(categories)].id, "Do it")], out_of_policy=None
        )
        for i, case in enumerate(cases)
    }
    router = make_router(StageDirector(replies))

    for i, case in enumerate(cases):
        expected = categories[i % len(categories)]
        with pytest.raises(r.TaskRefused) as raised:
            brief().extract_brief(case["task"], router=router)
        assert raised.value.category == expected.id, case["id"]
        assert (raised.value.reason, raised.value.alternative) == (expected.reason, expected.alternative), case["id"]


def test_FR_INT_12_the_ordinary_set_is_never_refused_and_an_empty_gap_list_changes_nothing():
    cases = load_refusal_set()["in_policy"]
    director = StageDirector({case["task"]: gap_reply([], out_of_policy=None) for case in cases})
    router = make_router(director)

    for case in cases:
        result = brief().extract_brief(case["task"], router=router)
        assert result.brief["goal"] and result.gaps == (), case["id"]


def test_FR_INT_12_a_safe_part_never_saves_an_unsafe_task_the_whole_task_is_refused():
    """BQ-INT15-3: the safe deliverable and the valid gaps are in the reply, and nothing but the refusal comes out."""
    r = refusal()
    chosen = r.load_refusal_policy().categories[0]
    reply = gap_reply(VALID_GAPS, out_of_policy=chosen.id)
    assert reply["deliverables"], "the model also gave a perfectly good safe part"
    director = StageDirector(default=reply)

    with pytest.raises(r.TaskRefused) as raised:
        brief().extract_brief("Log in with my password, then summarise my prices.", router=make_router(director))

    assert raised.value.category == chosen.id
    assert len(director.calls) == 1, "no approaches, no plan, no questions follow a refusal"


def test_FR_INT_12_an_unknown_out_of_policy_category_still_fails_closed_gaps_do_not_rescue_it():
    control_accepts_gaps()
    director = StageDirector(default=gap_reply(VALID_GAPS, out_of_policy="made_up_category"))

    with pytest.raises(brief().BriefExtractionError) as raised:
        brief().extract_brief("Anything at all", router=make_router(director))

    assert not isinstance(raised.value, refusal().TaskRefused)


@pytest.mark.parametrize("value", ["", "  ", 7, True, ["credential_handling"], {"id": "credential_handling"}])
def test_FR_INT_12_a_malformed_out_of_policy_value_never_yields_a_brief_even_with_valid_gaps(value):
    control_accepts_gaps()
    director = StageDirector(default=gap_reply(VALID_GAPS, out_of_policy=value))

    with pytest.raises(brief().BriefExtractionError):
        brief().extract_brief("Anything at all", router=make_router(director))


def test_FR_INT_12_a_refusal_is_not_a_gap_the_refusal_text_never_appears_on_a_brief_result():
    """A task with only gaps (no refusal) never carries a refusal category or a refusal's reason."""
    r = refusal()
    refusal_texts = {t for c in r.load_refusal_policy().categories for t in (c.reason, c.alternative)}
    director = StageDirector(default=gap_reply(VALID_GAPS))

    result = brief().extract_brief("Compare suppliers and pay the best one.", router=make_router(director))

    shown = {t for g in result.gaps for t in (g.reason, g.alternative, g.skip_line())}
    assert shown.isdisjoint(refusal_texts)
    assert not any(g.category in {c.id for c in r.load_refusal_policy().categories} for g in result.gaps)
