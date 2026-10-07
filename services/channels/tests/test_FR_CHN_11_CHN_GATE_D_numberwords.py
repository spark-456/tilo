"""CHN-GATE-D fix pass r1 (PR #525, Opus security verdict at c0e4c94d; FR-CHN-11; ADR-0013; PRD 10.4 T3 "money,
contract or legal terms"): a number word is never a name, however it is spelt into the name slot.

Rule pinned here: a name word with apostrophes dropped that is made only of number words (optionally followed by "k",
"grand" or "s") is never a name, and every join of a greeting, signature or repeat run (two words, or a word broken by
a space or an apostrophe) gets the same number-word check as a single word. Such a body is "unlisted", so T3 and never
L2 at preview.

Defaults applied (issue #298 and the PR #525 verdict; BQ-224): bodies of the "Hi X, works for us." shape; the
apostrophe is ASCII or U+2019 (written as a \\u escape); repeats are pinned where the run ends in ":" or ",".
Existing GATE_D tests are not edited; real names (Simone, Tennyson, Emily, Milan, Craig, O'Brien, David, Anna Maria)
stay L2 as positive controls so an over-tight fix fails."""

from __future__ import annotations

import time

import pytest
from _chn11_lib import USER, autopilot_module, make_bench, pair, scripted_thread


def signal(body: str) -> frozenset[str]:
    return autopilot_module().t3_content_signal(body)


def never_auto_sent(body: str) -> None:
    """Through the public interface: an L2 policy, a ready draft; the card is T3, L1, nothing scheduled."""
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, body))
    assert card.tier == "T3" and "money_or_legal" in card.modifiers, f"auto-send allowed for {body!r}"
    assert (card.level, card.undo_window_s, card.outbox_id) == ("L1", 0, None)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}, "T3 is never scheduled without a person"


def auto_sent(body: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, body))
    assert card.tier == "T2" and card.modifiers == (), f"harmless reply made T3: {body!r}"
    assert (card.level, card.undo_window_s) == ("L2", 60) and card.outbox_id is not None


# ---- 1. one name word made only of number words (+ k / grand / s), apostrophes dropped ------------------------------

SINGLE_WORD_NUMBERS = [
    "Hi Fiftythousand, works for us.",
    "Hi Fiftyk, works for us.",
    "Hi Fivegrand, works for us.",
    "Thanks,\nFiftythousand",
    "Hi Fifty'Thousand, works for us.",
    "Hi Fifty’Thousand, works for us.",
]


@pytest.mark.parametrize("body", SINGLE_WORD_NUMBERS)
def test_FR_CHN_11_CHN_GATE_D_numberword_single_word_is_unlisted(body: str) -> None:
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


@pytest.mark.parametrize("body", SINGLE_WORD_NUMBERS)
def test_FR_CHN_11_CHN_GATE_D_numberword_single_word_is_t3_at_preview(body: str) -> None:
    never_auto_sent(body)


# ---- 2. a number word broken into pieces: the join of the run is checked like a single word ------------------------

JOINED_PIECES = [
    "Hi Fif Ty, works for us.",
    "Hi Hun Dred, works for us.",
    "Hi Thou'Sand, works for us.",
]


@pytest.mark.parametrize("body", JOINED_PIECES)
def test_FR_CHN_11_CHN_GATE_D_numberword_joined_run_is_unlisted(body: str) -> None:
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


@pytest.mark.parametrize("body", JOINED_PIECES)
def test_FR_CHN_11_CHN_GATE_D_numberword_joined_run_is_t3_at_preview(body: str) -> None:
    never_auto_sent(body)


# ---- 3. a repeat of the number-word run later in the body ---------------------------------------------------------

REPEATS = ["Hi Fiftythousand,\n\nThanks Fiftythousand: confirmed."]


@pytest.mark.parametrize("body", REPEATS)
def test_FR_CHN_11_CHN_GATE_D_numberword_repeat_is_unlisted(body: str) -> None:
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


@pytest.mark.parametrize("body", REPEATS)
def test_FR_CHN_11_CHN_GATE_D_numberword_repeat_is_t3_at_preview(body: str) -> None:
    never_auto_sent(body)


# ---- 4. positive controls: real names stay L2 -----------------------------------------------------------------------

REAL_NAMES = ["Simone", "Tennyson", "Emily", "Milan", "Craig", "O'Brien", "David", "Anna Maria"]


def named(name: str) -> str:
    return f"Hi {name},\n\nFriday 2pm works for us.\n\nBest,\nSarah"


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_real_name_is_listed(name: str) -> None:
    assert signal(named(name)) == frozenset(), f"real name {name!r} rejected"


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_real_name_still_l2(name: str) -> None:
    auto_sent(named(name))


# ---- 5. bounded input -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "word",
    ["Ab" * 10_000, "Fifty" * 4_000, "Fif'Ty" * 3_400],
    ids=["name_like", "number_words_glued", "number_words_apostrophes"],
)
def test_FR_CHN_11_CHN_GATE_D_numberword_long_name_word_is_bounded(word: str) -> None:
    body = f"Hi {word[:20_000]},\n\nFriday 2pm works for us."
    t0 = time.perf_counter()
    result = signal(body)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"{elapsed:.2f}s for a 20k-char name-like word"
    # "obfuscated" or "unlisted": either signal is T3
    assert result, "a 20k-char name-like word is never plain scheduling talk"
