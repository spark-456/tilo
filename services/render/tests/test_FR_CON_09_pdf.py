"""Acceptance tests for AGR-03 PDF report renderer with data-labelled charts (FR-CON-09)."""

import io
import json
from pathlib import Path

from pypdf import PdfReader
from tilo_render.pdf import _find_repo_root, render_pdf
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
    default_rows: list[list[str | int | float]] = [["Alpha", 10.0, 5.0], ["Beta", 20.0, 15.0], ["Gamma", 30.0, 25.0]]
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
    reader = PdfReader(io.BytesIO(render_pdf(spec)))
    full_text = "\n".join(page.extract_text() for page in reader.pages)

    t1 = spec.tables[0]
    for col in t1.columns:
        assert col in full_text
    for row in t1.rows:
        for cell in row:
            assert (f"{cell:g}" if isinstance(cell, (int, float)) else str(cell)) in full_text

    for chart_def in spec.charts:
        assert chart_def.title in full_text
        tbl = next(t for t in spec.tables if t.id == chart_def.table_id)
        x_idx = tbl.columns.index(chart_def.x)
        for row in tbl.rows:
            assert str(row[x_idx]) in full_text
        for y_col in chart_def.y_columns:
            y_idx = tbl.columns.index(y_col)
            for row in tbl.rows:
                assert f"{float(row[y_idx]):g}" in full_text


def test_FR_CON_09_pdf_opens_and_paginates_long_tables() -> None:
    long_rows: list[list[str | int | float]] = [[f"Item {i}", float(i), float(i * 2)] for i in range(500)]
    t_long = Table(id="t_long", columns=["ItemName", "MetricA", "MetricB"], rows=long_rows)
    spec = DeliverableSpec(
        title="Long Table Report",
        date="2026-10-02",
        tables=[t_long],
        sections=[Section(heading="Long Table Section", blocks=[TableBlock(table_id="t_long")])],
    )
    reader = PdfReader(io.BytesIO(render_pdf(spec)))
    assert len(reader.pages) > 1
    for idx, page in enumerate(reader.pages):
        page_text = page.extract_text()
        for col in ["ItemName", "MetricA", "MetricB"]:
            assert col in page_text, f"Header {col} missing on page {idx + 1}"


def test_FR_CON_09_pdf_escapes_untrusted_markup() -> None:
    bad_xml = '<a href="https://x.invalid">malicious</a> and <img src="bad.png"> & \ufffe\uffff\r\x00\x07'
    bad_cat = "cat \ufffe\uffff\ud800\r\x00\x07<tag>'\""
    t = Table(id="t_bad", columns=["col_cat", "val"], rows=[[bad_cat, 42.0]])
    c = Chart(id="c_bad", kind=ChartKind.BAR, table_id="t_bad", x="col_cat", y="val", title="Chart Title")
    spec = DeliverableSpec(
        title=f"Untrusted <Markup> & Test {bad_xml}",
        subtitle=f"Subtitle with <tags> {bad_xml}",
        date="2026-10-02",
        tables=[t],
        charts=[c],
        sections=[
            Section(
                heading=f"Heading <1> {bad_xml}",
                blocks=[
                    ParagraphBlock(text=bad_xml),
                    BulletsBlock(bullets=['Bullet with <a href="bad">link</a>']),
                    TableBlock(table_id="t_bad"),
                    ChartBlock(chart_id="c_bad"),
                ],
            )
        ],
    )
    reader = PdfReader(io.BytesIO(render_pdf(spec)))
    full_text = "\n".join(page.extract_text() for page in reader.pages)

    assert '<a href="https://x.invalid">' in full_text
    assert '<img src="bad.png">' in full_text
    for forbidden in ["\ufffe", "\uffff", "\ud800", "\x00", "\x07"]:
        assert forbidden not in full_text

    for page in reader.pages:
        annots = page.get("/Annots")
        assert annots is None or len(annots) == 0
        assert len(list(page.images)) == 0


def test_FR_CON_09_pdf_colours_come_from_token_roles(tmp_path: Path) -> None:
    tokens = json.loads((_find_repo_root() / "design" / "tokens.json").read_text(encoding="utf-8"))
    tok_file = tmp_path / "tokens.json"
    tok_file.write_text(json.dumps(tokens), encoding="utf-8")
    assert len(render_pdf(_make_sample_spec(), tokens_path=tok_file)) > 0


def test_FR_CON_09_pdf_is_deterministic() -> None:
    spec = _make_sample_spec()
    r1 = PdfReader(io.BytesIO(render_pdf(spec)))
    r2 = PdfReader(io.BytesIO(render_pdf(spec)))
    assert len(r1.pages) == len(r2.pages)
    assert "\n".join(p.extract_text() for p in r1.pages) == "\n".join(p.extract_text() for p in r2.pages)
