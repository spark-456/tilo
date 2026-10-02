"""FR-CHN-09 acceptance tests: every mail lands in exactly one of the five PRD 11.3 categories with a priority,
deterministically for a scripted model answer. API pinned in API_FR_CHN_09.md.

PRD 11.3: categories needs a reply, needs an action, FYI, newsletter or promotion, suspicious; priority from
sender importance, deadline language, thread history and the user's VIP list. PRD 19.2 E-MAIL: triage agreement
with ground truth >= 85%. The category and priority spellings are the E-MAIL ground truth's (proposed BQ row in
API_FR_CHN_09.md); "a score" is read as the three ground-truth levels.
"""

from __future__ import annotations

import pytest
from _chn09_lib import (
    CATEGORIES,
    OTHER_USER,
    PRIORITIES,
    USER,
    answer,
    case_mail,
    load_triage_cases,
    make_rig,
    triage_module,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

TRIAGE_CASES = load_triage_cases()


def test_FR_CHN_09_fixture_set_is_the_thirty_e_mail_triage_cases() -> None:
    # Guards the fixture the agreement tests rely on: 30 labelled cases, 6 per category (PRD 19.2).
    assert len(TRIAGE_CASES) == 30
    assert {c.category for c in TRIAGE_CASES} == set(CATEGORIES)
    assert {c.priority for c in TRIAGE_CASES} <= set(PRIORITIES)


def test_FR_CHN_09_module_pins_five_categories_and_three_priorities() -> None:
    mod = triage_module()
    assert len(mod.CATEGORIES) == 5
    assert set(mod.CATEGORIES) == set(CATEGORIES)
    assert len(mod.PRIORITIES) == 3
    assert set(mod.PRIORITIES) == set(PRIORITIES)


@pytest.mark.parametrize("case", TRIAGE_CASES, ids=[c.id for c in TRIAGE_CASES])
def test_FR_CHN_09_each_eval_case_lands_in_its_one_category_with_priority(case) -> None:
    rig = make_rig()
    mail, _ = case_mail(rig, case, reply=answer(case.category, case.priority))

    result = rig.svc.triage(USER, mail.message_id)

    assert isinstance(result, triage_module().TriageResult)
    assert result.message_id == mail.message_id
    assert result.category in CATEGORIES
    assert result.priority in PRIORITIES
    assert result.category == case.category
    if not result.flagged:  # a flagged mail (E-MAIL-30 carries an injection) has no pinned priority
        assert result.priority == case.priority


@pytest.mark.parametrize("priority", PRIORITIES)
@pytest.mark.parametrize("category", CATEGORIES)
def test_FR_CHN_09_a_valid_model_answer_is_taken_as_given(category: str, priority: str) -> None:
    rig = make_rig()
    mail, _ = rig.mail(reply=answer(category, priority))

    result = rig.svc.triage(USER, mail.message_id)

    assert (result.category, result.priority, result.source, result.flagged) == (category, priority, "model", False)


def test_FR_CHN_09_instance_is_the_fr_chn_08_triage_callable() -> None:
    # FR-CHN-08's MailWatcher calls `triage(user_id, message_id)` (API_FR_CHN_08.md).
    rig = make_rig()
    mail, _ = rig.mail(reply=answer("needs_action", "high"))

    result = rig.svc(USER, mail.message_id)

    assert (result.category, result.priority) == ("needs_action", "high")
    assert rig.svc.triage(USER, mail.message_id) == result


def test_FR_CHN_09_same_mail_and_answer_give_the_same_result_on_any_instance() -> None:
    results = []
    for _ in range(3):
        rig = make_rig()
        mail, _ = rig.mail(message_id="m-fixed", reply=answer("needs_reply", "high"))
        results.append(rig.svc.triage(USER, mail.message_id))
    assert results[0] == results[1] == results[2]


def test_FR_CHN_09_vip_sender_gets_high_priority_and_keeps_its_category() -> None:
    # PRD 11.3 Priority: "the user's VIP list". Default (BQ-TBD): a VIP address always gets high.
    rig = make_rig()
    rig.svc.add_vip(USER, "Elena.Rostova@CascadeYachts.example")
    vip, _ = rig.mail(sender="Elena Rostova <elena.rostova@cascadeyachts.example>", reply=answer("fyi", "low"))
    plain, _ = rig.mail(sender="Jake Turner <jake.turner@coastalmarineelec.example>", reply=answer("fyi", "low"))
    other, _ = rig.mail(
        user_id=OTHER_USER, sender="Elena Rostova <elena.rostova@cascadeyachts.example>", reply=answer("fyi", "low")
    )

    result = rig.svc.triage(USER, vip.message_id)
    assert (result.category, result.priority) == ("fyi", "high")
    assert rig.svc.triage(USER, plain.message_id).priority == "low"
    assert rig.svc.triage(OTHER_USER, other.message_id).priority == "low"  # VIP lists are per user


_MODEL_TEXT = st.one_of(
    st.text(max_size=200),
    st.builds(answer, st.sampled_from(CATEGORIES + ("urgent", "", "FYI")), st.sampled_from(PRIORITIES + ("p0", ""))),
    st.builds(answer, st.one_of(st.none(), st.integers(), st.lists(st.sampled_from(CATEGORIES), max_size=2))),
    st.sampled_from(["", "null", "[]", "{}", "{", '{"category": "fyi"}', "needs_reply"]),
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(text=_MODEL_TEXT)
def test_FR_CHN_09_property_any_model_answer_gives_one_allowed_category_and_priority(text: str) -> None:
    outcomes = []
    for _ in range(2):  # two fresh instances: deterministic for the same answer
        rig = make_rig()
        mail, _ = rig.mail(message_id="m-prop", reply=text)
        result = rig.svc.triage(USER, mail.message_id)
        assert result.category in CATEGORIES
        assert result.priority in PRIORITIES
        outcomes.append((result.category, result.priority, result.source, result.flagged))
    assert outcomes[0] == outcomes[1]
