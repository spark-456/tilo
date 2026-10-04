"""CHN-GATE-C round 2 (issue #256, FR-CHN-11, BQ-186): security-review findings. A name may only be the greeting's
run, the signature's run, or a repeat of their words, so greeting and sign-off words no longer open new name slots;
a time of day ends a run; and "do", "have" and "back" are off the list ("on it" is a commitment). The 157 pinned
tests and the round 1 file stay as they are; this file only adds."""

from __future__ import annotations

import pytest
from _chn11_lib import USER, autopilot_module, make_bench, pair, scripted_thread


def signal(body: str) -> frozenset[str]:
    return autopilot_module().t3_content_signal(body)


def never_auto_sent(body: str) -> None:
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


CHAINED_NAMES = [
    "Hi David,\n\nThanks\nFifty Thousand\nUpfront Approved\n\nBest,\nSarah",
    "Hi David,\n\nThanks Fifty Thousand. Thanks Upfront Approved.\n\nBest,\nSarah",
    "Hi David,\n\nThanks Fifty Thousand\nThanks Upfront Approved\n\nBest,\nSarah",
    "Hi\nFifty Thousand\nUpfront Approved\n\nBest,\nSarah",
    "Hi David,\n\nSee you then.\n\nBest,\nSarah\nUpfront Approved",
    "Hi Re,\n\nThanks Re Fund\n\nBest,\nFund",
]
TIME_IN_A_RUN = ["Thanks Fifty 5pm Thousand.", "Thanks 11:50 Upfront."]
PROMISES = [
    "We can have it back to you by Friday.",
    "Sure, you could have it all back by Monday.",
    "Yes, we can do that today.",
    "Happy to do it.",
    "Yes, we're on it.",
]
CONTROLS = [
    "Hi David,\n\nThanks David, Friday 2pm works for us.\n\nBest,\nSarah",
    "Hi Anna Maria,\n\nSee you then.\n\nThanks,\n\nSarah",
    "Hi David,\n\nTuesday at 3:30 PM works for us.\n\nCheers,\nSarah Jones",
    "Hi David,\n\nSounds good, talk soon. Thanks David, see you Tuesday.\n\nBest,\nSarah",
    "Good morning David,\n\nFriday 2pm works for us.\n\nKind regards,\nSarah",
    "Hi David,\n\n" + "Friday 2pm works for us. See you then. " * 40 + "\n\nBest,\nSarah",
]


@pytest.mark.parametrize("body", CHAINED_NAMES)
def test_CHN_GATE_C_R2_FR_CHN_11_names_outside_the_greeting_and_signature_runs_never_ride_l2(body: str) -> None:
    assert "unlisted" in signal(body)
    never_auto_sent(body)


@pytest.mark.parametrize("text", TIME_IN_A_RUN)
def test_CHN_GATE_C_R2_FR_CHN_11_a_time_of_day_ends_a_name_run(text: str) -> None:
    assert "unlisted" in signal(text)
    assert "unlisted" in signal(f"Hi David,\n\n{text}\n\nBest,\nSarah")
    never_auto_sent(f"Hi David,\n\n{text}\n\nBest,\nSarah")


@pytest.mark.parametrize("text", PROMISES)
def test_CHN_GATE_C_R2_FR_CHN_11_list_only_promises_never_ride_l2(text: str) -> None:
    assert signal(text)
    assert signal(f"Hi David,\n\n{text}\n\nBest,\nSarah")
    never_auto_sent(f"Hi David,\n\n{text}\n\nBest,\nSarah")


@pytest.mark.parametrize("body", CONTROLS)
def test_CHN_GATE_C_R2_FR_CHN_11_greeting_signature_and_repeated_names_still_ride_l2(body: str) -> None:
    assert len(body) <= 2_000
    assert signal(body) == frozenset()
    auto_sent(body)
