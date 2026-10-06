"""FR-CHN-11, security review round 4 of PR #389: `autopilot_t3.inbound_plain` / `inbound_signal` (ADR-0013; issue #298
"CHN-GATE-C"; BQ-265; PRD 10.4: T3 "money, contract or legal terms" needs a person; L2 is for plain replies).

Round 4 found three holes in the round-3 allowlist, pinned here as pure functions (end to end in `_r4.py`):

  1. Newline glue. A newline is allowed text, and the signal drops it between letters ("trans\\nfer" gives "transfer"),
     but a neighbouring word glued by a line break ("the\\ntrans\\nfer" gives "thetransfer") has no word edge, so
     nothing signalled and the text was plain. A family word cut by line breaks (or a stop mark plus a line break)
     with a neighbour glued the same way is never clean: `inbound_signal` non-empty OR not `inbound_plain`. Spaced
     neighbours already signal; ordinary multi-line plain talk stays clean (controls).
  2. Raw non-ASCII is never plain. `inbound_plain` ran NFKC before the alphabet check, so "re" + U+017F + "und",
     U+00AA, fullwidth letters and NBSP folded into plain ASCII. The check is on the raw text (after the existing
     line-break normalisation). Also U+0F73 x 20,000 took 1.3 s through NFKC: under 0.2 s now.
  3. Mutant killers: a time of day takes a plain space only ("5\\tpm", "5\\npm" are not times, so not plain), and
     single letters separated by times of day ("w 5pm i 5pm r 5pm e") are not clean.

Every non-ASCII character is built with chr(). No network, no model."""

from __future__ import annotations

import time
import unicodedata

import pytest
from _chn11_inbound_lib import (
    PLAIN_INBOUND,
    PLAIN_SUBJECTS,
    R4_LETTERS_BETWEEN_TIMES,
    R4_NEWLINE_GLUE,
    R4_PLAIN_MULTILINE,
    R4_SUBJECT_NEWLINE_GLUE,
    inbound_plain,
    inbound_signal,
    is_clean,
    needs_inbound_plain,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_FAST = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])

# ---------------------------------------------------------------------------
# 1. Newline glue


@needs_inbound_plain
@pytest.mark.parametrize("text", R4_NEWLINE_GLUE, ids=[f"body{i}" for i in range(len(R4_NEWLINE_GLUE))])
def test_FR_CHN_11_inbound_aware_l2_r4_a_word_cut_by_line_breaks_with_a_glued_neighbour_is_not_clean(
    text: str,
) -> None:
    assert inbound_signal(text) or not inbound_plain(text), f"{text!r} has no signal and is plain"
    assert not is_clean(text)


@needs_inbound_plain
@pytest.mark.parametrize(
    "text", R4_SUBJECT_NEWLINE_GLUE, ids=[f"subject{i}" for i in range(len(R4_SUBJECT_NEWLINE_GLUE))]
)
def test_FR_CHN_11_inbound_aware_l2_r4_the_same_cut_in_a_subject_is_not_clean_with_or_without_a_re_prefix(
    text: str,
) -> None:
    assert not is_clean(text)
    assert not is_clean("Re: " + text)


@needs_inbound_plain
@pytest.mark.parametrize("text", R4_PLAIN_MULTILINE + PLAIN_INBOUND + PLAIN_SUBJECTS)
def test_FR_CHN_11_inbound_aware_l2_r4_ordinary_multi_line_plain_talk_stays_clean(text: str) -> None:
    # The control: a fix may not make every line break suspicious.
    assert is_clean(text)


_FAMILY_WORDS = [
    # money
    "transfer",
    "refund",
    "payment",
    "invoice",
    "wire",
    "deposit",
    "pay",
    "fee",
    "bank",
    "charge",
    "quote",
    "budget",
    "cash",
    # legal
    "contract",
    "liability",
    "sign",
    "agree",
    "waiver",
    "settlement",
    "terms",
    "accept",
    "court",
    # commitment
    "guarantee",
    "promise",
    "commit",
    "deadline",
    "assure",
    "pledge",
    "hereby",
    "deal",
]
_MARKS = ["\n", ".", ",", "!", "?", ":"]
_CUTS = [*_MARKS, *(m + "\n" for m in _MARKS[1:])]  # a line break, or a stop mark with or without one after it
_JOINTS = [*_CUTS, " "]  # a neighbour glued by a cut, or (on at most one side) spaced
_LEFT = ["the", "please", "to", "it", "kindly"]
_RIGHT = ["today", "now", "it", "soon", "okay"]


@needs_inbound_plain
@given(
    word=st.sampled_from(_FAMILY_WORDS),
    cut=st.integers(min_value=1, max_value=12),
    cut_sep=st.sampled_from(_CUTS),
    left=st.sampled_from(_LEFT),
    right=st.sampled_from(_RIGHT),
    left_sep=st.sampled_from(_JOINTS),
    right_sep=st.sampled_from(_JOINTS),
)
@_FAST
def test_FR_CHN_11_inbound_aware_l2_r4_property_a_family_word_cut_by_marks_or_line_breaks_is_never_clean(
    word: str, cut: int, cut_sep: str, left: str, right: str, left_sep: str, right_sep: str
) -> None:
    cut = min(cut, len(word) - 1)
    text = f"{left}{left_sep}{word[:cut]}{cut_sep}{word[cut:]}{right_sep}{right}"
    assert not is_clean(text), f"{text!r} is clean: no signal and plain"


@needs_inbound_plain
@given(
    word=st.sampled_from(_FAMILY_WORDS),
    cut=st.integers(min_value=1, max_value=12),
    cut_sep=st.sampled_from(_CUTS),
    left=st.sampled_from(_LEFT),
    right=st.sampled_from(_RIGHT),
    glue=st.sampled_from(_CUTS),
)
@_FAST
def test_FR_CHN_11_inbound_aware_l2_r4_property_a_neighbour_glued_the_same_way_on_both_sides_is_never_clean(
    word: str, cut: int, cut_sep: str, left: str, right: str, glue: str
) -> None:
    cut = min(cut, len(word) - 1)
    text = f"{left}{glue}{word[:cut]}{cut_sep}{word[cut:]}{glue}{right}"
    assert not is_clean(text), f"{text!r} is clean: no signal and plain"


# ---------------------------------------------------------------------------
# 2. Raw non-ASCII is never plain


@pytest.mark.parametrize(
    "char",
    [
        chr(0x017F),  # long s: NFKC gives "s"
        chr(0x00AA),  # feminine ordinal: NFKC gives "a"
        chr(0x00BA),
        chr(0xFF52),  # fullwidth r
        chr(0xFF26),  # fullwidth F
        chr(0xFF54),
        chr(0x00A0),  # NBSP: NFKC gives a space
        chr(0x2002),  # en space
        chr(0x3000),  # ideographic space
        chr(0x212A),  # Kelvin sign: NFKC gives "K"
        chr(0x2160),  # Roman numeral one: NFKC gives "I"
        chr(0xFB01),  # fi ligature
        chr(0x1D41A),  # mathematical bold a
        chr(0x0F73),  # NFKC splits it into two marks
        chr(0xFDFA),  # NFKC expands it 18-fold
        chr(0x2024),  # one dot leader: NFKC gives "."
        chr(0x2025),
        chr(0xFF0E),  # fullwidth full stop
        chr(0xFF0C),  # fullwidth comma
        chr(0x037E),  # Greek question mark: NFKC gives ";"
        chr(0x00B4),
    ],
    ids=lambda c: f"U+{ord(c):04X}",
)
def test_FR_CHN_11_inbound_aware_l2_r4_a_raw_non_ascii_character_is_never_plain(char: str) -> None:
    for text in (
        f"see you {char} friday",
        f"fri{char}day",
        f"Please confirm the re{char}und today.",
        char,
        f"ok {char}",
    ):
        assert inbound_plain(text) is False, f"plain with a raw U+{ord(char):04X}: {text!r}"


def _ascii_after_nfkc() -> list[str]:
    return [chr(i) for i in range(0x80, 0x20000) if unicodedata.normalize("NFKC", chr(i)).isascii()]


_FOLDS_TO_ASCII = _ascii_after_nfkc()
_HIDDEN = ("Cc", "Cf", "Zl", "Zp")  # `inbound_signal` already calls these "obfuscated": is_clean is the contract there


def test_FR_CHN_11_inbound_aware_l2_r4_the_scan_of_chars_that_fold_to_ascii_is_not_empty() -> None:
    assert len(_FOLDS_TO_ASCII) > 500 and chr(0x017F) in _FOLDS_TO_ASCII and chr(0xFF52) in _FOLDS_TO_ASCII


def test_FR_CHN_11_inbound_aware_l2_r4_no_character_that_nfkc_folds_to_ascii_is_plain() -> None:
    offenders = [
        f"U+{ord(c):04X}"
        for c in _FOLDS_TO_ASCII
        if unicodedata.category(c) not in _HIDDEN and inbound_plain(f"see you {c} friday")
    ]
    assert not offenders, f"{len(offenders)} raw non-ASCII characters are plain: {offenders[:12]}"


def test_FR_CHN_11_inbound_aware_l2_r4_no_hidden_or_folding_character_makes_a_clean_text() -> None:
    offenders = [f"U+{ord(c):04X}" for c in _FOLDS_TO_ASCII if is_clean(f"see you {c} friday")]
    assert not offenders, f"{len(offenders)} are clean: {offenders[:12]}"


@needs_inbound_plain
@given(
    before=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=20),
    after=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=20),
    char=st.sampled_from(
        [c for c in _FOLDS_TO_ASCII if unicodedata.category(c) not in _HIDDEN and c not in " "] or [chr(0x017F)]
    ),
)
@_FAST
def test_FR_CHN_11_inbound_aware_l2_r4_property_one_raw_non_ascii_character_makes_any_text_not_plain(
    before: str, after: str, char: str
) -> None:
    assert inbound_plain(before + char + after) is False


@pytest.mark.parametrize(
    ("char", "count"),
    [(chr(0x0F73), 20_000), (chr(0xFDFA), 10_000), (chr(0xFDFA), 20_000)],
    ids=["U+0F73x20000", "U+FDFAx10000", "U+FDFAx20000"],
)
def test_FR_CHN_11_inbound_aware_l2_r4_a_long_run_of_costly_characters_takes_under_a_fifth_of_a_second(
    char: str, count: int
) -> None:
    # The check on the raw text rejects at the first off-list character; no NFKC pass over the whole input first.
    text = char * count
    best = min(_timed(inbound_plain, text) for _ in range(3))
    assert inbound_plain(text) is False
    assert best < 0.2, f"inbound_plain took {best:.3f} s for {count} x U+{ord(char):04X}"


def _timed(fn, text: str) -> float:  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    fn(text)
    return time.perf_counter() - start


# ---------------------------------------------------------------------------
# 3. Mutant killers


@pytest.mark.parametrize(
    "text",
    [
        "5\tpm",
        "5\npm",
        "See you at 5\tpm.",
        "See you at 5\npm.",
        "See you at 5\r\npm.",
        "See you at 5 \npm.",
        "See you at 2:30\tpm.",
        "Hi Sarah, are you free at 3\npm or 4\tpm tomorrow?",
    ],
)
def test_FR_CHN_11_inbound_aware_l2_r4_a_time_of_day_takes_a_plain_space_only(text: str) -> None:
    # "5\\tpm" and "5\\npm" are not times: the digit is off the list, so the text is not plain (a `\\s?` between the
    # number and am/pm would let them through).
    assert inbound_plain(text) is False
    assert not is_clean(text)


def test_FR_CHN_11_inbound_aware_l2_r4_a_time_of_day_with_no_space_or_one_plain_space_is_plain() -> None:
    for time_ in ("5pm", "5 pm", "5:30pm", "5:30 pm", "17:30", "12am"):
        assert inbound_plain(f"See you at {time_}.") is True, time_


@needs_inbound_plain
@pytest.mark.parametrize("text", R4_LETTERS_BETWEEN_TIMES + ["a 5pm b 5pm c", "p 9am a 9am y"])
def test_FR_CHN_11_inbound_aware_l2_r4_single_letters_separated_by_times_are_not_clean(text: str) -> None:
    assert inbound_signal(text) or not inbound_plain(text), f"{text!r} has no signal and is plain"
    assert not is_clean(text)
