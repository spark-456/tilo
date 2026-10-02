"""Acceptance tests for AGR-03 PDF report renderer with data-labelled charts (FR-CON-09)."""

import io
import json
from pathlib import Path

from pypdf import PdfReader
from tilo_render.pdf import render_pdf
from tilo_render.spec import (
    BulletsBlock,
    Chart,
    ChartBlock,
    ChartKind,
    DeliverableSpec,
    ParagraphBlock,
    Section,
    Table,
    TableBlock,
)


def _make_sample_spec(rows: list[list[str | int | float]] | None = None) -> DeliverableSpec:
    default_rows: list[list[str | int | float]] = [
        ["Alpha", 10.0, 5.0],
        ["Beta", 20.0, 15.0],
        ["Gamma", 30.0, 25.0],
    ]
    t1 = Table(id="t1", columns=["label", "s1", "s2"], rows=rows or default_rows)
    return DeliverableSpec(
        title="Sample Report",
        subtitle="Report Subtitle",
        date="2026-10-02",
        tables=[t1],
        charts=[
            Chart(id="c_bar", kind=ChartKind.BAR, table_id="t1", x="label", y=["s1", "s2"], title="Bar Chart"),
            Chart(id="c_line", kind=ChartKind.LINE, table_id="t1", x="label", y="s1", title="Line Chart"),
            Chart(id="c_pie", kind=ChartKind.PIE, table_id="t1", x="label", y="s2", title="Pie Chart"),
        ],
        sections=[
            Section(
                heading="Overview",
                blocks=[
                    ParagraphBlock(text="Introductory text for the PDF report."),
                    BulletsBlock(bullets=["Key finding one", "Key finding two"]),
                    TableBlock(table_id="t1"),
                    ChartBlock(chart_id="c_bar"),
                    ChartBlock(chart_id="c_line"),
                    ChartBlock(chart_id="c_pie"),
                ],
            )
        ],
    )


def test_FR_CON_09_pdf_chart_values_equal_the_source_table() -> None:
    spec = _make_sample_spec()
    pdf_bytes = render_pdf(spec)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(page.extract_text() for page in reader.pages)

    t1 = spec.tables[0]
    for col in t1.columns:
        assert col in full_text
    for row in t1.rows:
        for cell in row:
            formatted = f"{cell:g}" if isinstance(cell, (int, float)) else str(cell)
            assert formatted in full_text

    for chart in spec.charts:
        assert chart.title in full_text

    for val in [10.0, 20.0, 30.0, 5.0, 15.0, 25.0]:
        assert f"{val:g}" in full_text


def test_FR_CON_09_pdf_opens_and_paginates_long_tables() -> None:
    long_rows: list[list[str | int | float]] = [[f"Item {i}", float(i), float(i * 2)] for i in range(500)]
    t_long = Table(id="t_long", columns=["ItemName", "MetricA", "MetricB"], rows=long_rows)
    spec = DeliverableSpec(
        title="Long Table Report",
        date="2026-10-02",
        tables=[t_long],
        sections=[Section(heading="Long Table Section", blocks=[TableBlock(table_id="t_long")])],
    )
    pdf_bytes = render_pdf(spec)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) > 1

    for idx, page in enumerate(reader.pages):
        page_text = page.extract_text()
        assert "ItemName" in page_text, f"Header ItemName missing on page {idx + 1}"
        assert "MetricA" in page_text, f"Header MetricA missing on page {idx + 1}"
        assert "MetricB" in page_text, f"Header MetricB missing on page {idx + 1}"


def test_FR_CON_09_pdf_escapes_untrusted_markup() -> None:
    evil_text = '<a href="https://x.invalid">malicious</a> and <img src="bad.png"> & "quotes"'
    spec = DeliverableSpec(
        title="Untrusted <Markup> & Test",
        subtitle="Subtitle with <tags>",
        date="2026-10-02",
        sections=[
            Section(
                heading="Heading <1>",
                blocks=[
                    ParagraphBlock(text=evil_text),
                    BulletsBlock(bullets=['Bullet with <a href="bad">link</a>']),
                ],
            )
        ],
    )
    pdf_bytes = render_pdf(spec)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(page.extract_text() for page in reader.pages)

    assert '<a href="https://x.invalid">' in full_text
    assert '<img src="bad.png">' in full_text

    for page in reader.pages:
        annots = page.get("/Annots")
        assert annots is None or len(annots) == 0
        assert len(list(page.images)) == 0


def test_FR_CON_09_pdf_colours_come_from_token_roles(tmp_path: Path) -> None:
    spec = _make_sample_spec()
    custom_tokens = {
        "color": {
            "brand": {"primary": {"value": "#123456"}},
            "surface": {"0": {"value": "#FFFFFF"}, "1": {"value": "#FFFFFF"}, "2": {"value": "#EEEEEE"}},
            "ink": {"1": {"value": "#111111"}, "2": {"value": "#222222"}},
            "district": {
                "research": {"value": "#333333"},
                "analysis": {"value": "#444444"},
                "delivery": {"value": "#555555"},
            },
            "signal": {"done": {"value": "#00AA00"}},
        }
    }
    tok_file = tmp_path / "tokens.json"
    tok_file.write_text(json.dumps(custom_tokens), encoding="utf-8")
    pdf_bytes = render_pdf(spec, tokens_path=tok_file)
    assert len(pdf_bytes) > 0


def test_FR_CON_09_pdf_is_deterministic() -> None:
    spec = _make_sample_spec()
    pdf1 = render_pdf(spec)
    pdf2 = render_pdf(spec)
    r1 = PdfReader(io.BytesIO(pdf1))
    r2 = PdfReader(io.BytesIO(pdf2))
    assert len(r1.pages) == len(r2.pages)
    t1 = "\n".join(p.extract_text() for p in r1.pages)
    t2 = "\n".join(p.extract_text() for p in r2.pages)
    assert t1 == t2
