"""LW-10 / AS-01: a malformed final file reply must not lose an otherwise useful run."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from tilo_harness.executor import UnitContext
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.media import MediaPart
from tilo_sandbox_web.fetch_fixtures import PAPERS

UNIT = {"id": "U4", "title": "Give the result", "unit_type": "deliver", "role": "writer"}
QUIZ = {"goal": "Quiz me", "deliverables": [{"title": "Quiz", "format": "app"}]}
SPEC = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/appspec/valid/true_false_one_question.json").read_text()
)
SPEC["questions"][0]["source"]["page"] = 1
REPORT = {"goal": "Write a report", "deliverables": [{"title": "Report", "format": "pdf"}]}
REPORT_SPEC = {
    "title": "Report",
    "date": "2026-10-16",
    "sections": [{"heading": "Summary", "blocks": [{"type": "paragraph", "text": "A useful finding."}]}],
}


@pytest.fixture(autouse=True)
def known_fixture_pdf_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    # This known-good generated fixture has one page. The Windows child-process timeout is tested in media.py.
    monkeypatch.setattr("tilo_providers.media._measure", lambda _data: ("ok", 1))


class Script(FakeModelProvider):
    def __init__(self, *replies: str) -> None:
        super().__init__("script")
        self.replies = list(replies)
        self.requests: list[GenerateRequest] = []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return GenerateResponse(text=self.replies.pop(0), profile_id="script")


def run(*replies: str, source: bool = False, cap: float = 20.0):
    model = Script(*replies)
    pdf = MediaPart(mime_type="application/pdf", data=PAPERS["paper-1.pdf"]) if source else None
    runner = ToolUnitRunner(
        {"writer": model},
        quiz_sources=(lambda _ref: pdf) if source else None,
        quiz_available=source,
        meter=lambda _role, _request, _response: 1.0,
        credit_cap=cap,
    )
    result = asyncio.run(runner.run_unit(UNIT, UnitContext("A_w0", (), brief=QUIZ)))
    return result, model


def test_LW_10_app_without_recorded_native_source_delivers_markdown() -> None:
    result, model = run("# Useful notes")
    assert result.outcome.success
    assert result.outcome.outputs[0].media_type == "text/markdown"
    assert result.outcome.outputs[0].content == b"# Useful notes"
    assert "AppSpec" not in model.requests[0].prompt


def test_AS_01_website_request_never_enters_quiz_path_without_a_source() -> None:
    model = Script("# Forty live timezone clocks\n\nShow a responsive grid with local times.")
    runner = ToolUnitRunner({"writer": model})
    brief = {**QUIZ, "goal": "a cool looking website showing over 40 different timezones live"}
    result = asyncio.run(runner.run_unit(UNIT, UnitContext("A_w0", (), brief=brief)))
    assert result.outcome.success
    assert result.outcome.outputs[0].media_type == "text/markdown"
    assert b"Forty live timezone clocks" in result.outcome.outputs[0].content
    assert "AppSpec" not in model.requests[0].prompt


def test_AS_01_recorded_pdf_keeps_valid_quiz_output() -> None:
    result, model = run(json.dumps(SPEC), source=True)
    assert result.outcome.success
    assert result.outcome.outputs[0].media_type == "application/json"
    assert "AppSpec" in model.requests[0].prompt


def test_LW_10_fenced_quiz_reply_gets_one_bounded_json_repair() -> None:
    result, model = run("```json\n" + json.dumps(SPEC) + "\n```", json.dumps(SPEC), source=True)
    assert result.outcome.success
    assert result.outcome.outputs[0].media_type == "application/json"
    assert result.credits == 2.0
    assert len(model.requests) == 2
    assert model.requests[1].json_mode is True
    assert model.requests[1].tools is None
    assert 0 < model.requests[1].max_output_tokens <= 4096


def test_LW_10_unrepairable_quiz_reply_degrades_to_text() -> None:
    result, model = run("Here is the useful answer.", "Still prose.", source=True)
    assert result.outcome.success and len(model.requests) == 2
    assert result.outcome.outputs[0].media_type == "text/markdown"
    assert result.outcome.outputs[0].content == b"Here is the useful answer."
    assert "could not build the app file" in result.outcome.summary


def test_AS_01_unowned_source_still_fails_closed() -> None:
    model = Script(json.dumps(SPEC))
    runner = ToolUnitRunner({"writer": model}, quiz_sources=lambda _ref: None, quiz_available=True)
    result = asyncio.run(runner.run_unit(UNIT, UnitContext("A_w0", (), brief=QUIZ)))
    assert not result.outcome.success and result.outcome.outputs == ()
    assert len(model.requests) == 1


def test_LW_10_oversized_reply_still_fails_closed() -> None:
    result, model = run("x" * 500_001, source=True)
    assert not result.outcome.success and result.outcome.outputs == ()
    assert len(model.requests) == 1


def test_LW_10_repair_obeys_remaining_unit_credit_cap() -> None:
    result, model = run("Useful text", source=True, cap=1.0)
    assert result.outcome.success and result.credits == 1.0
    assert result.outcome.outputs[0].media_type == "text/markdown"
    assert len(model.requests) == 1


def test_LW_10_pdf_spec_prose_gets_one_json_repair() -> None:
    model = Script("I found useful facts.", json.dumps(REPORT_SPEC))
    runner = ToolUnitRunner({"writer": model}, meter=lambda *_: 1.0)
    result = asyncio.run(runner.run_unit(UNIT, UnitContext("A_w0", (), brief=REPORT)))
    assert result.outcome.success and result.outcome.outputs[0].media_type == "application/pdf"
    assert len(model.requests) == 2 and model.requests[1].json_mode


def test_LW_10_pdf_spec_that_cannot_be_repaired_delivers_text() -> None:
    model = Script("I found useful facts.", "Still prose.")
    runner = ToolUnitRunner({"writer": model}, meter=lambda *_: 1.0)
    result = asyncio.run(runner.run_unit(UNIT, UnitContext("A_w0", (), brief=REPORT)))
    assert result.outcome.success
    assert result.outcome.outputs[0].media_type == "text/markdown"
    assert result.outcome.outputs[0].content == b"I found useful facts."
    assert "could not build the pdf file" in result.outcome.summary
