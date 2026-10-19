"""CHN-GATE-C round 1 (issue #256, FR-CHN-11, BQ-224): security-review findings. Run-on Title-case words must not pass
as names, allowlisted words that promise or price on their own are not on the list, and a link hidden next to a time
of day is still a link. The 157 pinned tests stay as they are; this file only adds."""

from __future__ import annotations

import time

import pytest
from _chn11_lib import EXTRA_NAMES, EXTRA_WORDS, USER, VOUCHED, autopilot_module, make_bench, pair, scripted_thread


def signal(body: str, names: frozenset[str] = VOUCHED) -> frozenset[str]:
    # CHN-GATE-E: a name rides L2 only when the thread vouches for it; the bench thread vouches for VOUCHED.
    return autopilot_module().t3_content_signal(body, names=names)


def never_auto_sent(body: str) -> None:
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
    assert card.tier == "T2" and (card.level, card.undo_window_s) == ("L2", 60) and card.outbox_id is not None


NAME_RUNS = [
    "Hi David,\n\nFifty Thousand Upfront Approved.\n\nBest,\nSarah",
    "Hi David,\n\nThanks R E F U N D Approved\n\nBest,\nSarah",
    "Hi David,\n\nThanks, Approved.\n\nBest,\nSarah",
    "Hi David,\n\nThanks Prepayment Nonrefundable Upfront.\n\nBest,\nSarah",
    "Hi David,\n\nFifty Thousand works for us.\n\nBest,\nSarah",
    "Hi David,\n\nThanks R,E,F,U,N,D\n\nBest,\nSarah",
    "Hi David,\n\nThanks R\u00b7E\u00b7F\u00b7U\u00b7N\u00b7D\n\nBest,\nSarah",
    "Hi David,\n\nThanks Re\u2013Fund\n\nBest,\nSarah",
    "Hi David,\n\nThanks Re Fund\n\nBest,\nSarah",
    "Hi David,\n\nThanks Re Fund. See you then.\n\nBest,\nSarah",
]
PROMISES = [
    "Will do, thanks.",
    "Lunch is on us.",
    "It's all yours.",
    "You will have it back by Friday.",
    "Our office will have it back to you by Monday.",
    "We should have it back to you by Friday.",
    "Yes, we can do it for free.",
]
HIDDEN_LINKS = [
    "See you at 5pm.me",
    "See you at meet.10am.us",
    "Thanks David.10am.to",
    "See you at example\u3002com",
    "See you at example\uff61com",
]


@pytest.mark.parametrize("body", NAME_RUNS)
def test_CHN_GATE_C_R1_FR_CHN_11_runs_of_title_case_words_are_not_names(body: str) -> None:
    assert "unlisted" in signal(body)
    never_auto_sent(body)


@pytest.mark.parametrize("text", PROMISES)
def test_CHN_GATE_C_R1_FR_CHN_11_allowlisted_words_that_promise_on_their_own_never_ride_l2(text: str) -> None:
    assert signal(f"Hi David,\n\n{text}\n\nBest,\nSarah")
    never_auto_sent(f"Hi David,\n\nFriday 2pm works for us. {text}\n\nBest,\nSarah")


@pytest.mark.parametrize("text", HIDDEN_LINKS)
def test_CHN_GATE_C_R1_FR_CHN_11_a_link_next_to_a_time_of_day_is_still_a_link(text: str) -> None:
    assert signal(text)
    never_auto_sent(f"Hi David,\n\n{text}\n\nBest,\nSarah")


@pytest.mark.parametrize(
    "body",
    [
        "Hi David,\n\nThanks David, Friday 2pm works for us.\n\nBest,\nSarah",
        "Hi Anna Maria,\n\nSee you then.\n\nThanks,\n\nSarah",
        "Hi David,\n\nTuesday at 3:30 PM works for us.\n\nCheers,\nSarah Jones",
        "Hi David,\n\nSounds good, talk soon. Thanks David, see you Tuesday.\n\nBest,\nSarah",
    ],
)
def test_CHN_GATE_C_R1_FR_CHN_11_names_after_greetings_and_sign_offs_still_ride_l2(body: str) -> None:
    assert signal(body, VOUCHED | EXTRA_WORDS) == frozenset()
    auto_sent(body)


def test_CHN_GATE_C_R1_FR_CHN_11_a_huge_nfkc_expansion_is_cut_short() -> None:
    start = time.perf_counter()
    assert "obfuscated" in signal("\ufdfa" * 19_999)
    assert time.perf_counter() - start < 2.0
