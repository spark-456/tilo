"""FR-CHN-11: the pure signal of the message a draft answers (ADR-0013; issue #298 "CHN-GATE-C", first bullet;
BQ-265). Proposed API: `tilo_channels.autopilot_t3.inbound_signal(text: str) -> frozenset[str]`.

Decided behaviour: the replied-to (inbound) message carries a signal when it has a word of the money, legal or
commitment families (the same ones `t3_content_signal` uses) or is obfuscated or over SIGNAL_CAP (fail closed). Unlike
a draft body, an inbound message is free text: it is NOT held to the L2 allowlist, so a link, a digit or a word off
the scheduling list is no signal on its own ("unlisted" is never returned). The result is a subset of
{"money", "legal", "commitment", "obfuscated"}; empty means a clean inbound message. No model, no network.

The PRD does not name the families for inbound mail: this follows `t3_content_signal` (PRD 10.4 T3 "money, contract or
legal terms"), the stated default, and is listed in the ticket notes. Invisible and look-alike characters are built
with chr() so no editor or tool can silently rewrite them."""

from __future__ import annotations

import pytest
from _chn11_inbound_lib import (
    COMMITMENT_INBOUND,
    LEGAL_INBOUND,
    MONEY_INBOUND,
    SCHEDULING_INBOUND,
    SIGNAL_INBOUND,
    inbound_signal,
    needs_inbound_signal,
    t3_module,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ALLOWED = {"money", "legal", "commitment", "obfuscated"}
ZWSP, ZWJ, SHY, BIDI_OVERRIDE = chr(0x200B), chr(0x200D), chr(0x00AD), chr(0x202E)
CYR_A, CYR_I, EMOJI = chr(0x0430), chr(0x0456), chr(0x1F642)
FDFA = chr(0xFDFA)  # NFKC expands it 18-fold
FULLWIDTH_REFUND = "".join(chr(0xFF00 + ord(c) - 0x20) for c in "refund")

CLEAN = [
    "",
    SCHEDULING_INBOUND,
    "Friday 2pm works for us. See you then.",
    "Thanks for the update, talk soon.",
    # An inbound message is free text: digits, a link, names and words off the scheduling list are no signal.
    "Could Marcus bring the 2 tarps to dock 14 on Thursday at 3pm? Map: https://harriercharters.example/dock-14",
    "Hello Sarah, the rigging inspection moved to the harbour office, room 7. Cheers, David Miller",
    "x " * 4_000,  # long, but under the cap
]
OBFUSCATED = [
    f"Friday{ZWSP} 2pm works for us.",  # zero-width space inside an otherwise clean message
    f"Fr{CYR_I}day 2pm works for us.",  # Cyrillic i
    f"See you {BIDI_OVERRIDE}Friday.",  # bidi override
    f"See you Fri{SHY}day.",  # soft hyphen
    f"Friday {EMOJI} works for us.",  # an emoji
]


def test_FR_CHN_11_inbound_signal_exists_in_autopilot_t3() -> None:
    assert callable(getattr(t3_module(), "inbound_signal", None)), "autopilot_t3.inbound_signal(text) is missing"


@pytest.mark.parametrize(
    ("family", "text"),
    [("money", t) for t in MONEY_INBOUND]
    + [("legal", t) for t in LEGAL_INBOUND]
    + [("commitment", t) for t in COMMITMENT_INBOUND],
)
def test_FR_CHN_11_inbound_signal_money_legal_and_commitment_words_are_named(family: str, text: str) -> None:
    signal = inbound_signal(text)
    assert isinstance(signal, frozenset)
    assert family in signal


def test_FR_CHN_11_inbound_signal_money_transfer_request_gives_money() -> None:
    # The motivating case: "Yes, confirmed." answers this, and its own body is clean.
    assert "money" in inbound_signal("Can you confirm the transfer of $5,000 to our bank account today?")


@pytest.mark.parametrize("text", CLEAN)
def test_FR_CHN_11_inbound_signal_clean_scheduling_talk_has_no_signal(text: str) -> None:
    assert inbound_signal(text) == frozenset()


def test_FR_CHN_11_inbound_signal_is_never_unlisted() -> None:
    # The L2 allowlist is for what Tilo SAYS, not for what it is told: a long message full of off-list words is clean.
    text = "The harbourmaster says the bilge pump, the tarps and the rigging need a look on Thursday at 3pm. " * 20
    assert inbound_signal(text) == frozenset()


@pytest.mark.parametrize("text", OBFUSCATED)
def test_FR_CHN_11_inbound_signal_obfuscated_text_fails_closed(text: str) -> None:
    assert "obfuscated" in inbound_signal(text)


@pytest.mark.parametrize(
    "word",
    [f"ref{ZWSP}und", f"p{CYR_A}yment", f"c{ZWJ}ontract", FULLWIDTH_REFUND],
    ids=["zwsp", "cyrillic", "zwj", "wide"],
)
def test_FR_CHN_11_inbound_signal_hidden_or_look_alike_signal_word_still_signals(word: str) -> None:
    assert inbound_signal(f"Please sort the {word} today.")


def test_FR_CHN_11_inbound_signal_over_the_cap_fails_closed_and_the_cap_itself_is_clean() -> None:
    cap = t3_module().SIGNAL_CAP
    filler = "see you friday. "
    at_cap = (filler * (cap // len(filler) + 1))[:cap]
    assert len(at_cap) == cap and inbound_signal(at_cap) == frozenset()
    assert "obfuscated" in inbound_signal(at_cap + " ")
    assert "obfuscated" in inbound_signal(filler * 2_000)  # 32 000 characters


def test_FR_CHN_11_inbound_signal_an_expanding_character_run_fails_closed() -> None:
    # NFKC expands U+FDFA 18-fold: it stops once the output is too big and fails closed, like the body signal.
    assert "obfuscated" in inbound_signal(FDFA * 2_000)


# ---------------------------------------------------------------------------
# BQ-265 fix pass (security review round 1, finding 2): an amount or a number word is "money" in an inbound message
# even with no money word around it. Only `inbound_signal` does this: a draft is held to the L2 allowlist already.

# Pinned: each must signal "money". (The first has no money word; "account" alone is not one.)
NUMBER_AMOUNT = [
    "Can you confirm the 5,000 to our account today?",
    "Please confirm the five thousand for the boat by Friday.",
    "Can you confirm we're square at 12000?",
    "Please confirm you'll take care of the 3 lakh tomorrow.",
    "Can you confirm you're on board with the 10% cut?",
]
NUMBER_WORDS = ["hundred", "thousand", "million", "billion", "lakh", "crore"]
AMOUNT_SHAPES = ["1,200", "12,50,000", "2.50", "0.5", "250", "12000", "1500000", "10%", "50 %"]
# Digits that are still scheduling talk: small counts, a time of day, a 4-digit year.
CLEAN_DIGITS = [
    "Could Marcus bring the 2 tarps to dock 14 on Thursday at 3pm?",
    "Let us meet at 14:30 on Friday.",
    "Friday at 2:30pm works, room 7.",
    "The inspection is on 12 Oct 2026.",
    "See you in 2027.",
]


@pytest.mark.parametrize("text", NUMBER_AMOUNT)
def test_FR_CHN_11_inbound_signal_an_amount_or_number_word_with_no_money_word_is_money(text: str) -> None:
    assert "money" in inbound_signal(text)


@pytest.mark.parametrize("word", NUMBER_WORDS)
def test_FR_CHN_11_inbound_signal_each_number_word_is_money(word: str) -> None:
    assert "money" in inbound_signal(f"Can you confirm the two {word} for the boat?")
    assert "money" in inbound_signal(f"Please confirm the {word.upper()} by Friday.")  # case does not matter


@pytest.mark.parametrize("shape", AMOUNT_SHAPES)
def test_FR_CHN_11_inbound_signal_each_amount_shape_is_money(shape: str) -> None:
    # A digit group with a thousands separator or a decimal part, a run of 3+ digits that is not a time of day or a
    # 4-digit year, and "%".
    assert "money" in inbound_signal(f"Can you confirm {shape} for the boat by Friday?")


@pytest.mark.parametrize("text", CLEAN_DIGITS)
def test_FR_CHN_11_inbound_signal_small_counts_times_and_years_stay_clean(text: str) -> None:
    assert inbound_signal(text) == frozenset()


@pytest.mark.parametrize("text", NUMBER_AMOUNT[1:4] + ["Sounds good, 10%.", "That is a hundred percent fine."])
def test_FR_CHN_11_amount_shapes_are_an_inbound_only_signal_a_drafts_money_signal_is_unchanged(text: str) -> None:
    # t3_content_signal (what a draft's own body is held to) is not widened: those words and digits only make a
    # draft "unlisted" (already off L2), never "money".
    assert "money" not in t3_module().t3_content_signal(text)


# ASCII splits (round 1, finding 3): a separator inside a signal word hides it from the word families.
TAB = chr(9)
SPLIT_WORDS = {
    "spaces_wire": "w i r e",
    "spaces_transfer": "t r a n s f e r",
    "middle_dot": f"re{chr(0xB7)}fund",
    "pipe": "tr|ansfer",
    "slash": "trans/fer",
    "tilde": "trans~fer",
    "plus": "trans+fer",
    "apostrophe": "trans'fer",
    "tab": f"trans{TAB}fer",
}


@pytest.mark.parametrize("word", list(SPLIT_WORDS.values()), ids=list(SPLIT_WORDS))
def test_FR_CHN_11_inbound_signal_ascii_split_signal_words_still_signal(word: str) -> None:
    assert inbound_signal(f"Please confirm the {word} today.")


# ---------------------------------------------------------------------------
# Invariants (Hypothesis)

_TEXT = st.one_of(
    st.text(max_size=300),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz ,.!?\n$0123456789-_*", max_size=300),
    st.lists(st.sampled_from([*SIGNAL_INBOUND, *CLEAN[1:4], f"a{ZWSP}b", CYR_A]), max_size=6).map(" ".join),
)
_FAST = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@needs_inbound_signal
@given(text=_TEXT)
@_FAST
def test_FR_CHN_11_inbound_signal_property_deterministic_and_within_its_four_names(text: str) -> None:
    first = inbound_signal(text)
    assert isinstance(first, frozenset) and first <= ALLOWED
    assert inbound_signal(text) == first


@needs_inbound_signal
@given(text=_TEXT)
@_FAST
def test_FR_CHN_11_inbound_signal_property_is_the_body_signal_without_the_allowlist_plus_money_shapes(
    text: str,
) -> None:
    # "Same word families as t3_content_signal", obfuscation and cap included, never "unlisted". Whatever the draft-side
    # signal finds is still found. What the inbound side adds (an amount shape or number word is "money"; a separator
    # or spread-out letters no longer hide a word, so "legal" or "commitment" can appear too: "s i g n", "con/tract")
    # is only ever one of the four inbound family names. (Round 2, blocker E: the old `<= {"money"}` was false.)
    body = t3_module().t3_content_signal(text) - {"unlisted"}
    signal = inbound_signal(text)
    assert body <= signal
    assert signal - body <= ALLOWED
    assert "unlisted" not in signal


@needs_inbound_signal
@given(text=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", max_size=300))
@_FAST
def test_FR_CHN_11_inbound_signal_property_with_no_separator_the_only_addition_is_money(text: str) -> None:
    # ASCII letters and digits only: there is nothing to drop or spread, so beyond the draft-side signal the only
    # thing the inbound side can add is "money" (an amount shape or a number word). True by construction.
    body = t3_module().t3_content_signal(text) - {"unlisted"}
    signal = inbound_signal(text)
    assert body <= signal
    assert signal - body <= {"money"}


@needs_inbound_signal
@given(before=st.text(max_size=120), phrase=st.sampled_from(SIGNAL_INBOUND), after=st.text(max_size=120))
@_FAST
def test_FR_CHN_11_inbound_signal_property_a_signal_sentence_is_never_missed(
    before: str, phrase: str, after: str
) -> None:
    # Wherever it sits in the message and whatever surrounds it, the message is not clean.
    assert inbound_signal(f"{before}\n{phrase}\n{after}")
