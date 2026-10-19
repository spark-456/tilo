"""CHN-GATE-D fix pass r2 (PR #525, Opus security verdict r2 at f3481582; FR-CHN-11; ADR-0013; PRD 10.4 T3 "money,
contract or legal terms"): a number word glued to a unit, a magnitude or an abbreviation is never a name.

Rule pinned here (class, verdict r2): with apostrophes dropped, a name word is never a name when (a) it is number
words followed by at most one of k, m, b, l, s, grand(s) or a money word, or (b) it starts with a number word of 4+
letters, or (c) it contains hundred, thousand, million, billion, trillion, lakh or crore anywhere. Such a body is
"unlisted", so T3 and never L2 at preview. Three-letter number words and abbreviations (mil, lac, cr) stay
fullmatch-only; the 24-letter cap stays.

Defaults applied (issue #298 and the PR #525 verdicts; BQ-224): bodies of the greeting shape "Hi X, works for us." and
the signature shape "Thanks,\\nX"; the reviewer's negatives are pinned only through those two shapes. Real names stay
L2 as positive controls so an over-tight fix fails. The accepted false positives named in the verdict (Fournier,
Lakhani, Ninette, Sevenoaks) and any other name that the rule happens to catch are deliberately NOT pinned either way.
Existing GATE_D tests are not edited."""

from __future__ import annotations

import pytest
from _chn11_lib import EXTRA_NAMES, USER, VOUCHED, autopilot_module, make_bench, name_words, pair, scripted_thread


def signal(body: str, names: frozenset[str] = VOUCHED) -> frozenset[str]:
    # CHN-GATE-E: a name rides L2 only when the thread vouches for it; the bench thread vouches for VOUCHED.
    return autopilot_module().t3_content_signal(body, names=names)


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


def auto_sent(body: str, names: tuple[str, ...] = EXTRA_NAMES) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench, names=names)
    card = bench.ap.preview(USER, *pair(thread, body))
    assert card.tier == "T2" and card.modifiers == (), f"harmless reply made T3: {body!r}"
    assert (card.level, card.undo_window_s) == ("L2", 60) and card.outbox_id is not None


def greeting(word: str) -> str:
    return f"Hi {word}, works for us."


def signature(word: str) -> str:
    return f"Thanks,\n{word}"


# ---- 1. number word glued to a unit, magnitude or abbreviation is never a name (rules a, b, c) -----------

NUMBER_WORD_NAMES = [
    "Fiftym",
    "Fiftyl",
    "Fiftydollars",
    "Fiftybucks",
    "Fiftyrupees",
    "Fiftyusd",
    "Hundredandfifty",
    "Halfmillion",
    "Fourtythousand",
    "Fiftyb",
    "Fiftyquid",
    "Fiftygrands",
    "Fiftyks",
    "Fiftyish",
    "Fiftypercent",
]


@pytest.mark.parametrize("word", NUMBER_WORD_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r2_greeting_is_unlisted(word: str) -> None:
    body = greeting(word)
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


@pytest.mark.parametrize("word", NUMBER_WORD_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r2_signature_is_unlisted(word: str) -> None:
    body = signature(word)
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


@pytest.mark.parametrize("word", NUMBER_WORD_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r2_greeting_is_t3_at_preview(word: str) -> None:
    never_auto_sent(greeting(word))


@pytest.mark.parametrize("word", NUMBER_WORD_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r2_signature_is_t3_at_preview(word: str) -> None:
    never_auto_sent(signature(word))


# ---- 2. positive controls: real names stay L2 -----------------------------------------------------------------------

REAL_NAMES = [
    "Simone",
    "Tennyson",
    "Emily",
    "Milan",
    "Craig",
    "O'Brien",
    "Mila",
    "Tenzin",
    "Sixtine",
    "David",
    "Miles",
]


def named(name: str) -> str:
    return f"Hi {name},\n\nFriday 2pm works for us.\n\nBest,\nSarah"


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r2_real_name_is_listed(name: str) -> None:
    assert signal(named(name), VOUCHED | name_words(name)) == frozenset(), f"real name {name!r} rejected"


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r2_real_name_still_l2(name: str) -> None:
    auto_sent(named(name), names=(name,))
