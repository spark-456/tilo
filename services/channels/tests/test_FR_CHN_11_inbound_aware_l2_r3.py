"""FR-CHN-11, security review round 3 of PR #389 (ADR-0013; issue #298 "CHN-GATE-C", first bullet; BQ-265; PRD 10.4: T3
"money, contract or legal terms" always needs a person; L2 "the instruction is the approval" is for plain replies;
OB-01: an L2 send is queued only on a policy decision), end to end. The pure-function half is in
`test_FR_CHN_11_inbound_aware_l2_unit_r3.py`.

Round 3 failed the denylist again, so the approach is redesigned (decided 6 Oct, by the orchestrator under the user's
standing delegation; strictly more conservative than the user's 5 Oct decision "a money, legal or spoofed inbound
makes the reply T3"): L2 needs the replied-to message's body AND Subject to be free of any `inbound_signal` AND
`inbound_plain` (only ASCII letters, spaces, newlines, `. , ? ! :` before a space, contractions and times of day). The
card stays off L2 (level L1, window 0, no policy.applied, no outbox entry, nothing sent however long the clock runs)
for both kinds of Autopilot wiring (the legacy level hint and the policy port; the fake policy is permissive on
purpose, so only the inbound check can hold the card back):

  1. every exact round-3 failure, as the body and as the Subject; two through the real Drafter;
  2. a digit that is not a time of day, a link, a hyphen or any other character off the allowlist, with no signal word;
  3. only the replied-to message counts: earlier messages may be as non-plain as they like, and a non-plain replied-to
     message counts after plain earlier ones;
  and the controls: plain scheduling talk (clean Subject, dmarc=pass) still rides L2.

Fake clock, fake outbox, no network, no paid call. Non-ASCII characters are built with chr()."""

from __future__ import annotations

from typing import Any

import pytest
from _chn10_lib import AUTH_PASS, USER, Msg, answer
from _chn11_inbound_lib import (
    KINDS,
    PLAIN_INBOUND,
    PLAIN_SUBJECTS,
    R3_BODY_FAILURES,
    R3_SUBJECT_FAILURES,
    SCHEDULING_INBOUND,
    assert_rides_l2,
    assert_waits_for_a_person,
    make_l2,
)
from _chn11_lib import INSTRUCTION, MAILBOX, context
from _chn_wire4_lib import fresh_ulid
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

YES = "Yes, confirmed."
AUTH = "Authentication-Results"
BODY_IDS = [f"body{i}" for i in range(len(R3_BODY_FAILURES))]
SUBJECT_FAILURES = R3_BODY_FAILURES + R3_SUBJECT_FAILURES
SUBJECT_IDS = [f"subject{i}" for i in range(len(SUBJECT_FAILURES))]


def _card(kind: str, inbound: str = SCHEDULING_INBOUND, body: str = YES, **kw: Any):
    """(rig, preview, context) of a ready `body` draft answering the thread's last message."""
    h = make_l2(kind)
    thread = h.thread(inbound, **kw)
    p, ctx, _ = h.preview(thread, body)
    return h, p, ctx


def _waits(kind: str, inbound: str = SCHEDULING_INBOUND, **kw: Any) -> None:
    h, p, ctx = _card(kind, inbound, **kw)
    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# 1. The exact round-3 failures, as the body and as the Subject


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", R3_BODY_FAILURES, ids=BODY_IDS)
def test_FR_CHN_11_inbound_aware_l2_r3_a_round_three_failure_in_the_body_never_rides_l2(
    kind: str, inbound: str
) -> None:
    _waits(kind, inbound)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", SUBJECT_FAILURES, ids=SUBJECT_IDS)
def test_FR_CHN_11_inbound_aware_l2_r3_a_round_three_failure_in_the_subject_never_rides_l2(
    kind: str, subject: str
) -> None:
    _waits(kind, subject=subject)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", SUBJECT_FAILURES[:6] + R3_SUBJECT_FAILURES)
def test_FR_CHN_11_inbound_aware_l2_r3_a_re_prefixed_round_three_failure_never_rides_l2(
    kind: str, subject: str
) -> None:
    _waits(kind, subject="Re: " + subject)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "inbound",
    [
        "Please confirm the _transfer_ today.",
        "Please _sign_ the _contract_ today.",
        "the_transfer",
        "5million",
        "the.trans.fer",
    ],
)
def test_FR_CHN_11_inbound_aware_l2_r3_through_the_real_drafter_a_failure_in_the_body_waits_for_a_person(
    kind: str, inbound: str
) -> None:
    h = make_l2(kind)
    thread, _ = h.rig.thread(body=inbound, answers=(answer(YES),))
    ctx = context(thread, instruction=INSTRUCTION, instruction_id=fresh_ulid())
    result = h.rig.svc.draft(
        USER, instruction_id=ctx.instruction_id, thread_id=thread.thread_id, instruction=INSTRUCTION, mailbox=MAILBOX
    )
    assert result.status == "ready" and result.draft.body == YES, "test setup: the clean reply passes FR-CHN-10"
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", ["Re: _contract_ by Friday", "Re:con-tract", "Re:contract", "5million", "10/L"])
def test_FR_CHN_11_inbound_aware_l2_r3_through_the_real_drafter_a_failure_in_the_subject_waits_for_a_person(
    kind: str, subject: str
) -> None:
    h = make_l2(kind)
    thread, _ = h.rig.thread(subject=subject, answers=(answer(YES),))
    ctx = context(thread, instruction=INSTRUCTION, instruction_id=fresh_ulid())
    result = h.rig.svc.draft(
        USER, instruction_id=ctx.instruction_id, thread_id=thread.thread_id, instruction=INSTRUCTION, mailbox=MAILBOX
    )
    assert result.status == "ready" and result.draft.body == YES, "test setup: the clean reply passes FR-CHN-10"
    p = h.ap.preview(USER, ctx, result)
    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# 2. Text with no signal word that is simply not plain keeps the card off L2

NOT_PLAIN_NO_SIGNAL = [
    "Could Marcus bring the 2 tarps to dock 14 on Thursday at 3pm?",
    "Hi Sarah, are you free on Friday - or Saturday?",
    "Hi Sarah, are you free on Friday/Saturday?",
    "Hi Sarah, are you free on Friday (afternoon)?",
    "Hi Sarah, are you free on Friday?\n> Hi David, the boat is ready.",
    "See https://harriercharters.example/dock for the map.",
    "Mail david@harriercharters.example about Friday.",
    "Hi Sarah, are you free on Friday" + chr(0x2019) + "s afternoon?",
    "Hi Sarah, are you free on Friday" + chr(0x2026),
    "Hi Sarah,are you free on Friday?",
    "Hi Sarah, are you free on Friday?!",
    "Hi Sarah, are you free on Friday... or Saturday?",
    "Hi Sarah, ar'e you free on Friday?",
    "Hi Sarah, are y o u free on Friday?",
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", NOT_PLAIN_NO_SIGNAL, ids=[f"notplain{i}" for i in range(len(NOT_PLAIN_NO_SIGNAL))])
def test_FR_CHN_11_inbound_aware_l2_r3_a_body_that_is_not_plain_never_rides_l2(kind: str, inbound: str) -> None:
    _waits(kind, inbound)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "subject",
    [
        "Dock 14 on Thursday",
        "Engine tune-up scheduling",
        "Friday/Saturday",
        "Re: Friday (afternoon)",
        "Friday afternoon!!",
        "Re:Friday afternoon",
    ],
)
def test_FR_CHN_11_inbound_aware_l2_r3_a_subject_that_is_not_plain_never_rides_l2(kind: str, subject: str) -> None:
    _waits(kind, subject=subject)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_r3_a_plain_body_under_a_non_plain_subject_waits_and_the_reverse_too(
    kind: str,
) -> None:
    _waits(kind, SCHEDULING_INBOUND, subject="Dock 14")
    _waits(kind, "Can Marcus bring 2 tarps?", subject="Engine tuneup scheduling")


# ---------------------------------------------------------------------------
# 3. Only the replied-to message counts


def _earlier(body: str, subject: str, message_id: str = "m-earlier-r3") -> Msg:
    return Msg(
        message_id=message_id,
        sender="David Miller <david.miller@harriercharters.example>",
        subject=subject,
        body=body,
        headers={AUTH: AUTH_PASS},
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("body", "subject"),
    [
        ("Invoice 1234: see https://x.example/pay-now, 5,000 due _today_", "Re: _contract_ by Friday"),
        ("5million", "Re:con-tract"),
        ("the.trans.fer w i r e", "Dock 14"),
    ],
    ids=["risky_and_not_plain", "number", "split_words"],
)
def test_FR_CHN_11_inbound_aware_l2_r3_an_earlier_non_plain_message_does_not_matter(
    kind: str, body: str, subject: str
) -> None:
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND, earlier=(_earlier(body, subject),))
    assert (
        len(thread.messages) == 3
    )  # the bench rig starts every thread with the owner's own SENT note (ADR-0025 migration)
    p, _, _ = h.preview(thread, YES)
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", ["5million", "the_transfer", "Please _sign_ the _contract_ today.", "10/L"])
def test_FR_CHN_11_inbound_aware_l2_r3_a_non_plain_replied_to_message_counts_after_plain_earlier_ones(
    kind: str, inbound: str
) -> None:
    h = make_l2(kind)
    earlier = (
        _earlier("Hi Sarah, are you free on Friday?", "Friday afternoon", "m-a"),
        _earlier("Can Marcus come by?", "Re: Friday afternoon", "m-b"),
    )
    thread = h.thread(inbound, earlier=earlier)
    p, ctx, _ = h.preview(thread, YES)
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_r3_a_non_plain_subject_on_an_earlier_message_does_not_matter(kind: str) -> None:
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND, earlier=(_earlier("Hi Sarah, are you free?", "Re:con-tract"),))
    p, _, _ = h.preview(thread, YES)
    assert_rides_l2(h, p)


# ---------------------------------------------------------------------------
# Controls: plain scheduling talk with a clean Subject and dmarc=pass still rides L2


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", PLAIN_INBOUND, ids=[f"plain{i}" for i in range(len(PLAIN_INBOUND))])
def test_FR_CHN_11_inbound_aware_l2_r3_plain_scheduling_talk_still_rides_l2(kind: str, inbound: str) -> None:
    h, p, _ = _card(kind, inbound)
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", PLAIN_SUBJECTS)
def test_FR_CHN_11_inbound_aware_l2_r3_a_plain_subject_still_rides_l2(kind: str, subject: str) -> None:
    h, p, _ = _card(kind, subject=subject)
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_r3_plain_talk_without_dmarc_pass_still_waits_for_a_person(kind: str) -> None:
    # The allowlist does not replace the spoofing check: both are needed.
    _waits(kind, SCHEDULING_INBOUND, headers={AUTH: "mx.example; dmarc=fail header.from=harriercharters.example"})


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_r3_the_card_can_still_be_cancelled_inside_the_window_for_plain_talk(
    kind: str,
) -> None:
    h, p, _ = _card(kind, PLAIN_INBOUND[2])
    assert_rides_l2(h, p)
    assert h.ap.cancel(USER, p.card_id).status == "cancelled"
    h.clock.advance(120)
    h.outbox.dispatch_due()
    assert h.outbox.sent == []


# ---------------------------------------------------------------------------
# Invariant (Hypothesis): the window needs a plain body AND a plain subject (with a dmarc pass)

_BODIES = [*PLAIN_INBOUND, *R3_BODY_FAILURES[:8]]
_SUBJECTS = [*PLAIN_SUBJECTS, *R3_SUBJECT_FAILURES, "Dock 14", "Engine tune-up scheduling"]


@given(
    body=st.sampled_from(_BODIES),
    subject=st.sampled_from(_SUBJECTS),
    kind=st.sampled_from(KINDS),
)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_FR_CHN_11_inbound_aware_l2_r3_property_the_window_needs_a_plain_body_and_a_plain_subject(
    body: str, subject: str, kind: str
) -> None:
    h = make_l2(kind)
    thread = h.thread(body, subject=subject)
    p, ctx, _ = h.preview(thread, YES)
    if body in PLAIN_INBOUND and subject in PLAIN_SUBJECTS:
        assert_rides_l2(h, p)
    else:
        assert_waits_for_a_person(h, p, ctx)
