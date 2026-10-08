"""CHN-GATE-E (FR-CHN-11; ADR-0025 decisions 5 and 6; PRD 10.4: L2 is for T2 only, "money, contract or legal terms" is
T3): `t3_content_signal(text, names=frozenset())`, the L2 allowlist with the name slot checked against a set of names.

A word passes the allowlist if it is on the list (`_WORDS`, with the greeting and sign-off words added) or in `names`.
`names` is what `Autopilot` builds from the draft's own To and Cc and the mailbox (ADR-0025 decision 5); here it is
given directly. No names, the default, fails closed. The position rules of PR #525 (greeting run, signature line,
Title case, clause openers, number words in the body) are retired: a name passes anywhere, and the number checks live
in the participants' name filter (`test_FR_CHN_11_CHN_GATE_E_participants.py`). Everything else stays: families,
digits that are not a time of day, links, obfuscation, SHORT_BODY_MAX, the two-word row cap, the join checks.
"""

from __future__ import annotations

import pytest
from _chn11_lib import autopilot_module
from _chn_gate_e_lib import listed_words
from hypothesis import assume, given, settings
from hypothesis import strategies as st

NAMES = frozenset({"david", "sarah", "anna", "maria", "marcus", "priya"})


def signal(body: str, names: frozenset[str] | None = None) -> frozenset[str]:
    fn = autopilot_module().t3_content_signal
    return fn(body) if names is None else fn(body, names=names)


# ---- 1. no names fails closed (decision 5) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Hi David, works for us.",
        "Hi David,\n\nFriday 2pm works for us.\n\nBest,\nSarah",
        "Best,\nSarah",
        "Thanks Anna.",
        "Good morning Marcus,\n\nFriday 2pm works for us.\n\nKind regards,\nSarah",
    ],
)
def test_FR_CHN_11_CHN_GATE_E_no_names_fails_closed(body: str) -> None:
    assert "unlisted" in signal(body), f"a name nobody vouched for rode the allowlist: {body!r}"
    assert "unlisted" in signal(body, frozenset()), "an empty `names` is the same as no names"


@pytest.mark.parametrize(
    "body",
    [
        "Hi, works for us.",
        "Hi there,\n\nFriday 2pm works for us.\n\nBest regards",
        "Thanks, see you Tuesday.",
        "Sounds good, talk soon.",
    ],
)
def test_FR_CHN_11_CHN_GATE_E_no_names_needed_when_the_body_names_nobody(body: str) -> None:
    assert signal(body) == frozenset() and signal(body, frozenset()) == frozenset()


def test_FR_CHN_11_CHN_GATE_E_greeting_and_sign_off_words_are_on_the_list() -> None:
    # `_GREETING` and `_SIGN_OFF` words join `_WORDS` (decision 5): "many", "sincerely", "warm wishes" need no name.
    for body in (
        "Many thanks, see you Tuesday.",
        "Hello,\n\nFriday 2pm works.\n\nWarm wishes,\n\nSincerely",
        "Dear all, the meeting works for us.\n\nAll the best",
    ):
        assert signal(body) == frozenset(), body


# ---- 2. a name in `names` passes anywhere (the position rules are retired) -----------------------------------------


@pytest.mark.parametrize(
    ("body", "names"),
    [
        ("Hi David, works for us.", {"david"}),
        ("hi david, works for us.", {"david"}),  # no Title-case rule
        ("HI DAVID, WORKS FOR US.", {"david"}),
        ("Hi David,\n\nFriday 2pm works for us.\n\nBest,\nSarah", {"david", "sarah"}),
        ("Hi David,\n\nSounds good David.\n\nBest,\nSarah", {"david", "sarah"}),  # #525 clause-opener rule retired
        ("Hi David,\n\nSee you Friday morning David.\n\nBest,\nSarah", {"david", "sarah"}),
        ("Friday 2pm works for David.", {"david"}),  # not a greeting or a signature
        ("See you then, David!", {"david"}),
        ("Hi Anna Maria,\n\nSee you then.\n\nThanks,\n\nSarah", {"anna", "maria", "sarah"}),
        ("Hi Anna-Maria, works for us.", {"anna", "maria"}),
        ("Hi David and Priya, works for us.", {"david", "priya"}),  # two rows of one name each
        ("Hi David,\n\nTuesday at 3:30 PM works for us.\n\nCheers,\nSarah Jones", {"david", "sarah", "jones"}),
        ("Hi Pat O'Brien, works for us.", {"pat", "o'brien"}),
        ("Hi Ops, works for us.", {"ops"}),
    ],
)
def test_FR_CHN_11_CHN_GATE_E_names_given_let_a_name_through_anywhere(body: str, names: set[str]) -> None:
    assert signal(body, frozenset(names)) == frozenset(), f"a vouched name was refused: {body!r}"


@pytest.mark.parametrize(
    "body",
    [
        "Hi Marcus, works for us.",  # a name, but not one of these
        "Hi David,\n\nFriday 2pm works for us.\n\nBest,\nSarah Jones",  # "jones" is not in names
        "Hi Zebra Pelican, works for us.",
        "Best,\nFifty Thousand",
        "Hi David, Marcus will be there.",
        "Hi Fifty Thousand, works for us.",
    ],
)
def test_FR_CHN_11_CHN_GATE_E_a_word_not_in_names_or_the_list_is_unlisted(body: str) -> None:
    assert "unlisted" in signal(body, frozenset({"david", "sarah"})), f"allowlist let {body!r} through"


def test_FR_CHN_11_CHN_GATE_E_a_name_is_matched_whole_not_as_a_prefix_or_substring() -> None:
    assert "unlisted" in signal("Hi Davidson, works for us.", frozenset({"david"}))
    assert "unlisted" in signal("Hi Dav, works for us.", frozenset({"david"}))


# ---- 3. the row cap and the family joins stay (decision 5) ----


def test_FR_CHN_11_CHN_GATE_E_a_row_of_name_words_is_at_most_two_long() -> None:
    names = frozenset({"anna", "maria", "lee"})
    assert signal("Hi Anna Maria, works for us.", names) == frozenset()
    assert "unlisted" in signal("Hi Anna Maria Lee, works for us.", names)
    assert "unlisted" in signal("Best,\nAnna Maria Lee", names)


@pytest.mark.parametrize(
    ("body", "names", "family"),
    [
        ("Hi Re Fund, works for us.", {"re", "fund"}, "money"),  # "refund"
        ("Hi Con Tract, works for us.", {"con", "tract"}, "legal"),  # "contract"
    ],
)
def test_FR_CHN_11_CHN_GATE_E_every_join_of_a_name_row_still_runs_through_the_families(
    body: str, names: set[str], family: str
) -> None:
    # PR #525 answers "unlisted" for a join that spells a family word; the family itself is as good.
    assert {"unlisted", family} & signal(body, frozenset(names)), (
        f"a name row that spells a {family} word rode L2: {body!r}"
    )


@pytest.mark.parametrize(
    "body",
    [
        "Hi David, I'll pay the refund.",
        "Hi David, we will confirm Friday.",
        "Hi David, the contract works for us.",
        "Hi David, the price works for us.",
        "Hi David,\n\nFriday works.\n\nBest,\nSarah\n\nI promise.",
        "Hi David, ple​ase wire it.",  # a hidden character
        "Hi Dаvid, works for us.",  # a Cyrillic "a" inside the name: no look-alike ever passes
    ],
)
def test_FR_CHN_11_CHN_GATE_E_a_name_does_not_switch_off_the_other_checks(body: str) -> None:
    assert signal(body, frozenset({"david", "sarah"})) != frozenset(), f"names weakened a check: {body!r}"


# ---- 4. numbers and amounts: the thread never makes one allowed (decision 6) ---------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Hi David, 5000 works for us.",
        "Hi David, 50,000 works for us.",
        "Hi David, fifty thousand works for us.",
        "Hi David, a hundred works for us.",
        "Hi David, ten k works for us.",
        "Hi David, 2 works for us.",
        "Hi David, see www.example.com",
        "Hi David, see https://example.com/x",
        "Hi David, ping me@example.com",
    ],
)
def test_FR_CHN_11_CHN_GATE_E_a_digit_or_number_word_or_link_stays_unlisted_whatever_the_names(body: str) -> None:
    # `names` hold name words only (the filter in `participants` keeps number words out of them, see the participants
    # and autopilot tests), so a digit, a number word or a link is never allowed by a name: a thread that repeats an
    # amount does not make it allowed (PRD 10.4: repeating it back agrees to money terms).
    assert signal(body, frozenset({"david"})) != frozenset(), f"an amount or link rode L2: {body!r}"


def test_FR_CHN_11_CHN_GATE_E_times_of_day_and_the_body_cap_are_unchanged() -> None:
    names = frozenset({"david"})
    assert signal("Hi David, Friday 2pm or 3:30 PM or 14:00 works for us.", names) == frozenset()
    assert "unlisted" in signal("Hi David, Friday works for us. " * 100, names)  # over SHORT_BODY_MAX (2,000)


# ---- 5. the number checks left the body: `names` is trusted as given (the filter is the gate for them) ---------------


def test_FR_CHN_11_CHN_GATE_E_the_body_no_longer_runs_number_word_checks_on_a_name() -> None:
    # PR #525 sent real names such as Crowe to T3 by `_numberish` on the body. That check moved to the participants'
    # name filter; the gate takes `names` as vouched. (The filter still drops "Crowe": `_numberish` is frozen.)
    assert signal("Hi Crowe, works for us.", frozenset({"crowe"})) == frozenset()


# ---- 6. properties ------------------------------------------------------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(word=st.text("abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=14))
def test_FR_CHN_11_CHN_GATE_E_property_a_word_neither_listed_nor_a_name_is_unlisted(word: str) -> None:
    assume(word not in listed_words() and word != "david")
    for body in (f"Hi {word}, works for us.", f"Hi David, works for us.\n\nBest,\n{word}", f"Works for us, {word}."):
        assert "unlisted" in signal(body, frozenset({"david"})), f"allowlist let {body!r} through"


@settings(max_examples=100, deadline=None)
@given(
    first=st.sampled_from(["david", "anna", "marcus", "priya", "tomasz", "kim"]),
    second=st.sampled_from(["lee", "ortiz", "novak", "reyes", "chen", "kaur"]),
    shape=st.sampled_from(
        ["Hi {a},", "Hi {a} {b},", "Hi {a},\n\nFriday 2pm works.\n\nBest,\n{b}", "Thanks {a}. See you {b}."]
    ),
)
def test_FR_CHN_11_CHN_GATE_E_property_names_in_the_set_never_make_a_body_unlisted(
    first: str, second: str, shape: str
) -> None:
    body = shape.format(a=first.title(), b=second.title())
    names = frozenset({first, second})
    assert "unlisted" not in signal(body, names), f"a vouched name made the body unlisted: {body!r}"


@settings(max_examples=100, deadline=None)
@given(extra=st.frozensets(st.sampled_from(["david", "sarah", "marcus", "anna"]), max_size=4))
def test_FR_CHN_11_CHN_GATE_E_property_more_names_never_remove_a_family_signal(extra: frozenset[str]) -> None:
    body = "Hi David, I will pay the refund on Friday."
    assert {"money", "commitment"} <= signal(body, frozenset({"david"}) | extra)
