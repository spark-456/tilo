"""FR-CHN-11, security review round 2 of PR #389: `tilo_channels.autopilot_t3.inbound_signal(text)` (ADR-0013; issue
#298 "CHN-GATE-C", first bullet; BQ-265; PRD 10.4: T3 "money, contract or legal terms" needs a person; L2 is for plain
replies). The round-1 fix dropped a LIST of separators, so every character not on the list still hides a word. These
tests pin the fix as a class, and the three smaller blockers:

  A. Punctuation is a CLASS. Any run of characters that are neither letters, digits nor whitespace, between two
     letters or digits, must not hide a word: every ASCII punctuation character and the Unicode marks hyphen, non-
     breaking hyphen, en dash, em dash, bullet, hyphenation point, katakana middle dot and halfwidth katakana middle
     dot, in "trans?fer", "re?fund", "con?tract", "w?i?r?e", and with single letters spread apart by any of them.
  B. Mixed spread-and-split forms ("w i r-e", "w-i r e", "t r a n s-f e r", "s-i g n") signal too.
  C. Magnitude suffixes: a number, an optional space and k, m, mn, b, bn, cr, l, lac or lacs is money; lac, lacs, mil,
     mn, bn and cr are number words. Small counts, times of day and ordinary words that merely start with a suffix
     letter ("2 kayaks") stay clean.
  D. Mutant killers: a bare 4-digit amount is money (only 2020-2039 are years, by the rule in force), pinned here so a
     "any 4 digits is a year" mutant dies. (The dmarc half of D is in the end-to-end `_r2` file.)

Every non-ASCII character is built with chr(), never typed. No network, no model."""

from __future__ import annotations

import string

import pytest
from _chn11_inbound_lib import inbound_signal, needs_inbound_signal
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ASCII_PUNCT = list(string.punctuation)
UNICODE_MARKS = {
    "hyphen_2010": chr(0x2010),
    "non_breaking_hyphen_2011": chr(0x2011),
    "en_dash": chr(0x2013),
    "em_dash": chr(0x2014),
    "bullet_2022": chr(0x2022),
    "hyphenation_point_2027": chr(0x2027),
    "katakana_middle_dot_30fb": chr(0x30FB),
    "halfwidth_katakana_middle_dot_ff65": chr(0xFF65),
}
ALL_PUNCT = ASCII_PUNCT + list(UNICODE_MARKS.values())
assert len(ASCII_PUNCT) == 32 and len(ALL_PUNCT) == 40

# word -> the family it belongs to
SPLIT_WORDS = {"trans?fer": "money", "re?fund": "money", "con?tract": "legal", "w?i?r?e": "money"}
SPREAD_WORDS = {
    "transfer": "money",
    "refund": "money",
    "contract": "legal",
    "wire": "money",
    "payment": "money",
    "invoice": "money",
    "sign": "legal",
    "pay": "money",
}
_FAST = settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _sentence(word: str) -> str:
    return f"Please confirm the {word} today."


def _label(mark: str) -> str:
    return f"U+{ord(mark):04X}"


# ---------------------------------------------------------------------------
# A. Punctuation is a class


@pytest.mark.parametrize(("template", "family"), list(SPLIT_WORDS.items()), ids=list(SPLIT_WORDS))
def test_FR_CHN_11_inbound_signal_every_punctuation_mark_inside_a_signal_word_still_signals(
    template: str, family: str
) -> None:
    # Loops over EVERY ASCII punctuation character and the eight Unicode marks; names every one that hides the word.
    hidden = [_label(p) + repr(p) for p in ALL_PUNCT if not inbound_signal(_sentence(template.replace("?", p)))]
    assert not hidden, f"{template!r} hides its word behind: {hidden}"
    wrong_family = [
        _label(p) + repr(p) for p in ALL_PUNCT if family not in inbound_signal(_sentence(template.replace("?", p)))
    ]
    assert not wrong_family, f"{template!r} lost its {family} signal behind: {wrong_family}"


@pytest.mark.parametrize(("word", "family"), list(SPREAD_WORDS.items()), ids=list(SPREAD_WORDS))
def test_FR_CHN_11_inbound_signal_single_letters_spread_apart_by_any_punctuation_still_signal(
    word: str, family: str
) -> None:
    hidden = [_label(p) + repr(p) for p in ALL_PUNCT if family not in inbound_signal(_sentence(p.join(word)))]
    assert not hidden, f"{word!r} spread out hides its {family} signal behind: {hidden}"


@pytest.mark.parametrize(
    "run", [",,", "--", "?!", "...", "-_-", "*.*", "'\"", chr(0x2013) + "-", chr(0x2022) + chr(0xFF65)]
)
@pytest.mark.parametrize("template", list(SPLIT_WORDS))
def test_FR_CHN_11_inbound_signal_a_run_of_punctuation_inside_a_signal_word_still_signals(
    template: str, run: str
) -> None:
    assert SPLIT_WORDS[template] in inbound_signal(_sentence(template.replace("?", run)))


@pytest.mark.parametrize(
    "word", ["trans,fer", "trans" + chr(0x2013) + "fer", "refund".replace("n", "&n"), "con@tract", "pay#ment"]
)
def test_FR_CHN_11_inbound_signal_the_motivating_punctuation_splits_signal(word: str) -> None:
    assert inbound_signal(_sentence(word))


@pytest.mark.parametrize("p", ALL_PUNCT, ids=[_label(p) for p in ALL_PUNCT])
def test_FR_CHN_11_inbound_signal_punctuation_split_names_the_family_for_each_mark(p: str) -> None:
    # One id per mark, so a run shows exactly which characters are not yet treated as a separator.
    assert "money" in inbound_signal(_sentence(f"trans{p}fer"))
    assert "legal" in inbound_signal(_sentence(f"con{p}tract"))


CLEAN_WITH_PUNCTUATION = [
    "Friday, 2pm - dock 14 (north side); bring 2 tarps!",
    "Re: Friday afternoon... see you there, David.",
    "Could we meet at the drop-off/pick-up point? Thanks - David",
    "Let's meet at the office; it's fine, we're on for Friday at 3pm.",
    "Okay: Thursday [3pm], room 7 {harbour office}; cheers, David.",
    "Check-in is at 14:30; the e-mail with the map is coming. Thanks!",
]


@pytest.mark.parametrize("text", CLEAN_WITH_PUNCTUATION)
def test_FR_CHN_11_inbound_signal_ordinary_punctuation_in_scheduling_talk_stays_clean(text: str) -> None:
    assert inbound_signal(text) == frozenset()


@needs_inbound_signal
@given(
    word=st.sampled_from(["transfer", "refund", "contract", "wire", "payment", "invoice", "liability", "invoice"]),
    cut=st.integers(min_value=1, max_value=7),
    run=st.lists(st.sampled_from(ALL_PUNCT), min_size=1, max_size=4).map("".join),
)
@_FAST
def test_FR_CHN_11_inbound_signal_property_any_punctuation_run_inside_a_signal_word_signals(
    word: str, cut: int, run: str
) -> None:
    cut = min(cut, len(word) - 1)
    assert inbound_signal(_sentence(word[:cut] + run + word[cut:]))


@needs_inbound_signal
@given(
    word=st.sampled_from(list(SPREAD_WORDS)),
    seps=st.lists(
        st.text(alphabet=[" ", *ALL_PUNCT], min_size=1, max_size=3).filter(lambda s: s.strip(" ") or s == " "),
        min_size=8,
        max_size=8,
    ),
)
@_FAST
def test_FR_CHN_11_inbound_signal_property_single_letters_spread_by_any_mix_of_spaces_and_punctuation_signal(
    word: str, seps: list[str]
) -> None:
    # Between two single letters: a space, a punctuation mark, or any run mixing both.
    spread = word[0] + "".join(sep + ch for sep, ch in zip(seps, word[1:], strict=False))
    assert SPREAD_WORDS[word] in inbound_signal(_sentence(spread))


# ---------------------------------------------------------------------------
# B. Mixed spread-and-split forms

MIXED = ["w i r-e", "w i r.e", "w-i r e", "t r a n s-f e r", "c o n-t r a c t", "s-i g n", "p-a y"]


@pytest.mark.parametrize("word", MIXED)
def test_FR_CHN_11_inbound_signal_mixed_spread_and_split_forms_signal(word: str) -> None:
    assert inbound_signal(_sentence(word)), f"{word!r} hides its word"


@pytest.mark.parametrize(
    ("word", "family"),
    [
        ("w i r-e", "money"),
        ("t r a n s-f e r", "money"),
        ("c o n-t r a c t", "legal"),
        ("s-i g n", "legal"),
        ("p-a y", "money"),
        ("w-i r e", "money"),
        ("w i r.e", "money"),
    ],
)
def test_FR_CHN_11_inbound_signal_mixed_spread_and_split_forms_name_the_family(word: str, family: str) -> None:
    assert family in inbound_signal(_sentence(word))


# ---------------------------------------------------------------------------
# C. Magnitude suffixes

SUFFIXED = ["5m", "2bn", "3cr", "5mn", "50 K", "5 k", "3 lacs", "10L", "2 b", "7 cr", "4 lac", "12 L", "6 bn", "9mn"]
NEW_NUMBER_WORDS = ["lac", "lacs", "mil", "mn", "bn", "cr"]
CLEAN_COUNTS = [
    "Could Marcus bring the 2 tarps to dock 14 on Thursday at 3pm?",
    "Hello Sarah, the rigging inspection moved to room 7. Cheers, David",
    "Let us meet at 14:30 on Friday.",
    "Friday at 3pm works for us.",
    "Could Marcus bring 2 kayaks and 3 buckets to dock 14?",
    "Please bring 10 lanes of rope to room 7 by 3pm.",
]


@pytest.mark.parametrize("amount", SUFFIXED)
def test_FR_CHN_11_inbound_signal_a_number_with_a_magnitude_suffix_is_money(amount: str) -> None:
    assert "money" in inbound_signal(f"Can you confirm the {amount} by Friday?")


@pytest.mark.parametrize("amount", ["5m", "2bn", "3cr", "5mn", "50 K", "3 lacs", "10L"])
def test_FR_CHN_11_inbound_signal_a_magnitude_suffix_with_other_wording_is_money(amount: str) -> None:
    assert "money" in inbound_signal(f"Could you confirm the {amount}?")
    assert "money" in inbound_signal(f"We agreed {amount}, right?")
    assert "money" in inbound_signal(f"{amount}")


@pytest.mark.parametrize("word", NEW_NUMBER_WORDS)
def test_FR_CHN_11_inbound_signal_each_new_number_word_is_money(word: str) -> None:
    assert "money" in inbound_signal(f"Can you confirm the two {word} for the boat?")
    assert "money" in inbound_signal(f"Please confirm the {word.upper()} by Friday.")  # case does not matter


@pytest.mark.parametrize("text", CLEAN_COUNTS + CLEAN_WITH_PUNCTUATION)
def test_FR_CHN_11_inbound_signal_small_counts_times_and_plain_words_stay_clean_beside_the_suffix_rule(
    text: str,
) -> None:
    assert inbound_signal(text) == frozenset()


# ---------------------------------------------------------------------------
# D. Mutant killers: a bare 4-digit amount is money, only 2020-2039 are years

FOUR_DIGIT_AMOUNTS = ["5000", "1999", "2000", "4999", "1000", "9999"]
YEARS = ["2020", "2026", "2027", "2039"]


@pytest.mark.parametrize("amount", FOUR_DIGIT_AMOUNTS)
def test_FR_CHN_11_inbound_signal_a_bare_four_digit_amount_is_money(amount: str) -> None:
    assert "money" in inbound_signal(f"Can you confirm the {amount}?")
    assert "money" in inbound_signal(f"Can you confirm the {amount} for the boat by Friday?")


@pytest.mark.parametrize("year", YEARS)
def test_FR_CHN_11_inbound_signal_a_year_from_2020_to_2039_stays_clean(year: str) -> None:
    assert inbound_signal(f"See you in {year}.") == frozenset()
    assert inbound_signal(f"The inspection is on 12 Oct {year}.") == frozenset()


# ---------------------------------------------------------------------------
# Invariants (Hypothesis)


@needs_inbound_signal
@given(
    amount=st.sampled_from([*SUFFIXED, *FOUR_DIGIT_AMOUNTS]),
    before=st.text(alphabet="abcdefghij ", max_size=40),
    after=st.text(alphabet="abcdefghij ", max_size=40),
)
@_FAST
def test_FR_CHN_11_inbound_signal_property_an_amount_is_money_wherever_it_sits(
    amount: str, before: str, after: str
) -> None:
    assert "money" in inbound_signal(f"{before}. confirm the {amount}! {after}")
