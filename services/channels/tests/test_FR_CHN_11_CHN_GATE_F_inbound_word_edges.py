"""CHN-GATE-F (BQ-274 follow-up, issue #298; FR-CHN-11; ADR-0013; PRD 10.4 T3 "money, contract or legal terms"):
`inbound_signal` must see a number word glued to a unit, with correct word edges.

Gap. The inbound check matches `_NUMBER_WORD` as a whole word only, so a glued amount in text the sender chose (a From
display name such as "Tenrm", "Fiftydollars", "Halfmillion", "Fiftym" or "Tenkk" repeated in the signature, a greeting
or the Subject) is "plain" and has no signal. A draft that echoes it ("Hi Tenkk,") is then clean at the outbound gate
(`t3_content_signal`), so the pair rode L2 with no person.

Rule pinned here. With the same word edges as the outbound name rule (`_numberish`, CHN-GATE-D r2 and r3): a token is a
"money" signal when it is number words followed by at most a unit, where a unit is k, m, b, l, ks (a magnitude
suffix) or any word the money family matches (rm, fee, cash, price, deposit, bucks, dollars, usd, rupees, quid, grand,
...), or when it holds hundred, thousand, million, billion, lakh or crore. The inbound signal is case-blind. An
ordinary word that only contains a number word ("Tenant", "often", "phones", "Milan") has no signal and stays plain, so
a real reply to it still rides L2.

Defaults applied (PRD names no inbound families; issue #298, BQ-274, BQ-224):
- The units come from the money family itself, not from a copied list: a guard test checks that every unit used here is
  one the money family matches (a unit sample that the family does not know would be a wrong test, not a wrong rule).
- "Tenkk" (the ticket names it) is read as number word + a repeated magnitude suffix: money. The outbound name rule
  catches it only as a name; the inbound check has to catch it as an amount.
- The unit "s" is NOT a unit here: "ones" ("which ones work for you?") is ordinary talk. The outbound name rule counts
  "s" because a name slot has no other use for "Tens"; free inbound text does.
- "Fifty-fifty" (BQ-274: a hyphen is not a join of number words with a unit) has no signal; it still waits at L1
  because a hyphen is not plain, which is the existing rule and is not pinned here.
- "Million Dollar Baby" keeps its decision: "money" (it holds a whole-word `dollar`).
- Not pinned either way: "hundredth" and "thousandth" (an ordinal that holds a magnitude), "Hundredandfifty",
  "Fiftyish", prefixed forms ("MrTenrm"), and number words split by spaces ("Ten rm", an accepted gap since BQ-274).
Existing tests are not edited. No network, no model, no real mail."""

from __future__ import annotations

import time
from typing import Any

import pytest
from _chn11_inbound_lib import (
    KINDS,
    SCHEDULING_INBOUND,
    assert_rides_l2,
    assert_waits_for_a_person,
    inbound_plain,
    inbound_signal,
    is_clean,
    make_l2,
)
from hypothesis import given, settings
from hypothesis import strategies as st

YES = "Yes, confirmed."

# ---- vocabulary --------------------------------------------------------------------------------------------------

# The reviewer's and the ticket's glued tokens: each is a number word glued to a unit or a magnitude.
GLUED = [
    "Tenrm",
    "Fiftydollars",
    "Halfmillion",
    "Fiftym",
    "Tenkk",
    "Sixrm",
    "Tenfee",
    "Onemil",
    "Tenk",
    "Fourtythousand",
    "Fiftyusd",
]
# The same tokens as the e2e tests use: one per way the money is spelled (unit word, magnitude inside, suffix, kk).
GLUED_E2E = ["Tenrm", "Halfmillion", "Tenkk"]

# Real names and ordinary words that only CONTAIN a number word (a prefix, a suffix or a middle part).
REAL_NAMES = ["Tenant", "Tenzin", "Tennyson", "Sixtine", "Milan", "Miles", "Craig", "Mila", "Simone", "David"]
ORDINARY_SENTENCES = [
    "Which ones work for you?",
    "Can you bring the phones and the stones on Friday?",
    "Is anyone free, or has someone gone home?",
    "Often written, rarely listened to: the kitten sat alone.",
    "Can Marcus come on the tenth or the fourteenth?",
    "The tenant is happy to meet at 3pm.",
]

# Number words and units for the property test. The money units are checked against the money family (guard test).
NUMBER_WORDS = [
    "one", "two", "six", "ten", "eleven", "twenty", "fifty", "ninety", "hundred", "thousand", "million", "billion",
    "lakh", "crore",
]  # fmt: skip
MONEY_UNITS = [
    "rm", "fee", "cash", "price", "deposit", "bucks", "dollars", "usd", "rupees", "quid", "grand", "bank", "wire",
    "refund", "invoice", "pay", "loan", "euros",
]  # fmt: skip
SUFFIX_UNITS = ["k", "m", "b", "l", "ks", "kk"]


def money(text: str) -> bool:
    return "money" in inbound_signal(text)


def in_shapes(token: str) -> list[str]:
    """The three places a sender's text lands in a reply the draft answers: a greeting, mid-sentence, a signature."""
    return [
        f"Hi {token}, can Marcus come by this Friday afternoon?",
        f"Can you confirm the {token} for Friday?",
        f"Hi Sarah,\n\nCan Marcus come by this Friday afternoon?\n\nBest,\n{token}",
    ]


def card(kind: str, inbound: str, body: str = YES, **kw: Any):
    h = make_l2(kind)
    p, ctx, _ = h.preview(h.thread(inbound, **kw), body)
    return h, p, ctx


# ---- 1. negatives: a glued number word + unit is a money signal ---------------------------------------------------


@pytest.mark.parametrize("token", GLUED)
def test_FR_CHN_11_CHN_GATE_F_glued_number_word_is_money_in_every_place(token: str) -> None:
    for text in in_shapes(token):
        assert money(text), f"inbound_signal missed the glued amount {token!r} in {text!r}"
        assert not is_clean(text), f"{text!r} would still ride L2"


@pytest.mark.parametrize("token", ["Tenrm", "Fiftydollars", "Halfmillion", "Tenkk"])
def test_FR_CHN_11_CHN_GATE_F_glued_signal_ignores_case(token: str) -> None:
    for variant in (token.lower(), token.upper(), token.swapcase()):
        assert money(f"Best,\n{variant}"), f"case change hid {token!r} as {variant!r}"


@pytest.mark.parametrize("token", ["Fiftydollars", "Tenkk"])
def test_FR_CHN_11_CHN_GATE_F_glued_amount_at_the_end_of_a_long_plain_body(token: str) -> None:
    body = "Can Marcus come by this Friday afternoon? " * 450 + token  # about 18,000 characters, no cut, no hit before
    assert len(body) < 20_000
    assert money(body)


def test_FR_CHN_11_CHN_GATE_F_units_in_this_file_are_money_family_words() -> None:
    """Guard: a unit that the money family does not know would make the property below a wrong test."""
    for unit in MONEY_UNITS:
        assert "money" in inbound_signal(f"the {unit}"), f"{unit!r} is not in the money family"


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    word=st.sampled_from(NUMBER_WORDS),
    unit=st.sampled_from([*MONEY_UNITS, *SUFFIX_UNITS]),
    style=st.sampled_from(["lower", "title", "upper"]),
)
def test_FR_CHN_11_CHN_GATE_F_property_number_word_glued_to_a_unit_is_money(word: str, unit: str, style: str) -> None:
    glued = f"{word}{unit}"
    token = {"lower": glued.lower(), "title": glued.title(), "upper": glued.upper()}[style]
    for text in (f"Best,\n{token}", f"Can you confirm the {token} for Friday?"):
        assert money(text), f"{token!r} glued from {word!r} + {unit!r} has no money signal in {text!r}"


# ---- 2. the L2 outcome: a card answering such a message waits for a person -----------------------------------------


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("token", GLUED_E2E)
def test_FR_CHN_11_CHN_GATE_F_glued_amount_in_the_signature_keeps_a_clean_draft_off_l2(kind: str, token: str) -> None:
    h, p, ctx = card(kind, in_shapes(token)[2])
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("token", ["Tenrm", "Fiftydollars", "Halfmillion", "Tenkk"])
def test_FR_CHN_11_CHN_GATE_F_glued_amount_in_the_subject_keeps_a_clean_draft_off_l2(token: str) -> None:
    h, p, ctx = card("policy_port", SCHEDULING_INBOUND, subject=f"Re: {token} on Friday")
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_CHN_GATE_F_draft_that_echoes_a_glued_sender_name_waits_for_a_person(kind: str) -> None:
    """The reported path: the sender's display name is "Tenkk", the draft greets and signs with it. The draft alone
    is clean at the outbound gate, so only the inbound check can hold the pair."""
    inbound = in_shapes("Tenkk")[2]
    echo = "Hi Tenkk,\n\nFriday 2pm works for us.\n\nBest,\nSarah"
    h, p, ctx = card(kind, inbound, echo)
    assert_waits_for_a_person(h, p, ctx)


# ---- 3. positives: ordinary words and real names stay clean and ride L2 --------------------------------------------


@pytest.mark.parametrize("name", REAL_NAMES)
def test_FR_CHN_11_CHN_GATE_F_real_name_has_no_signal_and_is_plain(name: str) -> None:
    for text in in_shapes(name):
        assert inbound_signal(text) == frozenset(), f"real name {name!r} flagged in {text!r}"
        assert inbound_plain(text), f"real name {name!r} made {text!r} not plain"


@pytest.mark.parametrize("sentence", ORDINARY_SENTENCES, ids=lambda s: s[:24])
def test_FR_CHN_11_CHN_GATE_F_ordinary_words_that_contain_a_number_word_stay_clean(sentence: str) -> None:
    assert inbound_signal(sentence) == frozenset(), f"false positive on {sentence!r}"
    assert inbound_plain(sentence)


@pytest.mark.parametrize("name", ["Tenant", "Tenzin", "Milan"])
def test_FR_CHN_11_CHN_GATE_F_real_name_in_the_signature_still_rides_l2(name: str) -> None:
    h, p, _ = card("policy_port", in_shapes(name)[2])
    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_CHN_GATE_F_which_ones_work_still_rides_l2(kind: str) -> None:
    h, p, _ = card(kind, "Hi Sarah, which ones work for you on Friday afternoon?")
    assert_rides_l2(h, p)


def test_FR_CHN_11_CHN_GATE_F_decided_cases_keep_their_decisions() -> None:
    assert money("Million Dollar Baby"), "a whole-word dollar is money (BQ-274)"
    assert "money" not in inbound_signal("Fifty-fifty"), "a hyphen between number words is no unit (BQ-274)"


def test_FR_CHN_11_CHN_GATE_F_word_edge_scan_is_linear_on_a_20k_plain_field() -> None:
    """A long ordinary field full of near-misses (Tenant, ones, phones) is clean and read in under 150 ms (best of 3),
    the bound the piece-join scan already holds."""
    text = ("Tenant ones phones kitten often. " * 600)[:19_900]
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        signal = inbound_signal(text)
        best = min(best, time.perf_counter() - start)
    assert signal == frozenset()
    assert best < 0.15, f"{best:.3f}s for a 20k plain field"
