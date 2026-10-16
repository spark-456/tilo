"""AS-01: an accidental app format must not send a source-free task to the quiz path."""

import asyncio

import pytest
from tilo_api.intake import safe_app_brief
from tilo_api.report_render import render_report
from tilo_harness.deliverable import DeliverableRefused
from tilo_providers.media import MediaPart
from tilo_sandbox_web.fetch_fixtures import PAPERS


@pytest.fixture(autouse=True)
def known_fixture_pdf_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tilo_providers.media._measure", lambda _data: ("ok", 1))


def brief() -> dict:
    return {"goal": "Help me prepare", "deliverables": [{"title": "Study aid", "format": "app"}]}


def test_AS_01_stray_app_is_normalised_to_markdown_even_with_an_upload() -> None:
    pdf = MediaPart(mime_type="application/pdf", data=PAPERS["paper-1.pdf"])
    assert safe_app_brief(brief(), "Summarize this paper", [pdf])["deliverables"][0]["format"] == "markdown"


def test_AS_01_website_request_is_normalised_to_markdown() -> None:
    request = "a cool looking website showing over 40 different timezones live"
    assert safe_app_brief(brief(), request, [])["deliverables"][0]["format"] == "markdown"


def test_AS_01_quiz_without_a_native_source_is_normalised_to_markdown() -> None:
    assert safe_app_brief(brief(), "Make me an interactive quiz", [])["deliverables"][0]["format"] == "markdown"


def test_AS_01_explicit_quiz_with_a_pdf_keeps_app_format() -> None:
    pdf = MediaPart(mime_type="application/pdf", data=PAPERS["paper-1.pdf"])
    assert safe_app_brief(brief(), "Make me an interactive quiz", [pdf])["deliverables"][0]["format"] == "app"


def test_LW_10_oversized_render_reply_remains_a_hard_refusal() -> None:
    with pytest.raises(DeliverableRefused) as error:
        asyncio.run(render_report("x" * 500_001))
    assert error.value.code == "too_large"
