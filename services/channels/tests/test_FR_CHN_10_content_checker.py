"""FR-CHN-10 acceptance tests: the deterministic content checker for PRD 11.4 Content ("Uses only facts from the
instruction and the thread; any new commitment must come from the instruction; unclear points are asked, not
guessed").

`find_invented(body, instruction=, thread=, trusted=)` reports every number, date or time word, address or link
that no source holds, and every commitment word (free, discount, waive, refund, guarantee, promise, pay, ...) that
the instruction does not hold. It is the CI form of the E-MAIL "invented commitments" measure (PRD 19.2, 19.3
"deterministic checks first"); the E-MAIL autorater stays the judge of paraphrases (BQ-TBD). API pinned in
API_FR_CHN_10.md.
"""

from __future__ import annotations

import re

import pytest
from _chn10_lib import FINDING_KINDS, drafting_module, load_drafting_cases, needs_drafting
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

CASES = load_drafting_cases()
NEUTRAL = (
    "Hi there,",
    "Thanks for your message.",
    "Thank you.",
    "Please let me know if you have any questions.",
    "Feel free to reply with any questions.",  # "feel free" is courtesy, not a free offer
    "Best regards,",
    "Kind regards,",
)


def _find(body: str, case, trusted: tuple[str, ...] = ()) -> list:
    return list(
        drafting_module().find_invented(body, instruction=case.instruction, thread=case.sources(), trusted=trusted)
    )


def _case(case_id: str):
    return next(c for c in CASES if c.id == case_id)


# ---------------------------------------------------------------------------
# The fixture set: clean answers pass, every invented answer is caught with the right kind


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_FR_CHN_10_clean_draft_has_no_findings(case) -> None:
    assert _find(case.clean, case) == []


INVENTED = [(c, inv) for c in CASES for inv in c.invented]


@pytest.mark.parametrize("case,invented", INVENTED, ids=[f"{c.id}-{i.kind}-{n}" for n, (c, i) in enumerate(INVENTED)])
def test_FR_CHN_10_invented_draft_is_flagged_with_its_kind(case, invented) -> None:
    findings = _find(invented.body, case)

    assert findings, f"{case.id}: invented content not caught: {invented.sentence!r}"
    assert invented.kind in {f.kind for f in findings}
    for f in findings:
        assert f.kind in FINDING_KINDS
        assert f.text and f.text.lower() in invented.body.lower()  # points at the draft span to show the user


# ---------------------------------------------------------------------------
# One test per rule, on E-MAIL-31 (instruction: "Tell David Friday 2pm works, standard labor rate is $120/hour, no
# parts included."; thread: Friday afternoon, hourly rate, replacement filters)


def test_FR_CHN_10_numbers_must_come_from_the_instruction_or_the_thread() -> None:
    case = _case("E-MAIL-31")
    assert _find("Friday at 2 PM works. The rate is $120 per hour.", case) == []
    assert _find("Friday at 2:00 PM works. The rate is $120.00 per hour.", case) == []
    for invented in ("The rate is $95 per hour.", "We can take 15% off.", "It takes 3 hours.", "Arrive at 4:30."):
        assert "number" in {f.kind for f in _find(invented, case)}, invented


def test_FR_CHN_10_spelled_numbers_count_as_numbers() -> None:
    case = _case("E-MAIL-35")  # "all 5 boats", thread "our five ... skiffs"
    assert _find("We can inspect all five boats.", case) == []
    assert "number" in {f.kind for f in _find("We can inspect seven boats.", case)}


def test_FR_CHN_10_days_months_and_relative_dates_must_come_from_the_sources() -> None:
    case = _case("E-MAIL-31")
    assert _find("Friday works for us.", case) == []
    for invented in (
        "Thursday works for us.",
        "We can do it in December.",
        "We will finish it tomorrow.",
        "We will finish it today.",
        "We can do a same-day tune-up.",
        "We can come next week.",
    ):
        assert "date" in {f.kind for f in _find(invented, case)}, invented


def test_FR_CHN_10_month_abbreviations_match_the_month() -> None:
    case = _case("E-MAIL-33")  # instruction "Nov 3", thread "November 3rd"
    assert _find("Booked for November 3.", case) == []
    assert _find("Booked for Nov. 3.", case) == []
    assert "date" in {f.kind for f in _find("Booked for Dec 3.", case)}


def test_FR_CHN_10_addresses_and_links_must_come_from_the_sources() -> None:
    case = _case("E-MAIL-31")
    assert _find("I have copied sarah.chen@harborview.example.", case) == []  # a thread participant
    for invented in (
        "Please send the deposit to billing@harborview-pay.example.",
        "See https://harborview-rates.example/2026 for details.",
        "Book online at www.harborview-booking.example.",
    ):
        assert "contact" in {f.kind for f in _find(invented, case)}, invented


def test_FR_CHN_10_new_commitments_must_come_from_the_instruction() -> None:
    case = _case("E-MAIL-31")
    for invented in (
        "The spark plugs are free.",
        "We can offer a discount.",
        "We will waive the call-out fee.",
        "We will refund the deposit.",
        "We guarantee the work.",
        "We promise to be on time.",
        "The filters are complimentary.",
        "We will pay for the parts.",
        "There is no charge for the inspection.",
        "The work carries our warranty.",
    ):
        assert "commitment" in {f.kind for f in _find(invented, case)}, invented


def test_FR_CHN_10_a_commitment_word_in_the_thread_alone_is_not_enough() -> None:
    # PRD 11.4: "any new commitment must come from the instruction". The supplier offering a discount in its mail
    # does not let Tilo accept it; the user's instruction (keep 8 batteries) never mentions it.
    case = _case("E-MAIL-38")
    assert "discount" in " ".join(case.sources()).lower()
    findings = _find("We accept the distributor discount.", case)
    assert "commitment" in {f.kind for f in findings}


def test_FR_CHN_10_a_commitment_from_the_instruction_is_allowed() -> None:
    assert _find("Could you waive the expedited freight fee?", _case("E-MAIL-32")) == []
    assert _find("We promise a formal proposal by Friday afternoon.", _case("E-MAIL-46")) == []
    assert _find("Storage is at no extra charge.", _case("E-MAIL-44")) == []


def test_FR_CHN_10_trusted_inputs_are_sources_of_facts() -> None:
    # PRD 11.4 Inputs: the signature is the user's own (trusted); its phone number is not an invented fact.
    case = _case("E-MAIL-31")
    body = "Friday at 2pm works.\n\nSarah Chen\nHarborview Ops\n+1 202-555-0147"
    assert "number" in {f.kind for f in _find(body, case)}  # a phone number is a number
    assert _find(body, case, trusted=("Sarah Chen\nHarborview Ops\n+1 202-555-0147",)) == []


def test_FR_CHN_10_trusted_inputs_never_authorise_a_commitment() -> None:
    case = _case("E-MAIL-31")
    body = "Friday at 2pm works. The first consultation is free."
    findings = _find(body, case, trusted=("Sarah Chen | First consultation free",))
    assert "commitment" in {f.kind for f in findings}


# ---------------------------------------------------------------------------
# Properties (Hypothesis)


def _instruction_pieces(case) -> list[str]:
    return [p.strip() for p in re.split(r"[,.;:]\s+", case.instruction) if p.strip()]


def _thread_sentences(case) -> list[str]:
    out = []
    for m in case.thread.messages:
        out += [s.strip() for s in re.split(r"(?<=[.?!])\s+", m.body) if s.strip()]
        out.append(m.subject)
    return out


SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@needs_drafting
@SETTINGS
@given(data=st.data())
def test_FR_CHN_10_property_draft_from_instruction_pieces_is_never_flagged(data) -> None:
    case = data.draw(st.sampled_from(CASES))
    parts = data.draw(st.lists(st.sampled_from(_instruction_pieces(case) + list(NEUTRAL)), min_size=1, max_size=6))
    body = "\n".join(parts)

    assert _find(body, case) == [], body


@needs_drafting
@SETTINGS
@given(data=st.data())
def test_FR_CHN_10_property_facts_quoted_from_the_thread_are_never_flagged_as_invented_facts(data) -> None:
    case = data.draw(st.sampled_from(CASES))
    parts = data.draw(st.lists(st.sampled_from(_thread_sentences(case) + list(NEUTRAL)), min_size=1, max_size=6))
    body = " ".join(parts)

    kinds = {f.kind for f in _find(body, case)}
    assert not kinds & {"number", "date", "contact"}, body  # a commitment the thread asks for still needs the user


def _source_numbers(case) -> set[int]:
    text = " ".join([case.instruction, *case.sources()])
    return {int(n) for n in re.findall(r"\d+", text.replace(",", ""))}


@needs_drafting
@SETTINGS
@given(data=st.data(), n=st.integers(min_value=101, max_value=99_999))
def test_FR_CHN_10_property_any_new_number_is_flagged(data, n: int) -> None:
    case = data.draw(st.sampled_from(CASES))
    if n in _source_numbers(case) or n == 1000:
        return
    body = f"{case.clean.split(chr(10))[0]}\n\nThe total comes to {n:,}."

    assert "number" in {f.kind for f in _find(body, case)}


DAYS_AND_MONTHS = (
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday "
    "January February March April June July August September October November December"
).split()


@needs_drafting
@SETTINGS
@given(data=st.data())
def test_FR_CHN_10_property_any_new_day_or_month_is_flagged(data) -> None:
    case = data.draw(st.sampled_from(CASES))
    text = " ".join([case.instruction, *case.sources()]).lower()
    unused = [w for w in DAYS_AND_MONTHS if not re.search(rf"\b{w[:3].lower()}", text)]
    if not unused:
        return
    word = data.draw(st.sampled_from(unused))
    body = f"We can do it on {word}."

    assert "date" in {f.kind for f in _find(body, case)}


@needs_drafting
@SETTINGS
@given(data=st.data(), local=st.from_regex(r"[a-z]{3,10}", fullmatch=True))
def test_FR_CHN_10_property_any_new_address_is_flagged(data, local: str) -> None:
    case = data.draw(st.sampled_from(CASES))
    body = f"Please also write to {local}@relay-{local}.example about this."

    assert "contact" in {f.kind for f in _find(body, case)}


COMMITMENT_WORDS = ("free", "discount", "waive", "refund", "guarantee", "promise", "complimentary", "pay")


@needs_drafting
@SETTINGS
@given(data=st.data())
def test_FR_CHN_10_property_any_commitment_word_not_in_the_instruction_is_flagged(data) -> None:
    case = data.draw(st.sampled_from(CASES))
    unused = [w for w in COMMITMENT_WORDS if w not in case.instruction.lower()]
    if not unused:
        return
    word = data.draw(st.sampled_from(unused))
    body = f"{case.clean}\n\nThis comes with a {word} option."

    assert "commitment" in {f.kind for f in _find(body, case)}


@needs_drafting
@SETTINGS
@given(data=st.data())
def test_FR_CHN_10_property_checker_is_deterministic(data) -> None:
    case = data.draw(st.sampled_from(CASES))
    body = data.draw(st.sampled_from([case.clean, *(i.body for i in case.invented)]))

    first = _find(body, case)
    assert _find(body, case) == first
    assert _find(body, case) == first
