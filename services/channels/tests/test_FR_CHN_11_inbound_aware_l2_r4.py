"""FR-CHN-11, security review round 4 of PR #389 (ADR-0013; issue #298 "CHN-GATE-C", first bullet; BQ-265; PRD 10.4: T3
"money, contract or legal terms" always needs a person; L2 "the instruction is the approval" is for plain replies;
OB-01: an L2 send is queued only on a policy decision), end to end. The pure-function half is in
`test_FR_CHN_11_inbound_aware_l2_unit_r4.py`.

Round 4 holes, each as the replied-to body and as its Subject, for both kinds of Autopilot wiring (the legacy level hint
and the policy port; the fake policy is permissive on purpose, so only the inbound check can hold the card back):

  1. a family word cut by line breaks with a neighbour glued by a line break ("the\\ntrans\\nfer today");
  2. raw non-ASCII that NFKC would fold into plain ASCII ("re" + U+017F + "und", U+017F "ees", fullwidth letters, NBSP);
  3. single letters separated by times of day ("w 5pm i 5pm r 5pm e it today");
  and the controls: ordinary multi-line plain scheduling talk (dmarc=pass, clean Subject) still rides L2.

Fake clock, fake outbox, no network, no paid call. Non-ASCII characters are built with chr()."""

from __future__ import annotations

from typing import Any

import pytest
from _chn11_inbound_lib import (
    KINDS,
    PLAIN_INBOUND,
    PLAIN_SUBJECTS,
    R4_LETTERS_BETWEEN_TIMES,
    R4_NEWLINE_GLUE,
    R4_PLAIN_MULTILINE,
    R4_RAW_NON_ASCII_BODIES,
    R4_RAW_NON_ASCII_SUBJECTS,
    R4_SUBJECT_NEWLINE_GLUE,
    SCHEDULING_INBOUND,
    assert_rides_l2,
    assert_waits_for_a_person,
    make_l2,
)

YES = "Yes, confirmed."


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
# 1. Newline glue


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", R4_NEWLINE_GLUE, ids=[f"body{i}" for i in range(len(R4_NEWLINE_GLUE))])
def test_FR_CHN_11_inbound_aware_l2_r4_a_newline_glued_cut_word_in_the_body_never_rides_l2(
    kind: str, inbound: str
) -> None:
    _waits(kind, inbound)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "subject", R4_SUBJECT_NEWLINE_GLUE, ids=[f"subject{i}" for i in range(len(R4_SUBJECT_NEWLINE_GLUE))]
)
def test_FR_CHN_11_inbound_aware_l2_r4_a_newline_glued_cut_word_in_the_subject_never_rides_l2(
    kind: str, subject: str
) -> None:
    _waits(kind, subject=subject)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", R4_SUBJECT_NEWLINE_GLUE[:4])
def test_FR_CHN_11_inbound_aware_l2_r4_a_re_prefixed_newline_glued_subject_never_rides_l2(
    kind: str, subject: str
) -> None:
    _waits(kind, subject="Re: " + subject)


# ---------------------------------------------------------------------------
# 2. Raw non-ASCII is never plain


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "inbound", R4_RAW_NON_ASCII_BODIES, ids=[f"body{i}" for i in range(len(R4_RAW_NON_ASCII_BODIES))]
)
def test_FR_CHN_11_inbound_aware_l2_r4_a_raw_non_ascii_body_never_rides_l2(kind: str, inbound: str) -> None:
    _waits(kind, inbound)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "subject", R4_RAW_NON_ASCII_SUBJECTS, ids=[f"subject{i}" for i in range(len(R4_RAW_NON_ASCII_SUBJECTS))]
)
def test_FR_CHN_11_inbound_aware_l2_r4_a_raw_non_ascii_subject_never_rides_l2(kind: str, subject: str) -> None:
    _waits(kind, subject=subject)


# ---------------------------------------------------------------------------
# 3. Single letters separated by times of day


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", R4_LETTERS_BETWEEN_TIMES, ids=["wire", "transfer"])
def test_FR_CHN_11_inbound_aware_l2_r4_single_letters_between_times_in_the_body_never_ride_l2(
    kind: str, inbound: str
) -> None:
    _waits(kind, inbound)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", R4_LETTERS_BETWEEN_TIMES, ids=["wire", "transfer"])
def test_FR_CHN_11_inbound_aware_l2_r4_single_letters_between_times_in_the_subject_never_ride_l2(
    kind: str, subject: str
) -> None:
    _waits(kind, subject=subject)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", ["See you at 5\tpm.", "See you at 5\npm.", "Are you free at 2:30\tpm tomorrow?"])
def test_FR_CHN_11_inbound_aware_l2_r4_a_time_with_a_tab_or_newline_before_pm_never_rides_l2(
    kind: str, inbound: str
) -> None:
    _waits(kind, inbound)


# ---------------------------------------------------------------------------
# Controls: ordinary multi-line plain scheduling talk still rides L2


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", R4_PLAIN_MULTILINE + PLAIN_INBOUND[:3], ids=lambda t: t[:20])
def test_FR_CHN_11_inbound_aware_l2_r4_ordinary_multi_line_plain_talk_still_rides_l2(kind: str, inbound: str) -> None:
    h, p, _ = _card(kind, inbound)
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("subject", PLAIN_SUBJECTS)
def test_FR_CHN_11_inbound_aware_l2_r4_a_plain_subject_still_rides_l2(kind: str, subject: str) -> None:
    h, p, _ = _card(kind, subject=subject)
    assert_rides_l2(h, p)
