"""FR-CHN-10 security review round 2 (PR #224): sentence-wide negation, text-direction controls, mixed-script
words, and questions checked against sources read once (PRD 11.4 Content, 16.3, FR-CHN-14)."""

from __future__ import annotations

import time

import pytest
from _chn10_lib import Msg, answer, drafting_module, make_rig

INSTRUCTION = "Tell David Friday 2pm works."
THREAD = ["Can Marcus come by this Friday afternoon, and what is your hourly rate?"]
CLEAN = "Hi David,\n\nFriday at 2pm works for us.\n\nBest regards,\nSarah"
REFUND = "Hi David,\n\nFriday at 2pm works. We will refund your deposit.\n\nSarah"
RLO, PDF = chr(0x202E), chr(0x202C)


def _kinds(body: str, instruction: str = INSTRUCTION, thread: list[str] = THREAD) -> set[str]:
    return {f.kind for f in drafting_module().find_invented(body, instruction=instruction, thread=thread)}


# 1. Any negator anywhere in the instruction sentence: the commitment is not granted

NEGATED = [
    "Tell David Friday 2pm works; a refund is not possible.",
    "Tell David Friday 2pm works. Refunds are not available.",
    "Tell David Friday 2pm works. Do not offer David a full cash refund.",
    "Tell David Friday 2pm works, but we're not going to be able to refund him.",
    "Tell David Friday 2pm works. Do not, under any circumstances, refund the deposit.",
    "Tell David Friday 2pm works. We won't refund the deposit.",
    "Tell David Friday 2pm works. Refunding the deposit is out of the question.",
    "Tell David Friday 2pm works. Refuse any refund.",
    "Tell David Friday 2pm works. Avoid promising a refund.",
    "Tell David Friday 2pm works. Never refund deposits.",
    "Tell David Friday 2pm works. A refund is impossible.",
    "Tell David Friday 2pm works. Deny the refund request.",
    "Tell David Friday 2pm works. Refunds, as you know, are unavailable.",
    "Tell David Friday 2pm works. We can’t refund it.",
    "Tell David Friday 2pm works. Without exception, refunds stay with the office.",
    "Tell David Friday 2pm works. Decline the refund he asked for.",
]


@pytest.mark.parametrize("instruction", NEGATED)
def test_FR_CHN_10_negated_instruction_sentence_never_grants(instruction: str) -> None:
    assert _kinds(REFUND, instruction=instruction) == {"commitment"}


def test_FR_CHN_10_negated_warranty_sentence_never_grants() -> None:
    instruction = "Tell Lucas Friday 2pm works. Harborview's warranty doesn't cover customer parts."
    assert "commitment" in _kinds("Our Harborview warranty also covers the parts you supply.", instruction)


def test_FR_CHN_10_plain_instruction_still_grants() -> None:
    assert _kinds(REFUND, instruction="Tell David Friday 2pm works and refund the deposit.") == set()


def test_FR_CHN_10_negated_instruction_end_to_end_is_needs_you() -> None:
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(REFUND)])
    result = rig.draft(thread, NEGATED[4])
    assert result.status == "needs_you" and result.draft is None
    assert rig.events.of_type("artifact.created") == []


@pytest.mark.parametrize(
    "sentence",
    [
        "No refund is not an option for us.",
        "No refund will be withheld.",
        "Declining a refund is not something we do.",
        "Not offering a refund is out of the question.",
        "Not a problem, we will refund you.",
    ],
)
def test_FR_CHN_10_draft_double_negation_is_not_an_allowance(sentence: str) -> None:
    instruction = "Tell David Friday 2pm works, no refund of the deposit."
    assert "commitment" in _kinds(sentence, instruction)
    assert _kinds("There is no refund of the deposit.", instruction) == set()


# 2. Text-direction controls are a finding, never silently dropped


@pytest.mark.parametrize("body", [f"We will {RLO}dnufer{PDF} your deposit.", f"The total is {RLO}005{PDF}."])
def test_FR_CHN_10_direction_controls_in_the_body_are_a_finding(body: str) -> None:
    assert "obfuscation" in _kinds(body)
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(CLEAN.replace("us.", "us. " + body))])
    assert rig.draft(thread, INSTRUCTION).status == "needs_you"


@pytest.mark.parametrize("control", [chr(0x202A), chr(0x2066), chr(0x2069), chr(0x200E), chr(0x200F), chr(0x061C)])
def test_FR_CHN_10_every_direction_control_is_a_finding(control: str) -> None:
    assert "obfuscation" in _kinds(f"Friday{control} works.")


def test_FR_CHN_10_question_with_direction_controls_is_never_returned() -> None:
    rig = make_rig()
    asked = [f"Should I send the {RLO}005{PDF} to David?", "Which Friday does David mean?"]
    thread, _ = rig.thread(answers=[answer("", questions=asked)])
    result = rig.draft(thread, INSTRUCTION)
    assert result.status == "needs_you" and result.questions == ("Which Friday does David mean?",)
    assert "obfuscation" in {f.kind for f in result.findings}


# 3. Mixed-script words, Latin small capitals and IPA letters; marks dropped after decomposition


@pytest.mark.parametrize(
    "word",
    [
        "ref" + chr(0x057D) + "nd",  # Armenian seh
        "g" + chr(0x057D) + "arantee",
        "pr" + chr(0x0585) + "mise",  # Armenian oh
        chr(0x0280) + "efund",  # Latin small capital R
        "w" + chr(0x1D00) + "ive",  # Latin small capital A
        "w" + chr(0x0251) + "ive",  # IPA alpha
        "fr" + chr(0x0435) + "e",  # Cyrillic ie inside a Latin word
    ],
)
def test_FR_CHN_10_mixed_script_word_is_a_finding(word: str) -> None:
    assert "obfuscation" in _kinds(f"We will {word} it.")
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(CLEAN.replace("us.", f"us. We will {word} it."))])
    assert rig.draft(thread, INSTRUCTION).status == "needs_you"


def test_FR_CHN_10_combining_marks_are_dropped_after_decomposition() -> None:
    assert "commitment" in _kinds("We will ref" + chr(0x1EE5) + "nd it.")  # u with dot below, precomposed
    assert "commitment" in _kinds("We will refu" + chr(0x0323) + "nd it.")


def test_FR_CHN_10_ordinary_accented_and_single_script_words_pass() -> None:
    body = "José, Zoë and Øyvind can come Friday. Спасибо."
    assert _kinds(body) == set()


# 4. Questions are capped, and checked against sources read once


def test_FR_CHN_10_questions_are_capped_in_number_and_length() -> None:
    rig = make_rig()
    asked = [f"Is Friday option {w} fine?" for w in "abcdefg"] + ["Is Friday fine? " + "x" * 300]
    thread, _ = rig.thread(answers=[answer("", questions=["y" * 301, *asked])])
    result = rig.draft(thread, INSTRUCTION)
    assert result.questions == tuple(asked[:5])


def test_FR_CHN_10_many_questions_on_a_digit_heavy_thread_are_cheap() -> None:
    digits = " ".join(str(n) for n in range(20_000))[:100_000]
    mod = drafting_module()
    start = time.process_time()
    checker = mod.Checker(instruction=INSTRUCTION, thread=[digits[i : i + 8_000] for i in range(0, 100_000, 8_000)])
    for n in range(100):
        checker.find(chr(97 + n % 26))
    assert time.process_time() - start < 2.0

    rig = make_rig()
    earlier = [Msg(f"m{n}", f"x{n}@y.example", "Rates", digits[n * 8_000 : (n + 1) * 8_000]) for n in range(12)]
    thread, _ = rig.thread(earlier=earlier, answers=[answer("", questions=[chr(97 + n % 26) for n in range(100)])])
    start = time.process_time()
    result = rig.draft(thread, INSTRUCTION)
    assert time.process_time() - start < 2.0
    assert result.status == "needs_you" and len(result.questions) == 5
