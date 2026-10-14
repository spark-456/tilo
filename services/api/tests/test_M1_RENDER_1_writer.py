"""Office requests must reach the render door and retain file provenance."""

import asyncio
import json

import pytest
from tilo_api import report_render
from tilo_harness.deliverable import DeliverableRefused, render_format, wants_pdf, wants_rendered
from tilo_harness.outputs import RenderedOffice

SPEC = json.dumps(
    {
        "title": "Deck",
        "date": "2026-10-14",
        "sections": [{"heading": "Summary", "blocks": [{"type": "paragraph", "text": "Checked sources."}]}],
    }
)
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.mark.parametrize("fmt", ["pdf", "pptx", "docx"])
def test_M1_RENDER_1_writer_selection_comes_from_deliverable(fmt):
    unit = {"role": "writer", "unit_type": "deliver"}
    brief = {"deliverables": [{"format": fmt}]}
    assert render_format(unit, brief) == fmt
    assert wants_rendered(unit, brief)
    assert wants_pdf(unit, brief) == (fmt == "pdf")
    assert render_format({"role": "researcher", "unit_type": "deliver"}, brief) is None
    assert render_format({"role": "writer", "unit_type": "research"}, brief) is None


def test_M1_RENDER_1_pptx_writer_uses_configured_authenticated_rpc(monkeypatch):
    seen = []

    class FakeRpc:
        def __init__(self, base):
            assert base == "https://render.example"

        def render(self, spec, fmt):
            seen.append((spec.title, fmt))
            return b"PK\x03\x04offline"

    monkeypatch.setenv("TILO_RENDER_URL", "https://render.example")
    monkeypatch.setattr(report_render, "RenderRpc", FakeRpc)
    output = asyncio.run(report_render.render_report(SPEC, fmt="pptx"))
    assert type(output) is RenderedOffice
    assert output.media_type == PPTX
    assert output.content == b"PK\x03\x04offline"
    assert json.loads(output.spec_text)["title"] == "Deck"
    assert seen == [("Deck", "pptx")]


def test_M1_RENDER_1_unconfigured_office_never_falls_back_to_pdf(monkeypatch):
    monkeypatch.delenv("TILO_RENDER_URL", raising=False)
    with pytest.raises(DeliverableRefused):
        asyncio.run(report_render.render_report(SPEC, fmt="pptx"))


@pytest.mark.parametrize(
    "mime,content", [("application/pdf", b"PK\x03\x04x"), (PPTX, b"%PDF-x"), (PPTX, b"PK\x03\x04")]
)
def test_M1_RENDER_1_office_requires_its_own_file_type_and_magic(mime, content):
    with pytest.raises(ValueError):
        RenderedOffice(media_type=mime, content=content, spec_text=SPEC)
