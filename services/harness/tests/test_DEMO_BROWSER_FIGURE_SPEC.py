"""DEMO-BROWSER: the writer places the run's recorded pictures by id; code supplies them. A reply's own `figures` key is
dropped (the model never supplies image bytes), a figure block naming a picture the run did not record, or one already
placed, is left out, and the redactor reads the spec's words without the pictures' bytes.
"""

from __future__ import annotations

import base64
import io
import json

from PIL import Image
from tilo_harness.deliverable import parse_spec, render_output, spec_words


def _png() -> str:
    out = io.BytesIO()
    Image.new("RGB", (300, 200), "#3a7").save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")


FIGURES = {
    "F1": {"id": "F1", "image_base64": _png(), "source": "https://en.wikipedia.org/wiki/A"},
    "F2": {"id": "F2", "image_base64": _png(), "source": "https://en.wikipedia.org/wiki/B"},
}


def _reply(*blocks, figures=None):
    spec = {"title": "Report", "date": "2026-10-21", "sections": [{"heading": "Pages", "blocks": list(blocks)}]}
    if figures is not None:
        spec["figures"] = figures
    return json.dumps(spec)


def _figure(ident, caption="A page"):
    return {"type": "figure", "figure_id": ident, "caption": caption}


def test_DEMO_BROWSER_the_writer_places_the_runs_pictures_by_id():
    spec = parse_spec(_reply(_figure("F2"), _figure("F1")), figures=FIGURES)
    assert [f.id for f in spec.figures] == ["F2", "F1"]
    assert [b.figure_id for b in spec.sections[0].blocks] == ["F2", "F1"]


def test_DEMO_BROWSER_a_picture_the_run_did_not_record_or_one_placed_twice_is_left_out():
    spec = parse_spec(_reply(_figure("F9"), _figure("F1"), _figure("F1")), figures=FIGURES)
    assert [b.figure_id for b in spec.sections[0].blocks] == ["F1"] and [f.id for f in spec.figures] == ["F1"]
    without = parse_spec(_reply({"type": "paragraph", "text": "Hi"}, _figure("F1")))
    assert [b.type for b in without.sections[0].blocks] == ["paragraph"] and without.figures == []


def test_DEMO_BROWSER_the_model_never_supplies_picture_bytes():
    forged = [{"id": "F1", "image_base64": _png(), "source": "https://elsewhere.example/x"}]
    spec = parse_spec(_reply(_figure("F1"), figures=forged), figures=FIGURES)
    assert spec.figures[0].source == "https://en.wikipedia.org/wiki/A", "code's picture, not the reply's"
    spec = parse_spec(_reply(_figure("F1"), figures=forged))
    assert spec.figures == []


def test_DEMO_BROWSER_the_redactor_reads_the_words_not_the_bytes():
    spec = parse_spec(_reply(_figure("F1", "Japan's list")), figures=FIGURES)
    words = spec_words(spec)
    assert "Japan's list" in words and "https://en.wikipedia.org/wiki/A" in words
    assert FIGURES["F1"]["image_base64"][:40] not in words


def test_DEMO_BROWSER_the_in_process_pdf_carries_the_picture():
    from pypdf import PdfReader

    pdf = render_output(_reply(_figure("F1", "Japan's list")), figures=FIGURES)
    reader = PdfReader(io.BytesIO(pdf.content))
    assert sum(len(page.images) for page in reader.pages) == 1
    assert "image_base64" not in pdf.spec_text
