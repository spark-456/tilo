"""CHN-GATE-D fix pass r3 (PR #525, Opus security verdict r3 at b6f77554; FR-CHN-11; ADR-0013; PRD 10.4 T3 "money,
contract or legal terms"): a short number word glued to ANY money word of the money family is never a name.

Rule pinned here (verdict r3): the unit of rule (a) comes from the money family itself, not from a copied list. With
apostrophes dropped, a name word is never a name when it is number words followed by at most one unit, where unit is
k, m, b, l, s, ks, grand(s) or any word the money family matches (rm, fee, cash, price, deposit, bucks, ...). Such a
body is "unlisted", so T3 and never L2 at preview. Only the three-letter number words (one, two, six, ten) and the
abbreviations are affected: a number word of 4+ letters is caught by rule (b).

Defaults applied (issue #298 and the PR #525 verdicts; BQ-224): bodies of the greeting shape "Hi X, works for us.",
the signature shape "Thanks,\\nX", the two-word form "Te Nrm" and the repeat shape. Real names stay L2 as positive
controls so an over-tight fix fails. Crowe and Milbank going T3 is an accepted false positive and is not pinned either
way. Existing GATE_D tests are not edited."""

from __future__ import annotations

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


# ---- 1. the reviewer's bodies: short number word + a money word outside the old copied list --------------------------

R3_BODIES = [
    "Hi Tenrm, works for us.",
    "Hi Sixrm, works for us.",
    "Hi Tenfee, works for us.",
    "Hi Tencash, works for us.",
    "Hi Tenprice, works for us.",
    "Hi Tendeposit, works for us.",
    "Hi Te Nrm, works for us.",
    "Hi Tenrm,\n\nThanks Tenrm, works for us.",
    "Thanks,\nTenrm",
    # a 3-letter number word and a unit (r3 follow-up: the r2 file had none)
    "Hi Tenk, works for us.",
    "Hi Sixbucks, works for us.",
    "Hi Onemil, works for us.",
    "Thanks,\nTenk",
    "Thanks,\nSixbucks",
    "Thanks,\nOnemil",
]


@pytest.mark.parametrize("body", R3_BODIES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r3_body_is_unlisted(body: str) -> None:
    assert "unlisted" in signal(body), f"allowlist let {body!r} through"


@pytest.mark.parametrize("body", R3_BODIES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r3_body_is_t3_at_preview(body: str) -> None:
    never_auto_sent(body)


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
    "Miles",
    "David",
]


def named(name: str) -> str:
    return f"Hi {name},\n\nFriday 2pm works for us.\n\nBest,\nSarah"


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r3_real_name_is_listed(name: str) -> None:
    assert signal(named(name)) == frozenset(), f"real name {name!r} rejected"


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r3_real_name_still_l2(name: str) -> None:
    auto_sent(named(name))


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_D_numberword_r3_real_name_signature_still_l2(name: str) -> None:
    auto_sent(f"Friday 2pm works for us.\n\nBest,\n{name}")
