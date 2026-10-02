"""FR-CHN-09 acceptance test, offline: "Pilot: >= 85% agreement with the user's own labels after day 1" (PRD 11.6).

A pilot number cannot be proven in CI. These tests pin how it is computed from labels (`pilot_agreement`) and run
the correction loop on the 30 E-MAIL triage cases (PRD 19.2): a model that is wrong on 9 of them gives 70% on day
two with no corrections, and >= 85% once the user's day-one corrections are learned. Definition (BQ-TBD in
API_FR_CHN_09.md): labelled messages first triaged at least 24 h after the user's Autopilot start; agreement is
the first category given equal to the user's label; category only.
"""

from __future__ import annotations

import pytest
from _chn09_lib import (
    CATEGORIES,
    DAY_S,
    USER,
    answer,
    bare_address,
    case_mail,
    load_triage_cases,
    make_rig,
    triage_module,
    wrong_category,
)
from hypothesis import given, settings
from hypothesis import strategies as st

T_START = 1_790_931_600.0
CASES = load_triage_cases()
# The scripted model is wrong on these 9 (30%): each sender appears once in the set, so a sender rule learned on
# day one cannot be confused with another case's label.
WRONG_IDS = frozenset(
    {
        "E-MAIL-01",
        "E-MAIL-04",
        "E-MAIL-07",
        "E-MAIL-10",
        "E-MAIL-13",
        "E-MAIL-19",
        "E-MAIL-22",
        "E-MAIL-26",
        "E-MAIL-28",
    }
)


def _record(i: int, predicted: str, label: str | None, triaged_at: float) -> dict:
    return {"message_id": f"m-{i}", "triaged_at": triaged_at, "predicted": predicted, "label": label}


def _day_two(n: int) -> float:
    return T_START + DAY_S + 60.0 * n


def test_FR_CHN_09_target_and_warmup_are_the_prd_numbers() -> None:
    mod = triage_module()
    assert mod.PILOT_AGREEMENT_TARGET == 0.85
    assert mod.PILOT_WARMUP_S == 86_400


def test_FR_CHN_09_agreement_of_17_in_20_meets_the_85_percent_target() -> None:
    records = [_record(i, "fyi", "fyi", _day_two(i)) for i in range(17)]
    records += [_record(100 + i, "fyi", "needs_reply", _day_two(i)) for i in range(3)]

    report = triage_module().pilot_agreement(records, started_at=T_START)

    assert (report.agreed, report.labelled) == (17, 20)
    assert report.rate == pytest.approx(0.85)
    assert report.meets_target is True


def test_FR_CHN_09_agreement_of_16_in_19_misses_the_target() -> None:
    records = [_record(i, "needs_action", "needs_action", _day_two(i)) for i in range(16)]
    records += [_record(100 + i, "needs_action", "fyi", _day_two(i)) for i in range(3)]

    report = triage_module().pilot_agreement(records, started_at=T_START)

    assert (report.agreed, report.labelled) == (16, 19)
    assert report.rate == pytest.approx(16 / 19)
    assert report.meets_target is False


def test_FR_CHN_09_day_one_and_unlabelled_mail_are_not_counted() -> None:
    boundary = T_START + DAY_S
    records = [
        _record(1, "fyi", "needs_reply", T_START + 10),  # day one: not counted
        _record(2, "fyi", "needs_reply", boundary - 0.001),  # still day one
        _record(3, "fyi", "fyi", boundary),  # the first instant after day one counts
        _record(4, "fyi", None, boundary + 5),  # unlabelled: silence is not agreement
        _record(5, "suspicious", "fyi", boundary + 9),
    ]

    report = triage_module().pilot_agreement(records, started_at=T_START)

    assert (report.agreed, report.labelled) == (1, 2)
    assert report.rate == pytest.approx(0.5)


def test_FR_CHN_09_no_labels_gives_no_rate_and_no_pass() -> None:
    report = triage_module().pilot_agreement([_record(1, "fyi", None, _day_two(1))], started_at=T_START)
    assert (report.agreed, report.labelled, report.rate, report.meets_target) == (0, 0, None, False)


@settings(max_examples=100, deadline=None)
@given(
    rows=st.lists(
        st.tuples(
            st.sampled_from(CATEGORIES),
            st.one_of(st.none(), st.sampled_from(CATEGORIES)),
            st.floats(min_value=T_START, max_value=T_START + 3 * DAY_S, allow_nan=False),
        ),
        max_size=40,
    )
)
def test_FR_CHN_09_property_rate_is_agreed_over_labelled_after_day_one(rows: list) -> None:
    records = [_record(i, p, lab, t) for i, (p, lab, t) in enumerate(rows)]
    counted = [(p, lab) for p, lab, t in rows if lab is not None and t >= T_START + DAY_S]
    agreed = sum(p == lab for p, lab in counted)

    report = triage_module().pilot_agreement(records, started_at=T_START)

    assert (report.agreed, report.labelled) == (agreed, len(counted))
    if counted:
        assert report.rate == pytest.approx(agreed / len(counted))
        assert report.meets_target is (agreed / len(counted) >= 0.85)
    else:
        assert report.rate is None and report.meets_target is False


def test_FR_CHN_09_records_keep_the_first_prediction_and_the_users_label() -> None:
    rig = make_rig()
    corrected, _ = rig.mail(reply=answer("fyi", "low"))
    untouched, _ = rig.mail(sender="jake.turner@coastalmarineelec.example", reply=answer("needs_action", "normal"))
    triaged_at = rig.clock()
    rig.svc.triage(USER, corrected.message_id)
    rig.svc.triage(USER, untouched.message_id)
    rig.clock.advance(600)

    rig.svc.correct(USER, corrected.message_id, category="needs_reply")
    rig.svc.triage(USER, corrected.message_id)  # now the user's label, but the prediction stays what it was

    records = {r["message_id"]: r for r in rig.svc.agreement_records(USER)}
    assert records[corrected.message_id]["predicted"] == "fyi"
    assert records[corrected.message_id]["label"] == "needs_reply"
    assert records[corrected.message_id]["triaged_at"] == pytest.approx(triaged_at)
    assert records[untouched.message_id]["predicted"] == "needs_action"
    assert records[untouched.message_id]["label"] is None


def test_FR_CHN_09_wrong_set_senders_are_unique_in_the_fixture() -> None:
    senders = [bare_address(c.sender) for c in CASES]
    for case in CASES:
        if case.id in WRONG_IDS:
            assert senders.count(bare_address(case.sender)) == 1, case.id
    assert len(WRONG_IDS) == 9 and WRONG_IDS <= {c.id for c in CASES}


def _pilot(*, learn: bool):
    """Day one: triage the 30 cases; with `learn`, the user corrects every wrong one. Day two: the same senders
    send the same kind of mail again, the model makes the same mistakes, and the user labels every message once the
    day's mail is triaged."""
    rig = make_rig()
    started_at = rig.clock()

    def reply(case) -> str:
        category = wrong_category(case.category) if case.id in WRONG_IDS else case.category
        return answer(category, case.priority)

    rig.clock.advance(3600)
    for case in CASES:
        mail, _ = case_mail(rig, case, reply=reply(case), suffix="-d1")
        result = rig.svc.triage(USER, mail.message_id)
        if learn and result.category != case.category:
            rig.svc.correct(USER, mail.message_id, category=case.category)

    rig.clock.advance(DAY_S)
    day_two = [(case, case_mail(rig, case, reply=reply(case), suffix="-d2")[0]) for case in CASES]
    for _, mail in day_two:
        rig.svc.triage(USER, mail.message_id)
    for case, mail in day_two:  # the user's own labels, given after the day's mail was triaged
        rig.svc.correct(USER, mail.message_id, category=case.category)

    return triage_module().pilot_agreement(rig.svc.agreement_records(USER), started_at=started_at)


def test_FR_CHN_09_without_corrections_day_two_agreement_misses_the_target() -> None:
    report = _pilot(learn=False)
    assert report.labelled == 30  # day-one messages are not counted
    assert report.agreed == 21
    assert report.meets_target is False


def test_FR_CHN_09_learned_corrections_lift_day_two_agreement_to_at_least_85_percent() -> None:
    report = _pilot(learn=True)
    assert report.labelled == 30
    assert report.rate is not None and report.rate >= 0.85
    # A rule never downgrades a model "suspicious" (security review r1 of #211, BQ-132): the two newsletter
    # cases the model wrongly calls suspicious stay suspicious on day two, so 28 of 30 agree, not 30.
    assert report.agreed == 28
    assert report.meets_target is True


def test_FR_CHN_09_ground_truth_answers_agree_fully_on_the_eval_set() -> None:
    rig = make_rig()
    started_at = rig.clock()
    rig.clock.advance(DAY_S)
    mails = [(case, case_mail(rig, case, reply=answer(case.category, case.priority))[0]) for case in CASES]
    for _, mail in mails:
        rig.svc.triage(USER, mail.message_id)
    for case, mail in mails:
        rig.svc.correct(USER, mail.message_id, category=case.category)

    report = triage_module().pilot_agreement(rig.svc.agreement_records(USER), started_at=started_at)

    assert (report.agreed, report.labelled, report.meets_target) == (30, 30, True)
