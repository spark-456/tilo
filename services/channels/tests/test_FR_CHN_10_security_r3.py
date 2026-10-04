"""FR-CHN-10 security review round 3 (PR #224): letters of other scripts fail closed, stroke letters read as their
base, and a negator anywhere in the instruction grants no commitment (PRD 11.4 Content)."""

from __future__ import annotations

import pytest
from _chn10_lib import answer, drafting_module, load_drafting_cases, make_rig

INSTRUCTION = "Tell David Friday 2pm works."
THREAD = ["Can Marcus come by this Friday afternoon, and what is your hourly rate?"]
CLEAN = "Hi David,\n\nFriday at 2pm works for us.\n\nBest regards,\nSarah"
REFUND = "Hi David,\n\nFriday at 2pm works. We will refund your deposit.\n\nSarah"


def _kinds(body: str, instruction: str = INSTRUCTION, thread: list[str] = THREAD) -> set[str]:
    return {f.kind for f in drafting_module().find_invented(body, instruction=instruction, thread=thread)}


def _drafted(body: str, instruction: str = INSTRUCTION) -> str:
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(body)])
    result = rig.draft(thread, instruction)
    assert (result.status == "ready") == bool(rig.events.of_type("artifact.created"))
    return result.status


# 1. Letters of other scripts are obfuscation; stroke letters read as their base letter


@pytest.mark.parametrize("word", ["ꓣꓰꓝꓴꓠꓓ", "ꓝꓣꓰꓰ", "ᖇᕮᕴᑌᑎᗪ", "ᏢᎪᎥᎠ"])  # Lisu, Canadian Syllabics, Cherokee
def test_FR_CHN_10_other_script_letters_are_obfuscation(word: str) -> None:
    assert "obfuscation" in _kinds(f"We will {word} your deposit.")
    assert _drafted(CLEAN.replace("us.", f"us. We will {word} your deposit.")) == "needs_you"


@pytest.mark.parametrize("sentence", ["We will refunđ your deposit.", "We prømise it.", "It is ƒree."])
def test_FR_CHN_10_stroke_letters_are_read_as_their_base(sentence: str) -> None:
    kinds = _kinds(sentence)
    assert kinds & {"commitment", "obfuscation"}, sentence
    assert _drafted(CLEAN.replace("us.", f"us. {sentence}")) == "needs_you"


def test_FR_CHN_10_stroke_letters_fold_for_the_commitment_match() -> None:
    assert _kinds("We will refunđ your deposit.") == {"commitment"}
    assert _kinds("We prømise it.") == {"commitment"}


def test_FR_CHN_10_names_and_single_script_words_stay_clean() -> None:
    assert _kinds("José, Zoë, Øyvind, Łukasz and Nguyễn can come Friday. Спасибо.") == set()


# 2. A negator anywhere in the instruction grants no commitment word

NEGATED = [
    "Tell David Friday 2pm works. He wants a refund; say no.",
    "David asked for a refund. Tell him Friday 2pm works but we can't.",
    "Tell David Friday 2pm works. Reject the refund.",
    "Tell David Friday 2pm works. Skip the refund.",
    "Tell David Friday 2pm works. Hold off on any refund.",
    "Tell David Friday 2pm works. Ignore his refund request.",
    "Tell David Friday 2pm works. Refund? Nope.",
    "Tell David Friday 2pm works. Turn the refund down.",
    "Tell David Friday 2pm works. Rule out a refund.",
    "Tell David Friday 2pm works. Forgo the refund.",
]


@pytest.mark.parametrize("instruction", NEGATED)
def test_FR_CHN_10_negator_anywhere_in_the_instruction_grants_nothing(instruction: str) -> None:
    assert _kinds(REFUND, instruction=instruction) == {"commitment"}


def test_FR_CHN_10_negator_anywhere_end_to_end_is_needs_you() -> None:
    assert _drafted(REFUND, NEGATED[0]) == "needs_you"
    assert _drafted(REFUND, "Tell David Friday 2pm works and refund the deposit.") == "ready"


def test_FR_CHN_10_every_clean_answer_still_has_no_findings() -> None:
    find = drafting_module().find_invented
    for case in load_drafting_cases():
        assert find(case.clean, instruction=case.instruction, thread=case.sources()) == [], case.id
