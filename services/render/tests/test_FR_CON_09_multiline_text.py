"""FR-CON-09: multi-line paragraph and bullet input renders as real paragraphs, not vertical-tab line breaks."""

import io
from typing import Any

import pptx
from tilo_render.pptx import _chunk_text, render_pptx, sanitize_text
from tilo_render.spec import BulletsBlock, DeliverableSpec, ParagraphBlock, Section


def _body_paragraphs(blocks: list[Any]) -> list[list[str]]:
    """Render a one-section deck and return, per body slide, the paragraph texts of the body text box."""
    spec = DeliverableSpec(title="T", date="2026-10-02", sections=[Section(heading="H", blocks=blocks)])
    prs = pptx.Presentation(io.BytesIO(render_pptx(spec)))
    out: list[list[str]] = []
    for slide in list(prs.slides)[2:]:  # skip the title and section-divider slides
        boxes = [sh for sh in slide.shapes if sh.has_text_frame]
        out.append([p.text for p in boxes[-1].text_frame.paragraphs])  # last text box is the body
    return out


def test_FR_CON_09_multiline_paragraph_is_one_paragraph_per_line() -> None:
    (paras,) = _body_paragraphs([ParagraphBlock(text="l1\nl2\n\nl3")])
    assert paras == ["l1", "l2", "", "l3"]
    assert all("\x0b" not in p for p in paras)


def test_FR_CON_09_multiline_paragraph_handles_crlf_and_sanitises_per_line() -> None:
    (paras,) = _body_paragraphs([ParagraphBlock(text="a\x00\r\nb\x07\rc￾")])
    assert paras == ["a", "b", "c"]


def test_FR_CON_09_multiline_bullets_get_one_marker_per_line() -> None:
    (paras,) = _body_paragraphs([BulletsBlock(bullets=["x\ny", "z"])])
    assert paras == ["•  x", "•  y", "•  z"]


def test_FR_CON_09_multiline_bullets_blank_lines_are_not_empty_bullets() -> None:
    (paras,) = _body_paragraphs([BulletsBlock(bullets=["a\n\nb", "", "  \n c\x00"])])
    assert paras == ["•  a", "•  b", "•   c"]


def test_FR_CON_09_multiline_bullets_all_at_level_zero() -> None:
    spec = DeliverableSpec(
        title="T", date="2026-10-02", sections=[Section(heading="H", blocks=[BulletsBlock(bullets=["p\nq"])])]
    )
    prs = pptx.Presentation(io.BytesIO(render_pptx(spec)))
    body = [sh for sh in list(prs.slides)[2].shapes if sh.has_text_frame][-1]
    assert [p.level for p in body.text_frame.paragraphs] == [0, 0]


def test_FR_CON_09_text_survives_chunking_across_slides() -> None:
    text = "\n".join(f"line {i} " + "w " * 40 for i in range(60))
    chunks = _chunk_text(sanitize_text(text), max_chars=500)
    assert len(chunks) > 1
    assert "".join(chunks) == sanitize_text(text)

    per_slide = _body_paragraphs([ParagraphBlock(text=text)])
    assert len(per_slide) > 1 or len(text) <= 1000
    # Every rendered paragraph is a line fragment; joining all fragments loses only chunk-boundary newlines.
    rendered = "".join(p for paras in per_slide for p in paras)
    assert rendered.replace(" ", "") == sanitize_text(text).replace("\n", "").replace(" ", "")
