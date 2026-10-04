"""FR-CHN-10 acceptance tests: recipients and reply headers come from the thread and the user, never from model
output (PRD 11.4 Threading: "Replies stay in the thread with correct reply headers; reply-to-sender by default";
Formats: adding any recipient, attaching files or forwarding is T3, so drafting never does it, FR-CHN-12).
API pinned in API_FR_CHN_10.md.
"""

from __future__ import annotations

import pytest
from _chn10_lib import Msg, answer, bare, case_rig, draft_case, load_drafting_cases, make_rig, needs_drafting
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

CLEAN = "Hi,\n\nThanks, noted.\n\nBest regards,\nSarah"
MAILBOX = "ops@harborview.example"
CASES = load_drafting_cases()


def _participants(msg: Msg) -> set[str]:
    return {bare(a) for a in [msg.sender, *msg.to, *msg.cc]} - {MAILBOX}


def test_FR_CHN_10_reply_goes_to_the_sender_only_by_default() -> None:
    rig = make_rig()
    thread, _ = rig.thread(
        sender="David Miller <David.Miller@HarrierCharters.example>",
        to=[MAILBOX, "frank.surveyor@maritimesurveys.example"],
        cc=["sarah.chen@harborview.example"],
        answers=[answer(CLEAN)],
    )

    d = rig.draft(thread).draft  # no mode given: reply-to-sender (PRD 11.4)

    assert d.mode == "reply"
    assert d.to == ("david.miller@harriercharters.example",)  # bare address, no display name, lower case
    assert d.cc == () and d.bcc == () and d.attachments == ()


def test_FR_CHN_10_reply_all_keeps_exactly_the_thread_participants() -> None:
    rig = make_rig()
    thread, _ = rig.thread(
        sender="Megan Torres <megan.torres@pacificboating.example>",
        to=[MAILBOX, "Frank <frank.surveyor@maritimesurveys.example>"],
        cc=["sarah.chen@harborview.example", "OPS@harborview.example"],
        answers=[answer(CLEAN)],
    )

    d = rig.draft(thread, mode="reply_all").draft

    assert "megan.torres@pacificboating.example" in d.to
    assert set(d.to) | set(d.cc) == {
        "megan.torres@pacificboating.example",
        "frank.surveyor@maritimesurveys.example",
        "sarah.chen@harborview.example",
    }
    assert MAILBOX not in d.to + d.cc  # never to the user's own mailbox
    assert len(d.to + d.cc) == len(set(d.to + d.cc))  # no duplicates
    assert d.bcc == () and d.attachments == ()


def test_FR_CHN_10_reply_to_header_never_adds_a_recipient() -> None:
    # A Reply-To naming an address outside the thread would be a new recipient, which is T3 (PRD 11.4 Formats,
    # 16.2): drafting replies to the sender and leaves any change of recipient to a person (FR-CHN-12).
    rig = make_rig()
    thread, _ = rig.thread(
        sender="Billing <accounts@pacificfasteners.example>",
        headers={"Reply-To": "remit@pacificfasteners-billing.example"},
        answers=[answer(CLEAN)],
    )

    d = rig.draft(thread).draft

    assert d.to == ("accounts@pacificfasteners.example",)
    assert "remit@pacificfasteners-billing.example" not in d.to + d.cc + d.bcc


def test_FR_CHN_10_reply_headers_come_from_the_message_replied_to() -> None:
    rig = make_rig()
    first = Msg(
        message_id="m-first",
        sender="David Miller <david.miller@harriercharters.example>",
        subject="Engine tune-up scheduling and estimate",
        body="Hi Harborview, can Marcus come by this Friday afternoon?",
        to=[MAILBOX],
    )
    ours = Msg(
        message_id="m-ours",
        sender=MAILBOX,
        subject="Re: Engine tune-up scheduling and estimate",
        body="Hi David, which time on Friday suits you?",
        to=["david.miller@harriercharters.example"],
        headers={"References": "<m-first@mail.example>", "In-Reply-To": "<m-first@mail.example>"},
    )
    thread, _ = rig.thread(
        subject="Re: Engine tune-up scheduling and estimate",
        body="Any time after 1 PM works for us.",
        headers={"References": "<m-first@mail.example> <m-ours@mail.example>"},
        earlier=[first, ours],
        answers=[answer(CLEAN)],
    )
    last = thread.messages[-1].as_message()

    d = rig.draft(thread).draft

    assert d.thread_id == thread.thread_id
    assert d.subject == "Re: Engine tune-up scheduling and estimate"  # never "Re: Re: ..."
    assert d.in_reply_to == last["headers"]["Message-ID"]
    assert d.references.split() == ["<m-first@mail.example>", "<m-ours@mail.example>", last["headers"]["Message-ID"]]
    assert d.to == ("david.miller@harriercharters.example",)


def test_FR_CHN_10_reply_is_to_the_latest_message_not_sent_by_the_user() -> None:
    rig = make_rig()
    inbound = Msg(
        message_id="m-in",
        sender="Elena Rostova <elena.rostova@cascadeyachts.example>",
        subject="Haul-out reservation",
        body="Hi Sarah, can we book our winter haul-out for Tuesday, November 3rd?",
        to=[MAILBOX],
    )
    thread, _ = rig.thread(
        sender=f"Harborview Ops <{MAILBOX}>",
        to=["elena.rostova@cascadeyachts.example"],
        cc=[],
        subject="Re: Haul-out reservation",
        body="Hi Elena, let me check the haul-out calendar.",
        earlier=[inbound],
        answers=[answer(CLEAN)],
    )

    d = rig.draft(thread).draft

    assert d.to == ("elena.rostova@cascadeyachts.example",)
    assert d.in_reply_to == "<m-in@mail.example>"
    assert d.subject == "Re: Haul-out reservation"


def test_FR_CHN_10_reply_subject_gets_one_re_prefix() -> None:
    rig = make_rig()
    thread, _ = rig.thread(subject="Delivery delay notification", answers=[answer(CLEAN)])
    assert rig.draft(thread).draft.subject == "Re: Delivery delay notification"

    rig = make_rig()
    thread, _ = rig.thread(subject="RE: Delivery delay notification", answers=[answer(CLEAN)])
    assert rig.draft(thread).draft.subject == "RE: Delivery delay notification"


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_FR_CHN_10_eval_case_recipients_within_the_thread_and_ground_truth(case) -> None:
    # PRD 19.2 E-MAIL "threading and recipient rules"; the eval check `recipients_within` uses the thread's
    # participants as its allowlist (evals/tests/test_PRD_19_2_e_mail_cases.py).
    rig, _ = case_rig(case, answer(case.clean))

    d = draft_case(rig, case).draft

    last = case.thread.last_inbound(case.mailbox)
    participants = {bare(a) for a in [last.sender, *last.to, *last.cc]} - {case.mailbox}
    assert d.to[0] == bare(last.sender)
    assert set(d.to) | set(d.cc) <= participants
    if case.mode == "reply":
        assert d.to == (bare(last.sender),) and d.cc == ()
    else:
        assert set(d.to) | set(d.cc) == participants
    assert d.bcc == () and d.attachments == ()
    assert d.in_reply_to == last.as_message()["headers"]["Message-ID"]


ADDRESS = st.from_regex(r"[a-z]{2,8}\.[a-z]{2,8}@[a-z]{3,9}\.example", fullmatch=True)
RECIPIENT_KEYS = st.dictionaries(
    st.sampled_from(["to", "cc", "bcc", "reply_to", "forward_to", "recipients", "attachments", "add_recipients"]),
    st.lists(ADDRESS, max_size=4),
    max_size=6,
)


@needs_drafting
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    sender=ADDRESS,
    to=st.lists(ADDRESS, max_size=3),
    cc=st.lists(ADDRESS, max_size=3),
    mode=st.sampled_from(["reply", "reply_all"]),
    extra=RECIPIENT_KEYS,
)
def test_FR_CHN_10_property_no_draft_adds_a_recipient(sender, to, cc, mode, extra) -> None:
    # FR-CHN-12's invariant at the drafting step: whatever the model returns, the draft's recipients are a subset
    # of the replied message's participants, with the sender first, no Bcc and no attachments.
    rig = make_rig()
    thread, _ = rig.thread(sender=sender, to=[MAILBOX, *to], cc=cc, answers=[answer(CLEAN, **extra)])
    last = thread.messages[-1]

    result = rig.draft(thread, mode=mode)

    assert result.status == "ready"
    d = result.draft
    allowed = _participants(last)
    assert d.to[0] == bare(sender)
    assert set(d.to) | set(d.cc) <= allowed
    assert d.bcc == () and d.attachments == ()
    if mode == "reply":
        assert d.to == (bare(sender),) and d.cc == ()
