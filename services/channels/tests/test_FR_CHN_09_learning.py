"""FR-CHN-09 acceptance tests: learning from corrections (PRD 11.3 "every correction (relabel, 'don't ask me
about these') becomes a preference in P7 and changes future triage"; PRD 13.1 Preferences layer).

The PRD names no mechanism, so the tests take the simplest deterministic default (BQ-TBD in API_FR_CHN_09.md): a
correction becomes a per-user rule on the sender's bare address, ahead of the model; the latest one wins.
"""

from __future__ import annotations

import pytest
from _chn09_lib import (
    CATEGORIES,
    OTHER_USER,
    PRIORITIES,
    USER,
    answer,
    make_rig,
)
from hypothesis import given, settings
from hypothesis import strategies as st

SENDER = "David Miller <david.miller@harriercharters.example>"


def test_FR_CHN_09_relabel_changes_later_mail_from_the_same_sender() -> None:
    rig = make_rig()
    first, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))
    assert rig.svc.triage(USER, first.message_id).category == "fyi"

    rig.svc.correct(USER, first.message_id, category="needs_action")

    # same address, other case and display name, different subject and body; the model still says fyi
    later, _ = rig.mail(
        sender="D. Miller (Harrier) <David.Miller@HarrierCharters.example>",
        subject="Fuel dock invoice",
        body="The fuel dock invoice for September is attached.",
        reply=answer("fyi", "low"),
    )
    result = rig.svc.triage(USER, later.message_id)

    assert result.category == "needs_action"
    assert result.source == "rule"


def test_FR_CHN_09_corrected_message_itself_takes_the_users_label() -> None:
    rig = make_rig()
    mail, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))
    rig.svc.triage(USER, mail.message_id)

    rig.svc.correct(USER, mail.message_id, category="needs_reply")
    result = rig.svc.triage(USER, mail.message_id)

    assert (result.category, result.source) == ("needs_reply", "user")


def test_FR_CHN_09_correction_survives_a_restart() -> None:
    rig = make_rig()
    first, _ = rig.mail(sender=SENDER, reply=answer("newsletter_promo", "low"))
    rig.svc.triage(USER, first.message_id)
    rig.svc.correct(USER, first.message_id, category="needs_reply", priority="high")

    restarted = rig.new_triage()  # a new instance over the same stores
    later, _ = rig.mail(sender=SENDER, reply=answer("newsletter_promo", "low"))
    result = restarted.triage(USER, later.message_id)

    assert (result.category, result.priority) == ("needs_reply", "high")


def test_FR_CHN_09_correction_touches_no_other_sender_and_no_other_user() -> None:
    rig = make_rig()
    first, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))
    rig.svc.triage(USER, first.message_id)
    rig.svc.correct(USER, first.message_id, category="needs_action")

    other_sender, _ = rig.mail(sender="jake.turner@coastalmarineelec.example", reply=answer("fyi", "low"))
    other_user, _ = rig.mail(user_id=OTHER_USER, sender=SENDER, reply=answer("fyi", "low"))

    assert rig.svc.triage(USER, other_sender.message_id).category == "fyi"
    assert rig.svc.triage(OTHER_USER, other_user.message_id).category == "fyi"


def test_FR_CHN_09_display_name_cannot_borrow_another_senders_rule() -> None:
    rig = make_rig()
    first, _ = rig.mail(sender="boss@harborview.example", reply=answer("fyi", "low"))
    rig.svc.triage(USER, first.message_id)
    rig.svc.correct(USER, first.message_id, category="needs_reply", priority="high")

    spoof, _ = rig.mail(sender='"boss@harborview.example" <payroll@evil-relay.example>', reply=answer("fyi", "low"))
    result = rig.svc.triage(USER, spoof.message_id)

    assert (result.category, result.priority, result.source) == ("fyi", "low", "model")


def test_FR_CHN_09_latest_correction_for_a_sender_wins() -> None:
    rig = make_rig()
    a, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))
    b, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))
    rig.svc.triage(USER, a.message_id)
    rig.svc.triage(USER, b.message_id)
    rig.svc.correct(USER, a.message_id, category="needs_action")
    rig.svc.correct(USER, b.message_id, category="newsletter_promo")

    later, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))

    assert rig.svc.triage(USER, later.message_id).category == "newsletter_promo"


def test_FR_CHN_09_priority_correction_applies_to_later_mail() -> None:
    rig = make_rig()
    first, _ = rig.mail(sender=SENDER, reply=answer("needs_action", "low"))
    rig.svc.triage(USER, first.message_id)
    rig.svc.correct(USER, first.message_id, priority="high")

    later, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))
    result = rig.svc.triage(USER, later.message_id)

    assert result.priority == "high"
    assert result.category == "fyi"  # a priority-only correction leaves the category to the model


def test_FR_CHN_09_dont_ask_me_about_these_stops_needs_reply_from_that_sender() -> None:
    rig = make_rig()
    first, _ = rig.mail(sender=SENDER, reply=answer("needs_reply", "normal"))
    rig.svc.triage(USER, first.message_id)

    rig.svc.mute(USER, first.message_id)
    later, _ = rig.mail(sender=SENDER, reply=answer("needs_reply", "high"))
    result = rig.svc.triage(USER, later.message_id)

    assert result.category != "needs_reply"
    assert result.category == "fyi"  # BQ-TBD default: goes to the digest (PRD 11.3 Delivery)


@pytest.mark.parametrize(
    "kwargs",
    [{"category": "urgent"}, {"priority": "critical"}, {}, {"category": None, "priority": None}],
    ids=["unknown_category", "unknown_priority", "nothing", "both_none"],
)
def test_FR_CHN_09_invalid_correction_is_refused_and_changes_nothing(kwargs: dict) -> None:
    rig = make_rig()
    mail, _ = rig.mail(sender=SENDER, reply=answer("fyi", "low"))
    rig.svc.triage(USER, mail.message_id)
    prefs, results = rig.preferences.dump(), rig.results.dump()

    with pytest.raises(ValueError):
        rig.svc.correct(USER, mail.message_id, **kwargs)

    assert (rig.preferences.dump(), rig.results.dump()) == (prefs, results)


def test_FR_CHN_09_only_the_user_writes_preferences() -> None:
    rig = make_rig()
    for category in CATEGORIES:
        mail, _ = rig.mail(reply=answer(category, "normal"))
        rig.svc.triage(USER, mail.message_id)
    assert rig.preferences.writes == 0

    rig.svc.correct(USER, mail.message_id, category="fyi")
    assert rig.preferences.writes >= 1


def test_FR_CHN_09_stores_hold_no_subject_or_body() -> None:
    # PRD 13.1 "never cached: email bodies"; 16.5 the preference keeps settings, not emails.
    rig = make_rig()
    subject, body = "Kestrel hull survey quote", "Our surveyor flagged blistering on the Kestrel port quarter."
    mail, _ = rig.mail(sender=SENDER, subject=subject, body=body, reply=answer("needs_reply", "normal"))
    rig.svc.triage(USER, mail.message_id)
    rig.svc.correct(USER, mail.message_id, category="needs_action", priority="high")
    rig.svc.mute(USER, mail.message_id)
    rig.svc.add_vip(USER, "david.miller@harriercharters.example")

    for dump in (rig.preferences.dump(), rig.results.dump()):
        for text in ("Kestrel", "blistering", "hull survey"):
            assert text not in dump


_SENDERS = ("a@one.example", "b@two.example", "c@three.example")


@settings(max_examples=50, deadline=None)
@given(
    corrections=st.lists(st.tuples(st.sampled_from(_SENDERS), st.sampled_from(CATEGORIES)), max_size=8),
    model_category=st.sampled_from(CATEGORIES),
    model_priority=st.sampled_from(PRIORITIES),
)
def test_FR_CHN_09_property_later_mail_follows_the_latest_correction_else_the_model(
    corrections: list[tuple[str, str]], model_category: str, model_priority: str
) -> None:
    rig = make_rig()
    expected: dict[str, str] = {}
    for sender, category in corrections:
        mail, _ = rig.mail(sender=sender, reply=answer("fyi", "low"))
        rig.svc.triage(USER, mail.message_id)
        rig.svc.correct(USER, mail.message_id, category=category)
        expected[sender] = category

    for sender in _SENDERS:
        later, _ = rig.mail(sender=sender.upper(), reply=answer(model_category, model_priority))
        result = rig.svc.triage(USER, later.message_id)
        assert result.category == expected.get(sender, model_category)
        assert result.source == ("rule" if sender in expected else "model")
