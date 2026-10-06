"""CHN-GATE-C round 3 (issue #256, FR-CHN-11, BQ-224): security-review finding. A name run is at most two words, starts
right after a greeting word or opens the signature line, and is followed by punctuation or the line end, never a word,
so a run can only be a vocative or a signature and never the subject of a sentence made of listed words. The pinned
tests and the round 1 and 2 files stay as they are; this file only adds."""

from __future__ import annotations

import pytest
from _chn11_lib import USER, autopilot_module, make_bench, pair, scripted_thread

SUBJECT_RUNS = [
    "Hi Fifty Thousand works for us.\n\nBest,\nSarah",
    "Thanks,\nFifty Thousand works for us.",
    "Hi David,\n\nSee you then.\n\nBest,\nFifty Thousand works for us.",
    "Hi Fifty Thousand,\n\nFifty Thousand works for us.\n\nBest,\nSarah",
    "Hi Fifty Thousand,\n\nFifty Thousand Upfront Approved.\n\nBest,\nUpfront Approved",
]


@pytest.mark.parametrize("body", SUBJECT_RUNS)
def test_CHN_GATE_C_R3_FR_CHN_11_a_name_run_followed_by_a_word_never_rides_l2(body: str) -> None:
    assert autopilot_module().t3_content_signal(body)
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, body))
    assert card.tier == "T3" and "money_or_legal" in card.modifiers, f"auto-send allowed for {body!r}"
    assert (card.level, card.undo_window_s, card.outbox_id) == ("L1", 0, None)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}, "T3 is never scheduled without a person"
