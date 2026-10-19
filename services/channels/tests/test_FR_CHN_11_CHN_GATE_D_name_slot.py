"""CHN-GATE-D (issue #298, "CHN-GATE-C" section; FR-CHN-11; ADR-0013; PRD 10.4 T3 "money, contract or legal terms"):
the L2 allowlist of `autopilot_t3` is body-only, so the name slot (the greeting's and the signature's run) must not let
a non-name run ride L2. Anything off the allowlist is "unlisted": T3, which waits for a person.

Defaults applied (issue #298, the "short of participants" fallback; BQ-224):
 - `t3_content_signal(text)` and `Autopilot.preview(user, ctx, result)` carry no thread participants (From/To/Cc), so
   the participant-name option of the issue is not reachable and is not tested. The fallback rule is: a name run ends
   only with "," or "!" or a blank line; the signature run must end its line; "-" and "_" between letters join (as
   `_SPLIT` does), so "Hi Fifty Thousand-ok" is one non-name token. "Hi Fifty Thousand, works for us." is the one
   listed body the fallback alone does not catch (a comma legitimately ends a greeting run); it is pinned in its own
   test and needs a number word ("fifty", "thousand", "million", ...) to disqualify a word from a name run.
 - Repeats of the name run's words are allowed only after a greeting word that opens a line or a clause
   ("Thanks David, ..." at the start of a sentence), not after "good", "you" or "morning" in the middle of one.
 - Repeats are pinned only where the run ends in a comma; whether "Thanks David." (full stop) may repeat is left open.

Existing FR-CHN-11 / GATE_C tests stay as they are; their benign lines are reused as positives so an over-tight fix
fails. Invisible characters would be written as \\u escapes (none are needed here)."""

from __future__ import annotations

import pytest
from _chn11_lib import EXTRA_NAMES, EXTRA_WORDS, USER, VOUCHED, autopilot_module, make_bench, pair, scripted_thread
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


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


def assert_unlisted_and_t3(body: str) -> None:
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"
    never_auto_sent(body)


# ---- 1. name slot: a non-name run in the greeting or signature slot does not ride L2 -------------------------------

# The issue's eight bodies minus the one a comma-ended run cannot reject (next test).
NAME_SLOT_NON_NAMES = [
    "Hi Fifty Thousand? Yes, works for us.",
    "Hi Fifty Thousand\nworks for us.",
    "Best,\nFifty Thousand, works for us.",
    "Hi Fifty Thousand: confirmed.",
    "Hi Fifty Thousand = ok.",
    "Hi Fifty Thousand-ok.",
    "Hi Fifty Thousand_works for us.",
]


@pytest.mark.parametrize("body", NAME_SLOT_NON_NAMES)
def test_FR_CHN_11_CHN_GATE_D_name_slot_rejects_fifty_thousand(body: str) -> None:
    assert_unlisted_and_t3(body)


def test_FR_CHN_11_CHN_GATE_D_name_slot_rejects_number_word_run_before_comma() -> None:
    # Not fixable by the end-of-run rule alone: "," ends a greeting run. A number word is never a name.
    assert_unlisted_and_t3("Hi Fifty Thousand, works for us.")


@pytest.mark.parametrize(
    "body",
    [
        "Hi David, works for us.\n\nBest,\nSarah",
        "Hi Anna Maria,\n\nSee you then.\n\nThanks,\n\nSarah",
        "Hi David!\n\nFriday 2pm works for us.\n\nBest,\nSarah",
        "Hi David\n\nFriday 2pm works for us.\n\nBest,\nSarah",
        "Hi David,\n\nTuesday at 3:30 PM works for us.\n\nCheers,\nSarah Jones",
    ],
)
def test_FR_CHN_11_CHN_GATE_D_name_slot_comma_bang_and_blank_line_still_end_a_run(body: str) -> None:
    assert signal(body, VOUCHED | EXTRA_WORDS) == frozenset()
    auto_sent(body)


TERMINATORS = ["?", ":", "=", ";", " - ok", "-ok", "_ok", "\nworks for us."]


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    run=st.sampled_from(["Fifty Thousand", "Upfront Approved", "Prepayment Nonrefundable"]),
    end=st.sampled_from(TERMINATORS),
)
def test_FR_CHN_11_CHN_GATE_D_property_greeting_run_ended_by_other_than_comma_bang_blank_is_never_l2(
    run: str, end: str
) -> None:
    body = f"Hi {run}{end} works for us."
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    run=st.sampled_from(["Fifty Thousand", "Upfront Approved", "Prepayment Nonrefundable"]),
    end=st.sampled_from([t for t in TERMINATORS if "\n" not in t]),
)
def test_FR_CHN_11_CHN_GATE_D_property_signature_run_must_end_its_line(run: str, end: str) -> None:
    body = f"Hi David,\n\nSee you then.\n\nBest,\n{run}{end} works for us."
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


# ---- 2. repeats only after a greeting word that opens a line or clause -----------------------------------------------

# CHN-GATE-E (ADR-0025, "Heuristics this retires"): the clause-opener rule is gone. A repeat of a VOUCHED name ("Sounds
# good David.") no longer needs to follow a greeting word that opens a clause: those four bodies moved to the second
# list and ride L2. What stays pinned as T3 is a repeat of a name nobody vouched for.
MID_SENTENCE_REPEATS = [
    "Hi Fifty Thousand,\n\nSounds good Fifty Thousand.\n\nBest,\nSarah",
    "Hi Fifty Thousand,\n\nSee you fifty thousand.\n\nBest,\nSarah",
]
VOUCHED_MID_SENTENCE_REPEATS = [
    "Hi David,\n\nSounds good David.\n\nBest,\nSarah",
    "Hi David,\n\nSee you David.\n\nBest,\nSarah",
    "Hi David,\n\nSee you Friday morning David.\n\nBest,\nSarah",
    "Hi David,\n\nSounds good Sarah.\n\nBest,\nSarah",
]


@pytest.mark.parametrize("body", MID_SENTENCE_REPEATS)
def test_FR_CHN_11_CHN_GATE_D_repeat_after_mid_sentence_greeting_word_rejected(body: str) -> None:
    assert_unlisted_and_t3(body)


@pytest.mark.parametrize("body", VOUCHED_MID_SENTENCE_REPEATS)
def test_FR_CHN_11_CHN_GATE_D_repeat_of_a_vouched_name_mid_sentence_rides_l2_after_adr_0025(body: str) -> None:
    assert signal(body) == frozenset()
    auto_sent(body)


@pytest.mark.parametrize(
    "body",
    [
        "Hi David,\n\nThanks David, Friday 2pm works for us.\n\nBest,\nSarah",
        "Hi David,\n\nSounds good, talk soon. Thanks David, see you Tuesday.\n\nBest,\nSarah",
        "Hi David,\n\nSee you then.\nThanks David, Friday 2pm works.\n\nBest,\nSarah",
    ],
)
def test_FR_CHN_11_CHN_GATE_D_repeat_after_line_or_clause_opening_greeting_word_still_rides_l2(body: str) -> None:
    assert signal(body, VOUCHED | EXTRA_WORDS) == frozenset()
    auto_sent(body)


# ---- 3. regression: legitimate L2 bodies stay on L2 (an over-tight fix must fail) ------------------------------------

LEGIT = [
    "Hi Pat,\nThanks, see you then.\nBest,\nAlex",  # a one-line signature right after the sign-off line
    "Hi David,\n\nThanks, see you Tuesday.\n\nBest,\nSarah",
    "Hi David,\n\nFriday 2pm works for us.\n\nBest,\nSarah",
    "Good morning David,\n\nFriday 2pm works for us.\n\nKind regards,\nSarah",
    "Hi David,\n\nTuesday at 3:30 PM works for us.\n\nCheers,\nSarah Jones",
    "Thanks, see you Tuesday.",
    "Sounds good, talk soon.",
]


@pytest.mark.parametrize("body", LEGIT)
def test_FR_CHN_11_CHN_GATE_D_legit_scheduling_bodies_still_ride_l2(body: str) -> None:
    assert signal(body, VOUCHED | EXTRA_WORDS) == frozenset()
    auto_sent(body)
