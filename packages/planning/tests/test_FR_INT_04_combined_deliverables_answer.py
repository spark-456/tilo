"""FR-INT-04 (PRD 7.1), live-run refusal of 8 Oct 2026: a person answered the deliverables question "1 and 2" and the
whole run stopped because the literal answer was set as the format of every deliverable ("Input should be 'pdf',
'pptx', ..."). A combined answer names several formats and keeps or adds the matching deliverables; a free-text answer
is mapped to a format or refused with a message the person can act on (they say it again); one answer still sets one
format. No model call, no network.
"""

from __future__ import annotations

from datetime import date

import pytest
from _planning_contracts_lib import load_brief_fixture, make_no_memory, sample_event_base
from tilo_planning.brief import BriefValidationError, complete_brief, validate_brief
from tilo_planning.questions import apply_answer, generate_questions

TODAY = date(2026, 10, 8)


def _brief(formats: tuple[str, ...] = ("pdf", "docx", "pptx")) -> dict:
    brief = load_brief_fixture("valid_pdf_report")
    brief["deliverables"] = [{"title": f"Item {n}", "format": f} for n, f in enumerate(formats, 1)]
    return complete_brief(brief)


def _question(brief: dict):
    return generate_questions(
        brief, ["deliverables"], memory=make_no_memory(), base=sample_event_base(), seq=2
    ).questions[0]


def _formats(brief: dict) -> list[str]:
    return [d["format"] for d in brief["deliverables"]]


def test_FR_INT_04_the_exact_live_case_options_one_and_two_joined_does_not_refuse():
    brief = _brief()
    question = _question(brief)
    one, two = question.suggested_answers[0], question.suggested_answers[1]  # the person typed "1 and 2"

    result = apply_answer(brief, question, f"{one}; {two}", today=TODAY)

    assert validate_brief(result) == result
    assert _formats(result) == ["pdf", "docx", "pptx"], "the current deliverables stay; a PDF report is already there"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("A PDF report and a slide deck", ["pdf", "pptx"]),
        ("pdf, pptx", ["pdf", "pptx"]),
        ("PDF + Word", ["pdf", "docx"]),
        ("excel & csv", ["xlsx", "csv"]),
        ("slides; docx; pdf", ["pptx", "docx", "pdf"]),
        ("A slide deck", ["pptx"]),
        ("markdown.", ["markdown"]),
    ],
)
def test_FR_INT_04_combined_and_typed_formats_are_mapped_to_the_enum(answer, expected):
    brief = _brief(("pdf",))
    result = apply_answer(brief, _question(brief), answer, today=TODAY)

    assert validate_brief(result) == result
    if len(expected) == 1:
        assert _formats(result) == expected, "one format still sets every deliverable"
    else:
        assert sorted(set(_formats(result))) == sorted(expected)
        assert len(result["deliverables"]) == len(expected)


def test_FR_INT_04_added_deliverables_are_titled_after_the_first_and_never_collide():
    brief = _brief(("pdf",))
    result = apply_answer(brief, _question(brief), "pdf and pptx", today=TODAY)

    assert [d["format"] for d in result["deliverables"]] == ["pdf", "pptx"]
    assert result["deliverables"][1]["title"] == "Item 1 (pptx)"


@pytest.mark.parametrize("answer", ["banana", "1 and 2", "pdf and banana", "and", "; ;", "standard"])
def test_FR_INT_04_an_answer_that_names_no_format_is_refused_so_the_person_can_say_it_again(answer):
    brief = _brief()

    with pytest.raises(BriefValidationError, match="Name the format"):
        apply_answer(brief, _question(brief), answer, today=TODAY)


def test_FR_INT_04_a_combined_answer_over_the_deliverables_cap_is_refused_not_stored():
    brief = _brief(("pdf",))
    every = "pdf, pptx, docx, xlsx, csv, markdown, google_slides, google_docs, google_sheets, email, in_app"

    with pytest.raises(BriefValidationError):
        apply_answer(brief, _question(brief), every, today=TODAY)


def test_FR_INT_04_the_word_and_inside_a_word_is_not_a_separator():
    brief = _brief(("pdf",))

    with pytest.raises(BriefValidationError):  # "standard" is not a format; it must not split into "st" and "ard"
        apply_answer(brief, _question(brief), "standard", today=TODAY)
    assert _formats(apply_answer(brief, _question(brief), "spreadsheet", today=TODAY)) == ["xlsx"]


def test_FR_INT_04_titles_with_and_or_commas_in_the_current_chip_do_not_break_the_split():
    brief = load_brief_fixture("valid_pdf_report")
    brief["deliverables"] = [
        {"title": "Pricing, risks and plan", "format": "pdf"},
        {"title": "Slides & notes", "format": "pptx"},
    ]
    brief = complete_brief(brief)
    question = _question(brief)

    result = apply_answer(brief, question, f"{question.suggested_answers[0]}; A document I can edit", today=TODAY)

    assert validate_brief(result) == result
    assert _formats(result) == ["pdf", "pptx", "docx"]
    assert result["deliverables"][0]["title"] == "Pricing, risks and plan"


@pytest.mark.parametrize(
    "answer",
    [" " * 100_000, "and,;" * 20_000, "pdf" + " " * 100_000 + "and pptx", "(" * 100_000],
    ids=["spaces", "and-commas", "spaced-and", "parens"],
)
def test_FR_INT_04_a_huge_answer_is_cut_to_the_routes_limit_and_never_scanned_whole(answer):
    import time

    brief = _brief(("pdf",))
    started = time.perf_counter()
    try:
        apply_answer(brief, _question(brief), answer, today=TODAY)
    except BriefValidationError:
        pass
    assert time.perf_counter() - started < 1.0
