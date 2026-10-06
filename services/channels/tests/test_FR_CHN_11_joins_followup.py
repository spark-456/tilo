"""FR-CHN-11, BQ-278 items (i)-(m) (follow-up to security review round 5 of PR #389): `autopilot_t3.inbound_signal`
and `inbound_plain`, the piece-join check (`_join_hits`) for the message a draft answers (ADR-0013; BQ-274 / BQ-278).

  (i)  A space next to a line break is a piece cut: "the \\ntrans \\nfer" signals money.
  (j)  A time of day between two multi-letter pieces is a piece cut: "trans 5pm fer" signals money.
  (k)  A phrase family cut inside a word by line breaks ("account\\nnum\\nber") is joined by piece, then matched.
  (l)  The joined length is capped at 2,000 characters (over it fails closed as "obfuscated"), the scan stops at the
       first hit, and a 20k-character plain field finishes in under 150 ms (best of 3).
  (m)  Test gaps: a 3-piece and 4-piece cut, and a late cut in a 9-10 letter stem (mutants joins_pairs_only and
       joins_stem_8).

Ordinary multi-line talk stays clean (negative controls). No network, no model."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from _chn11_inbound_lib import inbound_plain, inbound_signal, is_clean
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_FAST = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
_WORDS = ["transfer", "refund", "payment", "invoice", "contract", "signature", "guarantee", "promise", "deadline"]
_AROUND = [("the", "now"), ("please", "today"), ("to", "it"), ("kindly", "soon")]


def _best_of_3(fn: Callable[[str], object], text: str) -> float:
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        fn(text)
        best = min(best, time.perf_counter() - start)
    return best


def _signals(text: str, family: str) -> None:
    assert family in inbound_signal(text), f"{text!r}: {sorted(inbound_signal(text))}"
    assert not is_clean(text)


# (i) a space next to a line break is a piece cut

SPACE_BREAK_CUTS = [
    ("the \ntrans \nfer", "money"),
    ("the\n trans\n fer", "money"),
    ("the \r\n trans \r\n fer", "money"),
    ("the. \ntrans. \nfer", "money"),
    ("the \ncon \ntract now", "legal"),
    ("it \nguar \nantee now", "commitment"),
]


@pytest.mark.parametrize(("text", "family"), SPACE_BREAK_CUTS)
def test_FR_CHN_11_joins_i_a_space_next_to_a_line_break_is_a_piece_cut(text: str, family: str) -> None:
    _signals(text, family)


_SPACED_BREAKS = [" \n", "\n ", " \n ", " \r\n", "\n  ", "  \n\n "]


@given(
    word=st.sampled_from(_WORDS),
    cut=st.integers(min_value=1, max_value=12),
    cut_sep=st.sampled_from(_SPACED_BREAKS),
    glue=st.sampled_from(_SPACED_BREAKS),
    around=st.sampled_from(_AROUND),
)
@_FAST
def test_FR_CHN_11_joins_i_property_a_family_word_cut_with_spaces_next_to_line_breaks_is_never_clean(
    word: str, cut: int, cut_sep: str, glue: str, around: tuple[str, str]
) -> None:
    cut = min(cut, len(word) - 1)
    text = f"{around[0]}{glue}{word[:cut]}{cut_sep}{word[cut:]}{glue}{around[1]}"
    assert not is_clean(text), f"{text!r} is clean: no signal and plain"


# (j) a time of day between two multi-letter pieces is a piece cut

TIME_CUTS = [
    ("trans 5pm fer", "money"),
    ("the trans 5pm fer today", "money"),
    ("trans 5 pm fer", "money"),
    ("trans 17:30 fer", "money"),
    ("the 3pm trans 5pm fer 7pm now", "money"),
    ("the con 5pm tract now", "legal"),
    ("a guar 2:30pm antee now", "commitment"),
]


@pytest.mark.parametrize(("text", "family"), TIME_CUTS)
def test_FR_CHN_11_joins_j_a_time_of_day_between_two_pieces_is_a_cut(text: str, family: str) -> None:
    assert inbound_plain(text), "the control: the text is plain, so only the signal can stop it"
    _signals(text, family)


# (k) a phrase family cut inside a word by line breaks

PHRASE_CUTS = [
    ("account\nnum\nber", "money"),
    ("the\naccount\nnum\nber\nplease", "money"),
    ("account num\nber", "money"),
    ("acc\nount num\nber", "money"),
    ("sort\nco\ndes", "money"),
    ("we\nwi\nll", "commitment"),
    ("the\nrest\nassu\nred\nnow", "commitment"),
    ("for\nfr\nee", "commitment"),
    ("consider it\ndo\nne", "commitment"),
    ("leave\nit\nwi\nth\nme", "commitment"),
    ("we are\ngo\ning to", "commitment"),
]


@pytest.mark.parametrize(
    ("text", "family"), PHRASE_CUTS, ids=[t.replace("\n", "|").replace(" ", "_") for t, _ in PHRASE_CUTS]
)
def test_FR_CHN_11_joins_k_a_phrase_family_cut_inside_a_word_by_line_breaks_signals(text: str, family: str) -> None:
    _signals(text, family)


_PHRASES = ["account numbers", "sort code", "we will", "i shall", "will do", "for free", "on us", "my word"]
_PHRASES += ["consider it done", "count on me", "rest assured", "leave it with me", "you can rely", "we are going to"]
_BETWEEN_WORDS = [" ", "\n", "\n\n", " \n"]


@given(
    phrase=st.sampled_from(_PHRASES),
    cuts=st.sets(st.integers(min_value=1, max_value=20), max_size=6),
    seps=st.lists(st.sampled_from(_BETWEEN_WORDS), min_size=4, max_size=4),
    cut_sep=st.sampled_from(["\n", "\n\n", ".\n"]),
    around=st.sampled_from(_AROUND),
)
@_FAST
def test_FR_CHN_11_joins_k_property_a_phrase_cut_by_line_breaks_anywhere_is_never_clean(
    phrase: str, cuts: set[int], seps: list[str], cut_sep: str, around: tuple[str, str]
) -> None:
    out, word_no = [], 0
    for index, char in enumerate(phrase):
        if char == " ":
            out.append(seps[word_no % len(seps)])
            word_no += 1
        else:
            if index in cuts and out and out[-1] not in _BETWEEN_WORDS:
                out.append(cut_sep)
            out.append(char)
    text = f"{around[0]}\n{''.join(out)}\n{around[1]}"
    assert not is_clean(text), f"{text!r} is clean: no signal and plain"


# (l) the cap, the first hit and the timing

_PLAIN_FIELDS = {
    "pieces_cut_by_newlines": "ab\n" * 6_666,
    "talk": ("Hi Sarah, can Marcus come by this Friday afternoon?\nThanks\n" * 400)[:20_000],
    "spaced_newlines": "ab \n" * 5_000,
    "times": "trans 5pm " * 2_000,
    "spaces_only": "hello " * 3_333,
    "one_word": "a" * 20_000,
    "few_newlines_under_the_cap": ("hello there my friend " * 9 + "\n") * 100,
    "phrase_starts": "we are \nfor on \ncount " * 900,
    "contractions": "i'm\n" * 5_000,
    "times_between_breaks": "5pm\n" * 5_000,
}


@pytest.mark.parametrize("name", list(_PLAIN_FIELDS))
def test_FR_CHN_11_joins_l_a_20k_character_plain_field_takes_under_150_ms(name: str) -> None:
    text = _PLAIN_FIELDS[name]
    assert inbound_plain(text), "the control: the field is plain"
    for fn in (inbound_signal, inbound_plain):
        best = _best_of_3(fn, text)
        assert best < 0.15, f"{fn.__name__} took {best * 1000:.1f} ms for {name} ({len(text)} characters)"


def test_FR_CHN_11_joins_l_a_hit_at_the_start_stops_the_scan_and_still_signals_in_20k() -> None:
    text = "the\ntrans\nfer\n" + "ab\n" * 6_600
    assert "money" in inbound_signal(text)
    assert _best_of_3(inbound_signal, text) < 0.15


def test_FR_CHN_11_joins_l_joined_text_over_2000_characters_fails_closed_as_obfuscated() -> None:
    text = "hello\n" * 600  # 600 pieces glued by line breaks join to far more than 2,000 characters
    assert "obfuscated" in inbound_signal(text)
    assert not is_clean(text)


@pytest.mark.parametrize("tail", ["the\ntrans\nfer", "the\n trans\n fer", "trans 5pm fer", "account\nnum\nber"])
def test_FR_CHN_11_joins_l_a_risky_cut_after_a_long_padded_prefix_is_never_clean(tail: str) -> None:
    # The cap may not become a bypass: padding before the risky cut must not let it through.
    for pad in ("hello\n" * 400, "ab \n" * 1_000, "hello there my friend\n" * 300):
        assert not is_clean(pad + tail), f"{tail!r} after {len(pad)} characters of padding is clean"


# (m) a 3-piece cut and a late cut in a 9-10 letter stem

MANY_PIECES = [
    ("the\ntran\nsf\ner\nnow", "money"),  # kills joins_pairs_only (only joins of 2 pieces)
    ("the\ntr\nan\nsf\ner\nnow", "money"),
    ("the\ncon\ntr\nact\nnow", "legal"),
    ("it\nguar\nan\ntee\nnow", "commitment"),
]
LATE_CUTS = [  # kills joins_stem_8 (a join stops growing at 8 characters, not 10): the stem is not a word until joined
    ("the\nsettlemen\nt\nplease", "legal"),  # 10-letter stem, cut after the 9th letter
    ("the\nsettleme\nnt\nplease", "legal"),  # cut after the 8th letter
    ("the\nagreemen\nt\nplease", "legal"),  # 9-letter stem, cut after the 8th
    ("the\nquotatio\nn\nplease", "money"),  # 9-letter stem, cut after the 8th
]


@pytest.mark.parametrize(("text", "family"), MANY_PIECES + LATE_CUTS)
def test_FR_CHN_11_joins_m_a_word_cut_into_three_pieces_or_late_in_a_long_stem_signals(text: str, family: str) -> None:
    _signals(text, family)


# look-alike digits inside a family word cut by a time of day (the merged gate rejoined these before times were cut)

LEET_TIME_CUTS = [
    ("Please confirm the\nf\n3:35\nnow.", "money"),  # f + ee + s: fees
    ("the\nprom\n1:53\nnow", "commitment"),
    ("the\nguaran\n7:33\nnow", "commitment"),
    ("the\nc\n0:57\nnow", "money"),
    ("the\nra\n7:35\nnow", "money"),
    ("the\n5:37\ntlement\nnow", "legal"),
    ("rest\n4:55\nured\nnow", "commitment"),
]


@pytest.mark.parametrize(("text", "family"), LEET_TIME_CUTS)
def test_FR_CHN_11_joins_j_look_alike_digits_in_a_time_cut_family_word_are_not_clean(text: str, family: str) -> None:
    assert inbound_plain(text), "the control: the text is plain, so only the signal can stop it"
    assert not is_clean(text), f"{text!r} is clean"


# negative controls: ordinary multi-line talk stays clean

ORDINARY_MULTILINE = [
    "Hi Sarah, \nCan Marcus come by this Friday afternoon? \nThanks, \nDavid",
    "Hi Sarah,\nare you free on Friday \nafternoon or on \nSaturday morning?\nThanks,\nDavid",
    "Hi Sarah, are you free at 3 pm on Friday or at 4 pm on Saturday?\nThanks, David",
    "Please account\nfor the weather on Thursday.\nIt is late\nand we are happy to meet.",
    "Hi Sarah,\nwe could meet at 5pm \nfor a coffee \nor at 6pm for lunch.\nBest,\nDavid",
]


@pytest.mark.parametrize("text", ORDINARY_MULTILINE, ids=[f"talk{i}" for i in range(len(ORDINARY_MULTILINE))])
def test_FR_CHN_11_joins_ordinary_multi_line_talk_with_spaces_and_times_stays_clean(text: str) -> None:
    assert is_clean(text), f"{text!r}: {sorted(inbound_signal(text))}, plain={inbound_plain(text)}"


def test_FR_CHN_11_joins_a_1500_character_plain_email_stays_clean_under_the_cap() -> None:
    line = "Hi Sarah, can Marcus come by this Friday afternoon to look at the engine \n"
    text = (line * 20)[:1_500] + "\nThanks,\nDavid"
    assert is_clean(text), sorted(inbound_signal(text))
