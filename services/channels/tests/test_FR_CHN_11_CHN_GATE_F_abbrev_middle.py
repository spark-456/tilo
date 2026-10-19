"""CHN-GATE-F security fix (BQ-274; FR-CHN-11; issue #298): a counting word, then abbreviation words, then a unit.

Gap closed here. The first cut of the glued-word rule allowed counting words and then ONE unit, so "Fivelacrupees",
"Tenmildollars", "Twocrrupees", "Fivemnusd" and "Fivelacsrupees" (the outbound name rule `_numberish` catches all
five) had no inbound signal and the reply rode L2. The abbreviation words (mil, mn, bn, cr, lac, lacs) may stand
between the counting words and the unit. Counting word x abbreviation x every unit is checked, the units being
the money family's own alternatives (checked against `_MONEY`) and the magnitude suffixes. Real words that only start
with an abbreviation (milk, lacks, Milan, Craig) still need a counting word first and stay plain.
Existing tests are not edited. No network, no model, no real mail."""

from __future__ import annotations

import itertools
import re
import time

import pytest
from _chn11_inbound_lib import KINDS, assert_waits_for_a_person, inbound_plain, inbound_signal, is_clean, make_l2
from tilo_channels import autopilot_t3

COUNTING = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty",
    "fifty", "sixty", "seventy", "eighty", "ninety", "dozen",
]  # fmt: skip
ABBREVIATIONS = ["mil", "mn", "bn", "cr", "lac", "lacs"]
# One spelling for each alternative of the money family that can be glued (no space inside, no digits).
MONEY_UNITS = [
    "refund", "refunds", "invoice", "invoices", "pay", "pays", "paid", "payment", "payments", "payable", "wire",
    "wires", "wired", "wiring", "bank", "banks", "iban", "swift", "deposit", "deposits", "price", "prices", "pricing",
    "cost", "costs", "fee", "fees", "charge", "charges", "discount", "quote", "quotes", "quoted", "quotation",
    "estimate", "estimates", "rate", "rates", "money", "cash", "billing", "budget", "dollar", "dollars", "euro",
    "euros", "pound", "pounds", "rupee", "rupees", "usd", "eur", "gbp", "inr", "sgd", "aud", "cad", "jpy", "chf",
    "transfer", "transfers", "paypal", "venmo", "zelle", "btc", "bitcoin", "owe", "owes", "owed", "owing", "loan",
    "loans", "penalty", "penalties", "buck", "bucks", "grand", "quid", "rs", "rm",
]  # fmt: skip
SUFFIX_UNITS = ["k", "m", "b", "l", "ks", "kk"]


def _alternatives() -> list[str]:
    """The top-level alternatives of `_MONEY`, split outside parentheses."""
    body = autopilot_t3._MONEY.pattern.removeprefix(r"\b(?:").removesuffix(r")\b")
    parts, depth, current = [], 0, ""
    for c in body:
        depth += (c == "(") - (c == ")")
        if c == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += c
    return [*parts, current]


def test_FR_CHN_11_CHN_GATE_F_abbrev_middle_unit_list_covers_the_money_family() -> None:
    """Guard: every unit is a money word, and every glue-able alternative of `_MONEY` has a unit here."""
    for unit in MONEY_UNITS:
        assert autopilot_t3._MONEY.fullmatch(unit), f"{unit!r} is not in the money family"
    for alt in _alternatives():
        if r"\s" in alt or r"\d" in alt:
            continue  # a phrase with a space, a digit shape: nothing to glue
        assert any(re.fullmatch(alt, unit) for unit in MONEY_UNITS), f"no unit covers the alternative {alt!r}"


@pytest.mark.parametrize("abbreviation", ABBREVIATIONS)
def test_FR_CHN_11_CHN_GATE_F_abbrev_middle_every_counting_word_and_unit_is_money(abbreviation: str) -> None:
    misses = [
        token
        for counting, unit in itertools.product(COUNTING, [*MONEY_UNITS, *SUFFIX_UNITS])
        for token in (f"{counting}{abbreviation}{unit}",)
        if "money" not in inbound_signal(f"Best,\n{token}")
    ]
    assert not misses, f"{len(misses)} glued amounts have no money signal, for example {misses[:5]}"


@pytest.mark.parametrize("token", ["Fivelacrupees", "Tenmildollars", "Twocrrupees", "Fivemnusd", "Fivelacsrupees"])
def test_FR_CHN_11_CHN_GATE_F_abbrev_middle_reported_tokens_in_every_place(token: str) -> None:
    for text in (
        f"Hi {token}, can Marcus come by this Friday afternoon?",
        f"Hi Sarah,\n\nCan you confirm the {token} for Friday?\n\nBest,\nDavid",
        f"Hi Sarah,\n\nCan Marcus come by this Friday afternoon?\n\nBest,\n{token.upper()}",
    ):
        assert "money" in inbound_signal(text)
        assert not is_clean(text)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("token", ["Fivelacrupees", "Tenmildollars"])
def test_FR_CHN_11_CHN_GATE_F_abbrev_middle_clean_draft_waits_for_a_person(kind: str, token: str) -> None:
    h = make_l2(kind)
    inbound = f"Hi Sarah,\n\nCan you confirm the {token} for Friday?\n\nBest,\nDavid"
    p, ctx, _ = h.preview(h.thread(inbound), "Yes, confirmed.")
    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("word", ["milk", "lacks", "Milan", "Craig", "mill", "crowd", "mnemonic", "bnb", "lacrosse"])
def test_FR_CHN_11_CHN_GATE_F_abbrev_middle_words_that_start_with_an_abbreviation_stay_plain(word: str) -> None:
    text = f"Hi Sarah,\n\nCan you bring the {word} on Friday?\n\nBest,\nDavid"
    assert inbound_signal(text) == frozenset()
    assert inbound_plain(text)


@pytest.mark.parametrize(
    "text",
    [
        "ten" + "mil" * 6600 + "x",  # a long run of abbreviations, then a word that is no unit
        "ten" * 6600 + "x",
        ("ten" + "lacs") * 2800 + "x",
        "ten" + "mn" * 9900 + "k" + "x",
        ("tenmilcr" * 2400) + "x",
    ],
    ids=["abbrev-run", "counting-run", "alternating", "mn-run", "mixed-run"],
)
def test_FR_CHN_11_CHN_GATE_F_abbrev_middle_scan_is_linear_on_a_20k_field(text: str) -> None:
    assert len(text) < 20_000
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        inbound_signal(text)
        best = min(best, time.perf_counter() - start)
    assert best < 0.15, f"{best:.3f}s for a 20k field"
