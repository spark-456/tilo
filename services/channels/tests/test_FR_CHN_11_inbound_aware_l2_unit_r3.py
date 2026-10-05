"""FR-CHN-11, security review round 3 of PR #389: `tilo_channels.autopilot_t3.inbound_plain(text) -> bool` (ADR-0013;
issue #298 "CHN-GATE-C", first bullet; BQ-265; PRD 10.4: T3 "money, contract or legal terms" needs a person; L2 "the
instruction is the approval" is for plain replies).

Round 3 failed the denylist again: a denylist cannot enumerate every obfuscation. The decided redesign (6 Oct, by the
orchestrator under the user's standing delegation; strictly more conservative than the user's 5 Oct decision "a money,
legal or spoofed inbound makes the reply T3") adds a pure, linear ALLOWLIST for the replied-to body and Subject:

  `inbound_plain(text)` is true only when, after the existing clean_text / NFKC step, every character is
    - an ASCII letter, a space, a newline, or one of `. , ? ! :` and `'`; or
    - a digit that belongs to a time of day (the existing `_TIME` shapes: 3pm, 3 pm, 2:30pm, 14:30);
  and further
    - `. , ? ! :` may only be followed by a space, a newline or the end ("the.trans.fer", "re:fund", "1)trans-fer"
      are not plain);
    - `'` only inside a contraction between letters with suffix s, t, re, ve, ll, d or m ("trans'fer" is not plain);
    - NO hyphen, underscore, slash, backslash, `@`, `%`, `$`, `#`, `&`, `*`, `+`, `~`, `|`, quote, bracket, `>`
      (a quoted reply), middle dot, any non-ASCII character, or any digit outside a time of day;
    - two or more consecutive single-letter tokens are not plain ("w i r e", "t r a n s"); a lone "a" or "I" beside a
      longer word is fine;
    - empty text is plain; text over SIGNAL_CAP is not plain.
  Words split by plain spaces into multi-letter chunks ("trans fer") remain an ACCEPTED GAP: nothing below pins them.

`inbound_signal` is unchanged (its unit expectations in the other `_unit` files still hold), and L2 needs BOTH
`not inbound_signal(text)` and `inbound_plain(text)` for the body and for the Subject (end to end in `_r3.py`).

Pinned here: `inbound_plain` itself (plain scheduling talk is plain; each class above is not), the exact round-3 review
failures (each is NOT clean: a signal OR not plain), and two mutant killers for `inbound_signal` (the `_INSIDE`
searches of a joined spread run, and the spread-first form ordering). Every non-ASCII character is built with chr().
No network, no model."""

from __future__ import annotations

import string

import pytest
from _chn11_inbound_lib import (
    PLAIN_INBOUND,
    PLAIN_SUBJECTS,
    R3_BODY_FAILURES,
    R3_SUBJECT_FAILURES,
    inbound_plain,
    inbound_signal,
    is_clean,
    needs_inbound_plain,
    t3_module,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ASCII_PUNCT = list(string.punctuation)
UNICODE_MARKS = [chr(c) for c in (0x2010, 0x2011, 0x2013, 0x2014, 0x2022, 0x2027, 0x30FB, 0xFF65)]
ALL_PUNCT = ASCII_PUNCT + UNICODE_MARKS
assert len(ASCII_PUNCT) == 32 and "_" in ASCII_PUNCT and len(ALL_PUNCT) == 40
_FAST = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _label(mark: str) -> str:
    return f"U+{ord(mark):04X}"


def _plain_offenders(shapes: list[str]) -> list[str]:
    return [s for s in shapes if inbound_plain(s)]


def test_FR_CHN_11_inbound_plain_exists_in_autopilot_t3() -> None:
    assert callable(getattr(t3_module(), "inbound_plain", None)), "autopilot_t3.inbound_plain(text) is missing"


# ---------------------------------------------------------------------------
# Ordinary scheduling talk is plain


@pytest.mark.parametrize("text", PLAIN_INBOUND + PLAIN_SUBJECTS)
def test_FR_CHN_11_inbound_plain_ordinary_scheduling_talk_is_plain(text: str) -> None:
    assert inbound_plain(text) is True
    assert inbound_signal(text) == frozenset(), "test setup: plain scheduling talk has no signal"


@pytest.mark.parametrize(
    "text",
    [
        "Can Marcus come by this Friday afternoon to look the engine over? Thanks, David",
        "Hi Sarah, are you free at 3pm or 2:30pm tomorrow?",
        "Don't worry, we're fine.",
        "Thanks!",
        "Hi,\nDavid",
        "Ok.\n",
        "Can I bring a tarp?",
        "I'm free at 14:30, you'll see I've time. It's fine, they'd come, we'll meet.",
        "Let us meet at 3 pm.",
        "Re: Friday afternoon",
    ],
)
def test_FR_CHN_11_inbound_plain_allowed_letters_punctuation_contractions_and_times_are_plain(text: str) -> None:
    assert inbound_plain(text) is True


def test_FR_CHN_11_inbound_plain_empty_text_is_plain() -> None:
    assert inbound_plain("") is True
    assert inbound_plain("   ") is True


def test_FR_CHN_11_inbound_plain_a_time_of_day_is_the_only_digit_shape_that_is_plain() -> None:
    for time in ("3pm", "3 pm", "2:30pm", "9am", "14:30", "23:59"):
        assert inbound_plain(f"See you at {time}.") is True, time


# ---------------------------------------------------------------------------
# Punctuation, as a class, in the middle of a word and wrapping it


@pytest.mark.parametrize("p", ALL_PUNCT, ids=[_label(p) for p in ALL_PUNCT])
def test_FR_CHN_11_inbound_plain_each_mark_wrapping_or_inside_a_word_is_not_plain(p: str) -> None:
    # One id per mark (every ASCII punctuation character, "_" included, and the eight Unicode marks), so a run shows
    # exactly which characters the allowlist still lets through.
    shapes = [f"{p}transfer{p}", f"the{p}transfer", f"Please confirm the {p}transfer{p} today.", f"re{p}fund"]
    assert not _plain_offenders(shapes), f"{p!r} is plain in: {_plain_offenders(shapes)}"


def test_FR_CHN_11_inbound_plain_two_marks_in_a_word_are_never_plain() -> None:
    # f"the{p}tr{q}ansfer" and f"si{q}gn{p}return" over every pair of marks, ASCII punctuation (with "_") and Unicode.
    offenders = [
        s for p in ALL_PUNCT for q in ALL_PUNCT for s in (f"the{p}tr{q}ansfer", f"si{q}gn{p}return") if inbound_plain(s)
    ]
    assert not offenders, f"plain, but they hide a word: {offenders[:10]}"


@pytest.mark.parametrize("p", ALL_PUNCT, ids=[_label(p) for p in ALL_PUNCT])
def test_FR_CHN_11_inbound_plain_a_mark_beside_a_digit_or_a_bracket_is_not_plain(p: str) -> None:
    assert not inbound_plain(f"1{p}transfer")
    assert not inbound_plain(f"({p}) ok")
    assert not inbound_plain(f"ok{p}5")


@pytest.mark.parametrize(
    "text",
    [
        "Hi,David",
        "Hi.David",
        "Hi:David",
        "Hi?David",
        "Hi!David",
        "the.trans.fer",
        "re:fund",
        "1)trans-fer",
        "Ok,\tDavid",
        "see you.Friday",
    ],
)
def test_FR_CHN_11_inbound_plain_a_stop_mark_is_only_followed_by_a_space_a_newline_or_the_end(text: str) -> None:
    assert inbound_plain(text) is False


@pytest.mark.parametrize("text", ["Hi, David", "Hi,\nDavid", "Hi, David,", "Is it fine?", "Re: fine", "Fine.\n\nDavid"])
def test_FR_CHN_11_inbound_plain_a_stop_mark_before_a_space_a_newline_or_the_end_is_plain(text: str) -> None:
    assert inbound_plain(text) is True


@pytest.mark.parametrize(
    "text",
    ["trans'fer", "re'fund", "con'tract", "pa'yment", "'transfer'", "'", "ok 'quoted' text", "the' transfer", "it'sx"],
)
def test_FR_CHN_11_inbound_plain_an_apostrophe_outside_a_contraction_is_not_plain(text: str) -> None:
    assert inbound_plain(text) is False


@pytest.mark.parametrize("suffix", ["s", "t", "re", "ve", "ll", "d", "m"])
def test_FR_CHN_11_inbound_plain_each_contraction_suffix_is_plain(suffix: str) -> None:
    assert inbound_plain(f"They say it'{suffix} fine.") is True


def test_FR_CHN_11_inbound_plain_the_curly_apostrophe_is_not_ascii_so_not_plain() -> None:
    assert inbound_plain("Don" + chr(0x2019) + "t worry.") is False


# ---------------------------------------------------------------------------
# Characters that are never plain


@pytest.mark.parametrize(
    "char", list('-_/\\@%$#&*+~|"`()[]{}<>;=^') + ["\t"], ids=lambda c: _label(c) if c else "empty"
)
def test_FR_CHN_11_inbound_plain_other_ascii_characters_are_never_plain(char: str) -> None:
    for text in (f"ok{char}ok", f"{char}ok", f"ok{char}", f"ok {char} ok", f"Hi, {char}David"):
        assert inbound_plain(text) is False, repr(text)


@pytest.mark.parametrize("mark", UNICODE_MARKS, ids=[_label(m) for m in UNICODE_MARKS])
def test_FR_CHN_11_inbound_plain_unicode_marks_are_never_plain(mark: str) -> None:
    for text in (f"ok{mark}ok", f"{mark}ok", f"ok {mark} ok"):
        assert inbound_plain(text) is False, repr(text)


@pytest.mark.parametrize(
    "text",
    [
        "caf" + chr(0xE9),
        "Fri" + chr(0x0456) + "day",
        "na" + chr(0xEF) + "ve",
        "Friday " + chr(0x1F642),
        "see you" + chr(0x2026),
        "5" + chr(0x0663),
        "tr" + chr(0x0430) + "nsfer",
        chr(0xFDFA) * 3,
    ],
)
def test_FR_CHN_11_inbound_plain_non_ascii_characters_are_never_plain(text: str) -> None:
    assert inbound_plain(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "5million",
        "10lakh",
        "50  K",
        "25-M",
        "10_m",
        "12-b",
        "10/L",
        "5000",
        "10%",
        "Can you confirm the 5,000?",
        "dock 14",
        "room 7",
        "2 tarps",
        "See you in 2026.",
        "x1",
        "1x",
        "3pm5",
    ],
)
def test_FR_CHN_11_inbound_plain_a_digit_outside_a_time_of_day_is_never_plain(text: str) -> None:
    assert inbound_plain(text) is False
    assert inbound_plain(f"Can you confirm the {text} by Friday?") is False


@pytest.mark.parametrize(
    "text",
    [
        "see https://x.example",
        "a@b.example",
        "x.example/dock",
        "www.example.com",
        "Map: https://harriercharters.example/dock-14",
        "mail me at david@harriercharters.example",
    ],
)
def test_FR_CHN_11_inbound_plain_a_link_or_an_address_is_never_plain(text: str) -> None:
    assert inbound_plain(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "> Please wire it today",
        "Thanks, David\n\n> Hi Sarah, are you free?",
        ">> ok\n> fine",
        "Ok.\n> quoted",
    ],
)
def test_FR_CHN_11_inbound_plain_a_quoted_reply_line_is_never_plain(text: str) -> None:
    assert inbound_plain(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "w i r e",
        "t r a n s",
        "p a y",
        "x y",
        "a w i r e",
        "I s i g n",
        "Please confirm the w i r e today.",
        "Please confirm the t r a n s f e r today.",
        "Hi, w i r e ok",
    ],
)
def test_FR_CHN_11_inbound_plain_two_or_more_consecutive_single_letters_are_not_plain(text: str) -> None:
    assert inbound_plain(text) is False


@pytest.mark.parametrize("text", ["w. i. r. e.", "w, i, r, e", "w? i? r? e?", "t: r: a: n: s: f: e: r:"])
def test_FR_CHN_11_inbound_plain_single_letters_spread_by_stop_marks_are_not_clean(text: str) -> None:
    # A stop mark before a space is allowed on its own, so these are the cases where the signal or the single-letter
    # rule must hold the line: not clean either way.
    assert not is_clean(text)


@pytest.mark.parametrize("text", ["Can I bring a tarp?", "I think a tarp is fine.", "Is a boat free? I hope so."])
def test_FR_CHN_11_inbound_plain_a_lone_a_or_i_beside_longer_words_is_plain(text: str) -> None:
    assert inbound_plain(text) is True


def test_FR_CHN_11_inbound_plain_the_cap_itself_is_plain_and_one_more_is_not() -> None:
    cap = t3_module().SIGNAL_CAP
    assert cap == 20_000
    at_cap = "ok " * 6_666 + "ok"
    assert len(at_cap) == cap and inbound_plain(at_cap) is True
    assert inbound_plain(at_cap + " ") is False
    assert inbound_plain("see you friday. " * 2_000) is False  # 32 000 characters


def test_FR_CHN_11_inbound_plain_a_long_awkward_input_is_read_in_one_pass() -> None:
    # No catastrophic backtracking: these only have to return.
    assert inbound_plain("it'" * 6_000) is False
    assert inbound_plain("a" * 19_999 + "'") is False
    assert inbound_plain(". " * 9_999) is True
    assert inbound_plain("ab" * 9_999 + "-") is False


# ---------------------------------------------------------------------------
# The exact failures of the round-3 review: not clean through `inbound_signal` OR `inbound_plain`


@needs_inbound_plain
@pytest.mark.parametrize("text", R3_BODY_FAILURES, ids=[f"body{i}" for i in range(len(R3_BODY_FAILURES))])
def test_FR_CHN_11_inbound_aware_l2_r3_a_round_three_failure_is_not_clean_as_a_body(text: str) -> None:
    assert inbound_signal(text) or not inbound_plain(text), f"{text!r} is clean: it has no signal and is plain"


@needs_inbound_plain
@pytest.mark.parametrize("text", R3_BODY_FAILURES + R3_SUBJECT_FAILURES, ids=lambda t: t[:24])
def test_FR_CHN_11_inbound_aware_l2_r3_a_round_three_failure_is_not_clean_as_a_subject(text: str) -> None:
    # A Subject is held to the same rule as a body ("Re:" prefixes included).
    assert not is_clean(text)
    assert not is_clean("Re: " + text)


@needs_inbound_plain
@pytest.mark.parametrize("text", R3_SUBJECT_FAILURES)
def test_FR_CHN_11_inbound_aware_l2_r3_the_subject_failures_are_not_clean(text: str) -> None:
    assert not is_clean(text)


@needs_inbound_plain
def test_FR_CHN_11_inbound_aware_l2_r3_the_plain_scheduling_texts_are_clean() -> None:
    # The control for the failures above: plain talk is clean, so `is_clean` is not simply false.
    assert all(is_clean(t) for t in PLAIN_INBOUND + PLAIN_SUBJECTS)


# ---------------------------------------------------------------------------
# Mutant killers


@pytest.mark.parametrize(
    ("text", "family"),
    [
        ("a w i r e", "money"),
        ("Please confirm a w i r e today.", "money"),
        ("I s i g n", "legal"),
        ("Please confirm I s i g n today.", "legal"),
        ("I p a y", "money"),
        ("Please confirm the a t r a n s f e r today.", "money"),
    ],
)
def test_FR_CHN_11_inbound_aware_l2_r3_a_spread_run_with_a_stray_letter_before_it_still_signals(
    text: str, family: str
) -> None:
    # A stray "a" or "I" before a spread-out word glues to it ("a w i r e" gives "awire"): the signal searches the
    # joined run without word edges (`_INSIDE`). `inbound_signal` is unchanged, so it must still name the family; and
    # the text is not plain either way.
    assert family in inbound_signal(text)
    assert not is_clean(text)


@needs_inbound_plain
@pytest.mark.parametrize("text", ["a w i r e", "I s i g n", "a p a y", "I t r a n s f e r"])
def test_FR_CHN_11_inbound_aware_l2_r3_a_spread_run_is_a_signal_or_not_plain(text: str) -> None:
    assert inbound_signal(text) or not inbound_plain(text)


@pytest.mark.parametrize(
    ("text", "family"),
    [
        ("Please confirm the t r a n s-fer today.", "money"),
        ("Please confirm the tr-a n s f e r today.", "money"),
        ("Please confirm the w i r-e today.", "money"),
        ("Please confirm the s i-g n today.", "legal"),
    ],
)
def test_FR_CHN_11_inbound_aware_l2_r3_both_split_orders_still_signal(text: str, family: str) -> None:
    # "t r a n s-fer" needs spread first then punctuation dropped; "tr-a n s f e r" would be missed by a drop-first
    # only order: the signal forms must keep both orders (`_forms`).
    assert family in inbound_signal(text)
    assert not is_clean(text)


# ---------------------------------------------------------------------------
# Invariants (Hypothesis)

_WORDS = [
    "hi",
    "sarah",
    "can",
    "marcus",
    "come",
    "by",
    "this",
    "friday",
    "afternoon",
    "thanks",
    "david",
    "3pm",
    "2:30pm",
    "14:30",
    "don't",
    "we're",
    "I'm",
    "it's",
]
_STOPS = [" ", ", ", ". ", "? ", "! ", ": ", "\n", ",\n", " "]


@needs_inbound_plain
@given(
    words=st.lists(st.sampled_from(_WORDS), min_size=0, max_size=30),
    stops=st.lists(st.sampled_from(_STOPS), min_size=30, max_size=30),
    end=st.sampled_from(["", ".", "?", "!", "\n"]),
)
@_FAST
def test_FR_CHN_11_inbound_plain_property_words_times_and_ordinary_stops_are_plain(
    words: list[str], stops: list[str], end: str
) -> None:
    text = "".join(w + s for w, s in zip(words[:-1], stops, strict=False)) + "".join(words[-1:]) + end
    assert inbound_plain(text) is True, repr(text)


@needs_inbound_plain
@given(
    before=st.text(alphabet=string.ascii_lowercase + " ", min_size=0, max_size=30),
    after=st.text(alphabet=string.ascii_lowercase + " ", min_size=0, max_size=30),
    bad=st.sampled_from(list('-_/\\@%$#&*+~|"`()[]{}<>;=^\t') + UNICODE_MARKS + [chr(0xE9), chr(0x2019)]),
)
@_FAST
def test_FR_CHN_11_inbound_plain_property_one_character_outside_the_alphabet_makes_any_text_not_plain(
    before: str, after: str, bad: str
) -> None:
    assert inbound_plain(before + bad + after) is False


@needs_inbound_plain
@given(
    before=st.text(alphabet=string.ascii_lowercase + " ", min_size=0, max_size=30),
    after=st.text(alphabet=string.ascii_lowercase + " ", min_size=0, max_size=30),
    digit=st.sampled_from(list("0123456789")),
)
@_FAST
def test_FR_CHN_11_inbound_plain_property_a_digit_that_is_not_part_of_a_time_makes_any_text_not_plain(
    before: str, after: str, digit: str
) -> None:
    # The "x" after the digit keeps it from forming a time ("5pm") with whatever follows.
    assert inbound_plain(f"{before}{digit}x{after}") is False


@needs_inbound_plain
@given(
    word=st.sampled_from(["transfer", "refund", "contract", "wire", "payment", "invoice", "liability", "sign", "pay"]),
    cut=st.integers(min_value=1, max_value=7),
    run=st.lists(st.sampled_from(ALL_PUNCT), min_size=1, max_size=3).map("".join),
)
@_FAST
def test_FR_CHN_11_inbound_plain_property_a_signal_word_split_by_any_marks_is_never_clean(
    word: str, cut: int, run: str
) -> None:
    cut = min(cut, len(word) - 1)
    text = f"Please confirm the {word[:cut]}{run}{word[cut:]} today."
    assert not is_clean(text), f"{text!r} is clean"


@needs_inbound_plain
@given(
    word=st.sampled_from(["transfer", "refund", "contract", "wire", "payment", "invoice", "sign", "pay"]),
    seps=st.lists(st.sampled_from([" ", "-", ".", "_", "/", ",", "'", "  ", " -"]), min_size=8, max_size=8),
)
@_FAST
def test_FR_CHN_11_inbound_plain_property_a_signal_word_spread_by_any_separators_is_never_clean(
    word: str, seps: list[str]
) -> None:
    spread = word[0] + "".join(sep + ch for sep, ch in zip(seps, word[1:], strict=False))
    text = f"Please confirm the {spread} today."
    assert not is_clean(text), f"{text!r} is clean"
