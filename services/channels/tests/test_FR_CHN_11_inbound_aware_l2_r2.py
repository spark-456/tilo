"""FR-CHN-11, security review round 2 of PR #389 (ADR-0013; issue #298 "CHN-GATE-C", first bullet; BQ-265; PRD 10.4: T3
"money, contract or legal terms" always needs a person; L2 "the instruction is the approval" is for plain replies;
OB-01: an L2 send is queued only on a policy decision), end to end. Round 2 failed the round-1 fix on five counts; the
pure-function half is in `test_FR_CHN_11_inbound_aware_l2_unit_r2.py`. Here the card must stay off L2 (level L1, window
0, no policy.applied, no outbox entry, nothing sent however long the clock runs) for both kinds of Autopilot wiring
(the legacy level hint and the policy port; the fake policy is permissive on purpose, so only the inbound check can
hold the card back):

  A. a punctuation mark of ANY kind inside a signal word of the replied-to message ("Please confirm the trans,fer
     today.", "trans" + en dash + "fer"); every ASCII punctuation character; single letters spread by punctuation;
  B. mixed spread-and-split forms ("w i r-e", "s-i g n", ...);
  C. magnitude suffixes ("the 5m", "the 50 K", "the 3 lacs", "the 10L") and the new number words;
  D. mutant killers: a `dmarc` token with no verdict beside a pass ("dmarc=pass; dmarc") fails closed, and a bare
     4-digit amount ("the 5000", "1999", "2000") is money while 2020-2039 are still years;
  and the controls: plain scheduling talk with ordinary punctuation, small counts and times still rides L2.

Fake clock, fake outbox, no network, no paid call. Non-ASCII characters are built with chr()."""

from __future__ import annotations

import string
from typing import Any

import pytest
from _chn10_lib import AUTH_PASS
from _chn11_inbound_lib import (
    KINDS,
    SCHEDULING_INBOUND,
    assert_rides_l2,
    assert_waits_for_a_person,
    make_l2,
)

YES = "Yes, confirmed."
AUTH = "Authentication-Results"
EN_DASH, EM_DASH, BULLET, KATAKANA_DOT = chr(0x2013), chr(0x2014), chr(0x2022), chr(0x30FB)
ASCII_PUNCT = list(string.punctuation)


def _sentence(word: str) -> str:
    return f"Please confirm the {word} today."


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
# A. Punctuation is a class


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "word", ["trans,fer", "trans" + EN_DASH + "fer", "re" + EM_DASH + "fund", "con" + BULLET + "tract"]
)
def test_FR_CHN_11_inbound_aware_l2_a_punctuation_split_signal_word_never_rides_l2(kind: str, word: str) -> None:
    _waits(kind, _sentence(word))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("p", ASCII_PUNCT, ids=[f"U+{ord(c):04X}" for c in ASCII_PUNCT])
def test_FR_CHN_11_inbound_aware_l2_every_ascii_punctuation_mark_inside_a_word_keeps_the_reply_off_l2(
    kind: str, p: str
) -> None:
    _waits(kind, _sentence(f"trans{p}fer"))
    _waits(kind, _sentence(f"con{p}tract"))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "p", [EN_DASH, EM_DASH, chr(0x2010), chr(0x2011), BULLET, chr(0x2027), KATAKANA_DOT, chr(0xFF65)]
)
def test_FR_CHN_11_inbound_aware_l2_every_unicode_mark_inside_a_word_keeps_the_reply_off_l2(kind: str, p: str) -> None:
    _waits(kind, _sentence(f"re{p}fund"))
    _waits(kind, _sentence(f"con{p}tract"))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("p", [",", "?", "@", "#", "&", "(", EN_DASH, KATAKANA_DOT])
def test_FR_CHN_11_inbound_aware_l2_single_letters_spread_by_punctuation_never_ride_l2(kind: str, p: str) -> None:
    _waits(kind, _sentence(p.join("wire")))
    _waits(kind, _sentence(p.join("transfer")))


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_punctuation_split_word_in_the_subject_never_rides_l2(kind: str) -> None:
    _waits(kind, subject="Please confirm the trans,fer today")


# ---------------------------------------------------------------------------
# B. Mixed spread-and-split forms

MIXED = ["w i r-e", "w i r.e", "w-i r e", "t r a n s-f e r", "c o n-t r a c t", "s-i g n", "p-a y"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("word", MIXED)
def test_FR_CHN_11_inbound_aware_l2_a_mixed_spread_and_split_word_never_rides_l2(kind: str, word: str) -> None:
    _waits(kind, _sentence(word))


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_mixed_spread_and_split_word_in_the_subject_never_rides_l2(kind: str) -> None:
    _waits(kind, subject="Please confirm the w i r-e today")


# ---------------------------------------------------------------------------
# C. Magnitude suffixes and number words

SUFFIXED = ["5m", "2bn", "3cr", "5mn", "50 K", "5 k", "3 lacs", "10L"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("amount", SUFFIXED)
def test_FR_CHN_11_inbound_aware_l2_a_magnitude_suffix_amount_never_rides_l2(kind: str, amount: str) -> None:
    _waits(kind, f"Can you confirm the {amount} by Friday?")


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_a_magnitude_suffix_amount_in_the_subject_never_rides_l2(kind: str) -> None:
    _waits(kind, subject="Can you confirm the 5m by Friday?")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("word", ["lac", "lacs", "mil", "mn", "bn", "cr"])
def test_FR_CHN_11_inbound_aware_l2_each_new_number_word_never_rides_l2(kind: str, word: str) -> None:
    _waits(kind, f"Can you confirm the two {word} for the boat?")


# ---------------------------------------------------------------------------
# D. Mutant killers

DMARC_WITHOUT_A_VERDICT = {
    "pass_then_bare_token": "mx.example; dmarc=pass; dmarc",
    "pass_then_empty_verdict": "mx.example; dmarc=pass; dmarc=",
    "pass_then_bare_token_and_more": "mx.example; dmarc=pass header.from=a.example; dmarc (no result)",
    "upper_case": "MX.EXAMPLE; DMARC=PASS; DMARC",
    "bare_token_first": "mx.example; dmarc; dmarc=pass",
    "two_bare_tokens_and_a_pass": "mx.example; dmarc; dmarc; dmarc=pass",
}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("value", list(DMARC_WITHOUT_A_VERDICT.values()), ids=list(DMARC_WITHOUT_A_VERDICT))
def test_FR_CHN_11_inbound_aware_l2_a_dmarc_token_without_a_verdict_beside_a_pass_fails_closed(
    kind: str, value: str
) -> None:
    _waits(kind, headers={AUTH: value})


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_two_dmarc_passes_still_ride_l2(kind: str) -> None:
    # Every verdict is a pass and every dmarc token has one: a control for the stricter rule above.
    h, p, _ = _card(
        kind, headers={AUTH: "mx.example; dmarc=pass header.from=a.example; dmarc=pass header.from=b.example"}
    )
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("amount", ["5000", "1999", "2000"])
def test_FR_CHN_11_inbound_aware_l2_a_bare_four_digit_amount_never_rides_l2(kind: str, amount: str) -> None:
    _waits(kind, f"Can you confirm the {amount}?")
    _waits(kind, f"Can you confirm the {amount} for the boat by Friday?")


# ---------------------------------------------------------------------------
# Controls: plain scheduling talk still rides L2

CLEAN = [
    "Could Marcus bring the 2 tarps to dock 14 on Thursday at 3pm?",
    "Hello Sarah, the rigging inspection moved to room 7. Cheers, David",
    "Let us meet at 14:30 on Friday.",
    "Could Marcus bring 2 kayaks and 3 buckets to dock 14?",
    "Friday, 2pm - dock 14 (north side); bring 2 tarps!",
    "Could we meet at the drop-off/pick-up point? Thanks - David",
    "See you in 2026, or 2039 at the latest.",
    "Okay: Thursday [3pm], room 7 {harbour office}; cheers, David.",
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("inbound", CLEAN, ids=[f"clean{i}" for i in range(len(CLEAN))])
def test_FR_CHN_11_inbound_aware_l2_plain_scheduling_talk_with_ordinary_punctuation_still_rides_l2(
    kind: str, inbound: str
) -> None:
    h, p, _ = _card(kind, inbound)
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_inbound_aware_l2_the_default_authentication_still_rides_l2(kind: str) -> None:
    h, p, _ = _card(kind, headers={AUTH: AUTH_PASS})
    assert_rides_l2(h, p)
