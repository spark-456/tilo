"""FR-INT-04 / FR-INT-06, INTAKE-QUALITY-1 slice 3: the deliverables question offers what Tilo can produce TODAY, from
`config/deliverable_kinds.yaml` (kinds that need work that has not shipped are `available: false` and never listed),
as numbered choices after the Director's guess, and several may be picked ("Study plan; Notes", "study plan and notes").
A chosen kind is a deliverable titled with the kind's label in the kind's format; an answer that names nothing offered
keeps the old reading (formats, free text, re-ask). No model call, no network."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from _planning_contracts_lib import load_brief_fixture, make_no_memory, sample_event_base
from tilo_contracts import Brief
from tilo_planning import questions as questions_module
from tilo_planning.brief import BriefValidationError, complete_brief, validate_brief
from tilo_planning.deliverable_kinds import (
    DEFAULT_KINDS_CONFIG,
    FORMATS,
    MAX_CHOICES,
    DeliverableKind,
    DeliverableKindsError,
    UnavailableKind,
    load_deliverable_kinds,
    load_kinds,
)
from tilo_planning.questions import KINDS_QUESTION, apply_answer, generate_questions, record_assumption

TODAY = date(2026, 10, 9)
KINDS = (
    DeliverableKind("study_plan", "Study plan", "markdown"),
    DeliverableKind("notes", "Notes", "markdown"),
    DeliverableKind("question_bank", "Question bank", "xlsx"),
)


def _brief() -> dict:
    brief = load_brief_fixture("valid_pdf_report")
    brief["deliverables"] = [{"title": "Exam preparation", "format": "pdf"}]
    return complete_brief(brief)


def _question(kinds=KINDS):
    brief = _brief()
    result = generate_questions(
        brief, ["deliverables"], memory=make_no_memory(), base=sample_event_base(), seq=2, kinds=kinds
    )
    return brief, result.questions[0]


def _titles(brief: dict) -> list[tuple[str, str]]:
    return [(d["title"], d["format"]) for d in brief["deliverables"]]


# --- the config -----------------------------------------------------------------------------------------------------


def test_FR_INT_04_the_shipped_config_loads_and_offers_only_available_kinds() -> None:
    kinds = load_deliverable_kinds()
    raw = yaml.safe_load(DEFAULT_KINDS_CONFIG.read_text(encoding="utf-8"))["kinds"]

    assert [k.id for k in kinds] == [e["id"] for e in raw if e["available"]]
    assert 1 <= len(kinds) <= MAX_CHOICES
    assert all(not e["available"] and e.get("needs") for e in raw if e["id"] not in {k.id for k in kinds})
    assert {e["needs"] for e in raw if not e["available"]} >= {"LW-12", "LW-14"}  # not offered until they ship


def test_FR_INT_04_the_kind_formats_are_the_contracts_deliverable_formats() -> None:
    from tilo_planning import questions

    enum = Brief.model_json_schema()["$defs"]["DeliverableFormat"]["enum"]

    assert tuple(enum) == FORMATS == questions._FORMATS


def _write(tmp_path: Path, kinds: object) -> Path:
    path = tmp_path / "kinds.yaml"
    path.write_text(yaml.safe_dump(kinds), encoding="utf-8")
    return path


def _entry(**changes: object) -> dict:
    return {"id": "notes", "label": "Notes", "format": "markdown", "available": True, **changes}


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"kinds": "notes"},
        {"kinds": [], "extra": 1},
        {"kinds": [_entry(id="Notes")]},
        {"kinds": [_entry(label="")]},
        {"kinds": [_entry(label="A, B")]},
        {"kinds": [_entry(label="A; B")]},
        {"kinds": [_entry(label="A <b>")]},
        {"kinds": [_entry(label="x" * 61)]},
        {"kinds": [_entry(label=" Notes")]},
        {"kinds": [_entry(format="docs")]},
        {"kinds": [_entry(available="yes")]},
        {"kinds": [_entry(available=False)]},  # unavailable without `needs`
        {"kinds": [_entry(needs="x" * 50)]},
        {"kinds": [{"id": "notes", "label": "Notes", "format": "markdown"}]},
        {"kinds": [_entry(), _entry(label="Other")]},  # duplicate id
        {"kinds": [_entry(), _entry(id="other", label="NOTES")]},  # duplicate label, any case
        {"kinds": [_entry(id=f"k{n}", label=f"Kind {n}") for n in range(MAX_CHOICES + 1)]},
    ],
)
def test_FR_INT_04_a_bad_kinds_file_fails_loudly(tmp_path, bad) -> None:
    with pytest.raises(DeliverableKindsError):
        load_deliverable_kinds(_write(tmp_path, bad))


def test_FR_INT_04_a_missing_or_unparsable_file_fails_loudly(tmp_path) -> None:
    with pytest.raises(DeliverableKindsError):
        load_deliverable_kinds(tmp_path / "missing.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("kinds: [\n", encoding="utf-8")
    with pytest.raises(DeliverableKindsError):
        load_deliverable_kinds(broken)


def test_FR_INT_04_an_unavailable_kind_is_never_offered_until_the_flag_is_true(tmp_path) -> None:
    later = _entry(id="quiz", label="Mock-test quiz", available=False, needs="LW-12")
    assert [k.id for k in load_deliverable_kinds(_write(tmp_path, {"kinds": [_entry(), later]}))] == ["notes"]

    shipped = {**later, "available": True}
    assert [k.id for k in load_deliverable_kinds(_write(tmp_path, {"kinds": [_entry(), shipped]}))] == ["notes", "quiz"]


# --- the question -------------------------------------------------------------------------------------------------


def test_FR_INT_04_the_deliverables_question_offers_the_kinds_after_the_directors_guess() -> None:
    _, question = _question()

    assert question.text == KINDS_QUESTION
    assert question.suggested_answers == ("Exam preparation (pdf)", "Study plan", "Notes", "Question bank")
    assert question.field == "deliverables" and question.label is None


def test_FR_INT_04_the_cap_of_three_answers_is_lifted_only_for_this_question() -> None:
    many = tuple(DeliverableKind(f"k{n}", f"Kind {n}", "markdown") for n in range(MAX_CHOICES))
    _, question = _question(many)
    assert len(question.suggested_answers) == 1 + MAX_CHOICES

    brief = _brief()
    audience = generate_questions(
        brief, ["audience"], memory=make_no_memory(), base=sample_event_base(), seq=2, kinds=many
    ).questions[0]
    assert len(audience.suggested_answers) <= 3


def test_FR_INT_04_with_no_available_kind_the_old_format_question_stays() -> None:
    _, question = _question(())

    assert question.text == "What should Tilo deliver, and in which format?"
    assert question.suggested_answers[1:] == ("A PDF report", "A slide deck")  # the old cap of 3 answers


def test_FR_INT_04_the_default_question_reads_the_shipped_config() -> None:
    brief = _brief()
    question = generate_questions(
        brief, ["deliverables"], memory=make_no_memory(), base=sample_event_base(), seq=2
    ).questions[0]

    assert list(question.suggested_answers[1:]) == [k.label for k in load_deliverable_kinds()]


# --- answers ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Study plan", [("Study plan", "markdown")]),
        ("Study plan; Notes", [("Study plan", "markdown"), ("Notes", "markdown")]),
        ("study plan and notes", [("Study plan", "markdown"), ("Notes", "markdown")]),
        ("NOTES, question bank", [("Notes", "markdown"), ("Question bank", "xlsx")]),
        (
            "Question bank + Study plan &Notes",
            [("Question bank", "xlsx"), ("Study plan", "markdown"), ("Notes", "markdown")],
        ),
        ("Notes; Notes; notes.", [("Notes", "markdown")]),
    ],
)
def test_FR_INT_04_several_kinds_can_be_picked_in_one_answer(answer, expected) -> None:
    brief, question = _question()

    result = apply_answer(brief, question, answer, today=TODAY, kinds=KINDS)

    assert _titles(result) == expected and validate_brief(result) == result


def test_FR_INT_04_the_guess_among_the_choices_keeps_the_current_deliverables_and_adds_the_kinds() -> None:
    brief, question = _question()
    guess = question.suggested_answers[0]

    result = apply_answer(brief, question, f"{guess}; Notes", today=TODAY, kinds=KINDS)  # the terminal's "1 and 3"

    assert _titles(result) == [("Exam preparation", "pdf"), ("Notes", "markdown")]
    again = apply_answer(result, question, f"{guess}; Notes", today=TODAY, kinds=KINDS)
    assert _titles(again) == _titles(result), "a kind already there is not added twice"


def test_FR_INT_04_skipping_the_choices_question_keeps_the_guess_and_records_the_assumption() -> None:
    brief, question = _question()

    skipped = record_assumption(brief, question, kinds=KINDS)

    assert _titles(skipped) == _titles(brief)
    assert skipped["assumptions"][-1] == {"question": KINDS_QUESTION, "assumed": "Deliverables: Exam preparation (pdf)"}


def test_FR_INT_04_a_word_that_is_not_an_offered_kind_keeps_the_re_ask() -> None:
    brief, question = _question()

    for unknown in ("Flashcards", "Quiz", "1,3", "7"):  # one word, or numbers: nothing offered, no format
        with pytest.raises(BriefValidationError):
            apply_answer(brief, question, unknown, today=TODAY, kinds=KINDS)
    # a longer unknown answer is the person's own words (free text, BQ-FREETEXT-1), not a refusal
    wish = apply_answer(brief, question, "Study plan; Flashcards", today=TODAY, kinds=KINDS)
    assert any(c.startswith("Deliverable wishes: Study plan; Flashcards") for c in wish["constraints"])


def test_FR_INT_04_free_text_and_formats_still_work_beside_the_choices() -> None:
    brief, question = _question()

    wish = apply_answer(brief, question, "Study plan with weekly goals for me", today=TODAY, kinds=KINDS)
    assert any(c.startswith("Deliverable wishes: Study plan with weekly goals") for c in wish["constraints"])
    assert (
        apply_answer(brief, question, "A slide deck", today=TODAY, kinds=KINDS)["deliverables"][0]["format"] == "pptx"
    )
    assert apply_answer(brief, question, "pdf; pptx", today=TODAY, kinds=KINDS)["deliverables"][0]["format"] == "pdf"


def test_FR_INT_04_a_label_that_holds_the_word_and_is_still_one_kind() -> None:
    kinds = (DeliverableKind("qa", "Question and answer bank", "markdown"), DeliverableKind("n", "Notes", "markdown"))
    brief, question = _question(kinds)

    result = apply_answer(brief, question, "Question and answer bank and Notes", today=TODAY, kinds=kinds)

    assert _titles(result) == [("Question and answer bank", "markdown"), ("Notes", "markdown")]


def test_FR_INT_04_matching_kinds_is_linear_on_a_long_answer() -> None:
    import time

    brief, question = _question()
    began = time.perf_counter()
    for answer in ("Notes; " * 40_000, "x" * 200_000, "Study plan " * 20_000):
        try:
            apply_answer(brief, question, answer, today=TODAY, kinds=KINDS)
        except BriefValidationError:
            pass

    assert time.perf_counter() - began < 2.0
    assert questions_module.ANSWER_MAX_CHARS == 300


# --- review fixes: kinds that are not available yet are refused, never read as free text -----------------------------

WITHHELD = (
    UnavailableKind("mock_test_quiz", "Mock-test quiz", "markdown", "LW-12"),
    UnavailableKind("past_paper_links", "Past-paper links", "markdown", "LW-14"),
)


def _refused(answer: str, unavailable=WITHHELD, kinds=KINDS) -> str:
    brief, question = _question(kinds)
    with pytest.raises(BriefValidationError) as caught:
        apply_answer(brief, question, answer, today=TODAY, kinds=kinds, unavailable=unavailable)
    return str(caught.value)


@pytest.mark.parametrize(
    ("answer", "label", "needs"),
    [
        ("Mock-test quiz", "Mock-test quiz", "LW-12"),
        ("mock-test QUIZ", "Mock-test quiz", "LW-12"),
        ("Past-paper links.", "Past-paper links", "LW-14"),
        ("Study plan; Mock-test quiz", "Mock-test quiz", "LW-12"),
        ("Study plan and Past-paper links", "Past-paper links", "LW-14"),
        ("Notes + mock-test quiz + Question bank", "Mock-test quiz", "LW-12"),
        ("I want a Mock-test quiz for the exam", "Mock-test quiz", "LW-12"),
    ],
)
def test_FR_INT_04_a_kind_that_is_not_available_yet_is_refused_alone_or_in_a_mix(answer, label, needs) -> None:
    message = _refused(answer)

    assert f"{label} is not available yet" in message and needs in message


def test_FR_INT_04_every_unavailable_kind_named_is_listed_in_the_refusal() -> None:
    message = _refused("Mock-test quiz and Past-paper links")

    assert "Mock-test quiz" in message and "Past-paper links" in message


def test_FR_INT_04_only_whole_words_name_an_unavailable_kind_and_the_fallback_ignores_them() -> None:
    brief, question = _question()
    assert apply_answer(brief, question, "mock-test quizzes", today=TODAY, kinds=KINDS, unavailable=WITHHELD)
    # with no kind offered the question is the old format question: nothing is withheld from it
    bare, plain = _question(())
    free = apply_answer(bare, plain, "Mock-test quiz", today=TODAY, kinds=(), unavailable=WITHHELD)
    assert free["deliverables"][0]["title"] == "Mock-test quiz"


def test_FR_INT_04_the_config_exposes_the_unavailable_kinds_validated_like_the_others(tmp_path) -> None:
    config = load_kinds()
    assert [(u.id, u.needs) for u in config.unavailable] == [("mock_test_quiz", "LW-12"), ("past_paper_links", "LW-14")]
    assert [k.id for k in config.offered] == [k.id for k in load_deliverable_kinds()]
    assert config.unavailable[0].label == "Mock-test quiz" and config.unavailable[0].format == "markdown"


def test_FR_INT_04_the_default_answer_path_refuses_an_unavailable_shipped_kind() -> None:
    brief = _brief()
    question = generate_questions(
        brief, ["deliverables"], memory=make_no_memory(), base=sample_event_base(), seq=2
    ).questions[0]

    for answer in ("Mock-test quiz", "Study plan; Past-paper links"):
        with pytest.raises(BriefValidationError, match="not available yet"):
            apply_answer(brief, question, answer, today=TODAY)


def test_FR_INT_04_the_parsed_config_is_cached_until_the_file_changes(tmp_path) -> None:
    path = _write(tmp_path, {"kinds": [_entry()]})
    first = load_kinds(path)
    assert load_kinds(path) is first

    path.write_text(yaml.safe_dump({"kinds": [_entry(), _entry(id="plan", label="Study plan")]}), encoding="utf-8")

    assert [k.id for k in load_kinds(path).offered] == ["notes", "plan"]
    path.write_text("kinds: [\n", encoding="utf-8")
    with pytest.raises(DeliverableKindsError):
        load_kinds(path)  # a bad file is never served from the cache


def test_FR_INT_04_the_guess_is_kept_only_as_a_whole_segment_of_the_answer() -> None:
    brief, question = _question()
    guess = question.suggested_answers[0]

    for answer in (f"{guess}; Notes", f"Notes; {guess}", f"Notes and {guess}", f"{guess} and Notes"):
        kept = apply_answer(brief, question, answer, today=TODAY, kinds=KINDS)
        assert ("Exam preparation", "pdf") in _titles(kept) and ("Notes", "markdown") in _titles(kept)
    for glued in (f"{guess} Notes", f"x{guess}; Notes", f"{guess}x; Notes"):
        with pytest.raises(BriefValidationError):
            apply_answer(brief, question, glued, today=TODAY, kinds=KINDS)
