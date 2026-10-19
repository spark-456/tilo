"""FR-MTG-08c acceptance tests: the residual hardening of `tilo_channels.meeting_followup` and `drafting_check` left by
the Opus review of FR-MTG-08b (BQ-MTG08C-1 to -7). Nothing here weakens `test_FR_MTG_08_*` or `test_FR_MTG_08b_*`.

(e) NFKD can expand a body past the checker's cap: that is a finding, never an exception, and one bad item never aborts
    the other nudges or costs a second model call on retry.
(a) A prefix with no commitment word cannot turn a verbatim confirmed entry into a commitment ("Approved: <entry>").
(b) Pins: the line-end anchor and the lead-in requirement of a verbatim repeat.
(c) Overlay and enclosing combining marks (strike-through) in model text are obfuscation; a body of marks only is no
    readable body.
(d) The NFKD work is bounded (a 40,000-character run of one mark was 52 s).
(f) The meeting title is its own source of facts: a link, address or number that confirmed text does not hold gives the
    generic subject.

Uses the doubles of `_mtg08_lib`. No network, no paid call, no real mail.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from _chn10_lib import fresh_key
from _chn_wire1_lib import assert_nothing_sent, real_check_is_live
from _mtg08_lib import PEOPLE, World, addresses, item, make_world, needs_followup
from tilo_channels.drafting_check import CHECK_CAP, Checker, clean, find_invented

MINUTES_CAP = 40_000
PRIYA, SAM = PEOPLE["u_priya"], PEOPLE["u_sam"]
REFUND = "Acme asked about a refund for the March order"
TOO_SLOW_S = 8.0  # the unbounded NFKD took 52 s; a linear one takes well under a second


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


def assert_not_sendable(world: World, card: Any) -> None:
    if card is not None:
        assert card.status != "ready" and "send" not in card.options, (card.status, card.options)
    assert_nothing_sent(world.line)


def patch_meeting_title(world: World, title: str) -> None:
    original = world.meetings.get

    def get(user_id: str, meeting_id: str) -> dict[str, Any] | None:
        doc = original(user_id, meeting_id)
        if doc is not None:
            doc["title"] = title
        return doc

    world.meetings.get = get  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# (e) An expanding body is a finding, not an exception


@needs_followup
def test_FR_MTG_08c_e_a_minutes_body_that_expands_past_the_cap_is_needs_you_not_an_exception() -> None:
    world = make_world()
    noise = chr(0xFDFA) * 2300  # NFKD x18: 41,400 characters read
    world.model.minutes_body = lambda: f"Hi all,\n\n{world.summary}\n\n{noise}\n\nBest,\nSarah"

    card = world.minutes_email("u_priya")  # must not raise

    assert card is not None and card.status == "needs_you" and "send" not in card.options
    assert card.findings, "the owner sees why"
    asked = len(world.model.minutes_prompts())
    assert asked <= 2, "one draft plus at most one regeneration"
    assert world.minutes_email("u_priya") is not None
    assert len(world.model.minutes_prompts()) == asked, "a retry reuses the stored answer: no new model call"
    assert_nothing_sent(world.line)


@needs_followup
def test_FR_MTG_08c_e_one_nudge_that_expands_past_the_cap_does_not_abort_the_other_nudges() -> None:
    world = make_world()
    bad, good = world.items[0], world.items[1]
    world.model.nudge_body = lambda it: "Hi,\n\n" + "ﷺ" * 2300 if it is bad else world.faithful_nudge_body(it)

    cards = world.nudges()  # must not raise

    ready = [c for c in cards if c.status == "ready"]
    assert [addresses(c) for c in ready] == [(SAM,)] and good.text in ready[0].body
    assert all(c.status != "ready" and "send" not in c.options for c in cards if addresses(c) == (PRIYA,))
    calls = len(world.model.nudge_prompts())
    world.nudges()
    assert len(world.model.nudge_prompts()) == calls, "a retry pays no second model call"
    assert_nothing_sent(world.line)


@needs_followup
def test_FR_MTG_08c_e_a_nudge_whose_model_call_fails_does_not_abort_the_other_nudges() -> None:
    world = make_world()
    bad = world.items[0]
    real = world.model.generate

    def generate(request: Any) -> Any:
        if bad.key in request.prompt:
            raise RuntimeError("provider down")
        return real(request)

    world.model.generate = generate  # type: ignore[method-assign]

    cards = world.nudges()

    assert [addresses(c) for c in cards if c.status == "ready"] == [(SAM,)]
    assert_nothing_sent(world.line)


def test_FR_MTG_08c_e_the_checker_reads_an_expanding_body_within_its_cap_and_never_raises_on_it() -> None:
    checker = Checker(instruction="", thread=[], cap=MINUTES_CAP)
    for body in ("ﷺ" * 2300, "ﷺ" * 2_222):
        found = checker.find(body)  # raw length is within the cap: a finding, not a ValueError
        assert any(f.kind == "obfuscation" for f in found), body[:1]
    with pytest.raises(ValueError, match="too long"):
        checker.find("a" * (MINUTES_CAP + 1))


def test_FR_MTG_08c_e_the_audit_of_a_body_whose_fold_doubles_it_past_the_cap_is_a_finding() -> None:
    from tilo_channels.meeting_followup import _audit  # the module's own gate; "ss" x2 of every sharp s

    checker = Checker(instruction="", thread=[], cap=MINUTES_CAP)
    found = _audit(checker, "ß" * MINUTES_CAP, ["entry"])  # reads as 80,000 characters: must not raise
    assert found and all(isinstance(f.text, str) for f in found)


# ---------------------------------------------------------------------------
# (a) A prefix with no commitment word cannot turn a verbatim entry into a commitment


PREFIXES = [
    "Approved: ",
    "We agreed to grant this request: ",
    "Yes, we accept - ",
    "- Approved: ",
    "Granted: ",
]


@needs_followup
@pytest.mark.parametrize("prefix", PREFIXES)
def test_FR_MTG_08c_a_prefix_cannot_turn_a_confirmed_entry_with_a_commitment_word_into_a_commitment(
    prefix: str,
) -> None:
    world = make_world(summary=REFUND)
    world.model.minutes_body = lambda: f"Hi all,\n\n{prefix}{world.summary}\n\nBest,\nSarah"

    card = world.minutes_email("u_priya")

    assert_not_sendable(world, card)
    assert card is not None and any(f.startswith("commitment") for f in card.findings), card.findings


@needs_followup
def test_FR_MTG_08c_a_heading_line_cannot_turn_the_entries_under_it_into_a_commitment() -> None:
    world = make_world(summary=REFUND)
    world.model.minutes_body = lambda: f"Hi all,\n\nApproved:\n\n- {world.summary}\n\nBest,\nSarah"
    card = world.minutes_email("u_priya")
    assert_not_sendable(world, card)
    assert card is not None and any(f.startswith("commitment") for f in card.findings)


@needs_followup
def test_FR_MTG_08c_a_nudge_prefix_cannot_turn_a_confirmed_item_into_a_commitment() -> None:
    items = [item(1, "Send the refund form to Acme", owner="u_priya")]
    world = make_world(items)
    world.model.nudge_body = lambda it: f"Hi,\n\nPlease go ahead and approve: {it.text}\n\nSarah"

    cards = world.nudges()

    assert cards and all(c.status != "ready" and "send" not in c.options for c in cards)
    assert any(f.startswith("commitment") for c in cards for f in c.findings)
    assert_nothing_sent(world.line)


@needs_followup
@pytest.mark.parametrize(
    "lead",
    ["", "- ", "* ", "Summary: ", "Decisions: ", "A reminder about this item: ", "Open action items:\n- "],
    ids=["bare", "dash", "star", "summary", "decisions", "reminder", "heading"],
)
def test_FR_MTG_08c_a_neutral_lead_in_keeps_a_verbatim_confirmed_entry_sendable(lead: str) -> None:
    world = make_world(summary=REFUND, decisions=[(f"Offer partners a discount as agreed {fresh_key()}", "verified")])
    world.model.minutes_body = lambda: (
        f"Hi all,\n\n{lead}{world.summary}\n\n{lead}{world.decisions[0][0]}\n\nBest,\nSarah"
    )
    card = world.minutes_email("u_priya")
    assert card is not None and card.status == "ready" and card.findings == (), card and card.findings

    items = [item(1, "Send the refund form to Acme", owner="u_priya")]
    nudge = make_world(items)
    nudge.model.nudge_body = lambda it: f"Hi,\n\n{lead}{it.text}\n\nSarah"
    (ncard,) = nudge.nudges()
    assert ncard.status == "ready" and ncard.findings == (), ncard.findings


# ---------------------------------------------------------------------------
# (b) Pins: the line-end anchor and the lead-in requirement


@needs_followup
@pytest.mark.parametrize(
    "template",
    ["{e} and we approve it", "So we grant what {e}", "We are happy that {e}, as requested", "{e} - approved"],
    ids=["tail_after_entry", "lead_word", "tail_comma", "tail_dash"],
)
def test_FR_MTG_08c_b_text_around_an_entry_on_its_line_makes_it_no_verbatim_repeat(template: str) -> None:
    world = make_world(summary=REFUND)
    world.model.minutes_body = lambda: "Hi all,\n\n" + template.format(e=world.summary) + "\n\nBest,\nSarah"

    card = world.minutes_email("u_priya")

    assert_not_sendable(world, card)
    assert card is not None and any(f.startswith("commitment") for f in card.findings), card.findings


# ---------------------------------------------------------------------------
# (c) Overlay and enclosing combining marks are obfuscation in model text


OVERLAYS = ["̴", "̵", "̶", "̷", "̸", "⃒", "⃝", "⃥", "⃰"]


@pytest.mark.parametrize("mark", OVERLAYS, ids=[f"u{ord(m):04x}" for m in OVERLAYS])
def test_FR_MTG_08c_c_an_overlay_mark_in_model_text_is_an_obfuscation_finding(mark: str) -> None:
    struck = mark.join("No") + mark + " refund for Acme"
    found = find_invented(struck, instruction="", thread=["No refund for Acme"])
    assert any(f.kind == "obfuscation" for f in found), found


def test_FR_MTG_08c_c_a_body_of_combining_marks_only_is_an_obfuscation_finding_not_an_empty_pass() -> None:
    for body in ("ཱི" * 50, "̶" * 5, "​" * 10, "ཱི"):
        found = find_invented(body, instruction="", thread=[])
        assert any(f.kind == "obfuscation" for f in found), repr(body)


def test_FR_MTG_08c_c_ordinary_accents_and_names_are_not_obfuscation() -> None:
    body = "Thanks José, see you at the café on the Müller project. Zoë and Łukasz will join."
    assert find_invented(body, instruction="", thread=[]) == []


@needs_followup
def test_FR_MTG_08c_c_a_struck_through_repeat_of_a_confirmed_entry_is_not_a_verbatim_repeat() -> None:
    world = make_world(summary="No refund for Acme")
    struck = chr(0x336).join(world.summary)  # a stroke through every letter
    world.model.minutes_body = lambda: f"Hi all,\n\n{struck}\n\nBest,\nSarah"
    card = world.minutes_email("u_priya")
    assert_not_sendable(world, card)
    assert card is not None and any(f.startswith("obfuscation") for f in card.findings), card.findings


@needs_followup
def test_FR_MTG_08c_c_a_body_made_only_of_combining_marks_is_never_a_ready_card() -> None:
    world = make_world()
    world.model.minutes_body = lambda: "ཱི" * 3000
    assert_not_sendable(world, world.minutes_email("u_priya"))
    nudge = make_world()
    nudge.model.nudge_body = lambda it: "ཱི" * 500
    assert all(c.status != "ready" for c in nudge.nudges())
    assert_nothing_sent(nudge.line)


# ---------------------------------------------------------------------------
# (d) The NFKD work is bounded


@pytest.mark.parametrize("run", ["ཱི", "ﾞ", "ཱི", "aཱི"], ids=["u0f73", "uff9e", "pair", "mixed"])
def test_FR_MTG_08c_d_a_maximal_run_of_marks_is_cleaned_and_checked_in_bounded_time(run: str) -> None:
    body = (run * MINUTES_CAP)[:MINUTES_CAP]
    checker = Checker(instruction="", thread=[], cap=MINUTES_CAP)
    start = time.perf_counter()
    found = checker.find(body)
    cleaned = clean(body)
    elapsed = time.perf_counter() - start
    assert elapsed < TOO_SLOW_S, f"{elapsed:.1f}s"
    assert len(cleaned) <= 100_000
    assert any(f.kind == "obfuscation" for f in found)


def test_FR_MTG_08c_d_a_maximal_expanding_text_is_cleaned_in_bounded_time_and_size() -> None:
    start = time.perf_counter()
    cleaned = clean("ﷺ" * MINUTES_CAP)
    found = Checker(instruction="", thread=[], cap=MINUTES_CAP).find("ﷺ" * MINUTES_CAP)
    assert time.perf_counter() - start < TOO_SLOW_S
    assert len(cleaned) <= 100_000
    assert any(f.kind == "obfuscation" for f in found)


def test_FR_MTG_08c_d_the_default_checker_cap_still_reads_a_body_of_that_size_in_bounded_time() -> None:
    start = time.perf_counter()
    found = find_invented("ཱི" * CHECK_CAP, instruction="", thread=[])
    assert time.perf_counter() - start < TOO_SLOW_S
    assert any(f.kind == "obfuscation" for f in found)


@needs_followup
def test_FR_MTG_08c_d_a_minutes_body_of_marks_is_refused_in_bounded_time_end_to_end() -> None:
    world = make_world()
    world.model.minutes_body = lambda: "Hi,\n\n" + "ཱི" * 6_000  # JSON-escaped it stays within the answer cap
    start = time.perf_counter()
    card = world.minutes_email("u_priya")
    assert time.perf_counter() - start < TOO_SLOW_S
    assert_not_sendable(world, card)


# ---------------------------------------------------------------------------
# (f) The meeting title is its own source of facts


@needs_followup
@pytest.mark.parametrize(
    "title",
    [
        "Sync https://evil.example/login now",
        "Sync mallory@attacker.example",
        "Sync at acme-login.example",
        "Invoice 48213 sync",
        "Launch 5,000 units",
    ],
    ids=["link", "address", "domain", "number", "amount"],
)
def test_FR_MTG_08c_f_a_title_with_a_link_address_or_number_confirmed_text_lacks_gets_the_generic_subject(
    title: str,
) -> None:
    world = make_world()
    patch_meeting_title(world, title)
    card = world.minutes_email("u_priya")
    assert card is not None and card.status == "ready" and card.subject == "Meeting minutes", card.subject


@needs_followup
def test_FR_MTG_08c_f_a_fact_in_the_title_that_confirmed_text_holds_stays_in_the_subject() -> None:
    world = make_world(summary="The budget of 4500 is settled")
    patch_meeting_title(world, "Budget 4500 review")
    card = world.minutes_email("u_priya")
    assert card is not None and card.subject == "Minutes: Budget 4500 review"

    plain = make_world()
    patch_meeting_title(plain, "Q3 launch plan sync")
    card = plain.minutes_email("u_priya")
    assert card is not None and card.subject == "Minutes: Q3 launch plan sync"
