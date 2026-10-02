"""Acceptance tests for AGR-03, the PDF report renderer with data-labelled charts (FR-CON-09)."""

import io
from pathlib import Path
from typing import Any

import yaml
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
from tilo_render.text import find_repo_root

TEMPLATE = find_repo_root() / "templates" / "report" / "default.yaml"
FMT: str = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))["format"]["number_format"]


def _pages(spec: DeliverableSpec, **kw: Any) -> list[str]:
    return [p.extract_text() for p in PdfReader(io.BytesIO(render_pdf(spec, **kw))).pages]


def _one_section(blocks: list[Any], **spec_kw: Any) -> DeliverableSpec:
    return DeliverableSpec(title="T", date="2026-10-02", sections=[Section(heading="H", blocks=blocks)], **spec_kw)


def test_FR_CON_09_pdf_chart_values_equal_the_source_table() -> None:
    # The chart tables are never shown as tables, so every value below can only come from a chart data label.
    data: list[tuple[str, float, float]] = [
        ("Q-one", 1234567.5, 0.125),
        ("Q-two", -42.0, 7.0),
        ("Q-three", 3.0, 99999.0),
    ]
    shown_rows: list[tuple[str, int | float]] = [("Visible-row", 1500000), ("Other-row", 2.5)]
    shown = Table(id="shown", columns=["Item", "Amount"], rows=[list(r) for r in shown_rows])
    chart_t = Table(id="ct", columns=["x", "a", "b"], rows=[list(r) for r in data])
    charts = [
        Chart(id="bar", kind=ChartKind.BAR, table_id="ct", x="x", y=["a", "b"], title="Bar title"),
        Chart(id="line", kind=ChartKind.LINE, table_id="ct", x="x", y="a", title="Line title"),
        Chart(id="pie", kind=ChartKind.PIE, table_id="ct", x="x", y="b", title="Pie title"),
    ]
    spec = _one_section(
        [TableBlock(table_id="shown")] + [ChartBlock(chart_id=c.id) for c in charts],
        tables=[shown, chart_t],
        charts=charts,
    )
    text = "\n".join(_pages(spec))

    for name, amount in shown_rows:  # every table cell, formatted as the template says
        assert name in text
        assert (f"{amount:,}" if isinstance(amount, int) else format(amount, FMT)) in text
    for chart in charts:
        assert chart.title in text
        for row in data:
            assert row[0] in text
    for series_idx in (1, 2):  # bar chart labels every value of both series
        for row in data:
            assert format(row[series_idx], FMT) in text
    assert text.count(format(data[0][1], FMT)) == 2  # bar label + line label for series "a"
    assert text.count(format(data[2][2], FMT)) == 2  # bar label + pie label for series "b"


def test_FR_CON_09_pdf_number_format_comes_from_the_template(tmp_path: Path) -> None:
    tmpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    tmpl["format"]["number_format"] = ".3f"
    custom = tmp_path / "t.yaml"
    custom.write_text(yaml.safe_dump(tmpl), encoding="utf-8")
    ct = Table(id="ct", columns=["x", "v"], rows=[["a", 1.5], ["b", 2.25]])
    chart = Chart(id="c", kind=ChartKind.BAR, table_id="ct", x="x", y="v", title="C")
    text = "\n".join(
        _pages(_one_section([ChartBlock(chart_id="c")], tables=[ct], charts=[chart]), template_path=custom)
    )
    assert "1.500" in text and "2.250" in text


def test_FR_CON_09_pdf_opens_and_paginates_long_tables() -> None:
    rows: list[list[str | int | float]] = [[f"Item-{i}", i, float(i * 2)] for i in range(500)]
    tbl = Table(id="t", columns=["ItemName", "MetricA", "MetricB"], rows=rows)
    pages = _pages(_one_section([TableBlock(table_id="t")], tables=[tbl]))
    assert len(pages) > 1
    for idx, page in enumerate(pages):
        for col in tbl.columns:
            assert col in page, f"header {col} missing on page {idx + 1}"
    text = "\n".join(pages)
    assert all(f"Item-{i}" in text for i in (0, 250, 499))


def test_FR_CON_09_pdf_escapes_untrusted_markup() -> None:
    evil = '<a href="https://x.invalid">click</a> <img src="https://x.invalid/p.png"> <b>bold</b> & <br/>'
    tbl = Table(id="t", columns=["c"], rows=[[evil]])
    spec = DeliverableSpec(
        title=f"Title {evil}",
        subtitle=evil,
        date="2026-10-02",
        tables=[tbl],
        sections=[
            Section(
                heading=evil,
                blocks=[ParagraphBlock(text=evil), BulletsBlock(bullets=[evil]), TableBlock(table_id="t")],
            )
        ],
    )
    raw = render_pdf(spec)
    reader = PdfReader(io.BytesIO(raw))
    text = "\n".join(p.extract_text() for p in reader.pages)
    assert text.count('<a href="https://x.invalid">click</a>') >= 5
    assert '<img src="https://x.invalid/p.png">' in text
    assert "<b>bold</b>" in text
    for page in reader.pages:
        assert not page.get("/Annots")
        assert len(list(page.images)) == 0
    assert b"/URI" not in raw


def test_FR_CON_09_pdf_newlines_become_separate_paragraphs() -> None:
    spec = _one_section(
        [ParagraphBlock(text="para-one\r\npara-two\n\npara-three"), BulletsBlock(bullets=["bul-x\nbul-y", "", "bul-z"])]
    )
    text = "\n".join(_pages(spec))
    assert "para-one para-two" not in text and "bul-x bul-y" not in text  # not collapsed into one paragraph
    lines = [ln.strip() for ln in text.splitlines()]
    for token in ("para-one", "para-two", "para-three"):
        assert token in lines
    for token in ("bul-x", "bul-y", "bul-z"):
        assert any(ln.endswith(token) and ln != token for ln in lines)  # each line carries its own bullet marker


def test_FR_CON_09_pdf_strips_xml_invalid_characters() -> None:
    bad = "\ufffe\uffff\x00\x07\x1b\x85"  # lone surrogates never get past the spec model
    tbl = Table(id="t", columns=["cat", "val"], rows=[[f"ca{bad}t", 41.5]])
    chart = Chart(id="c", kind=ChartKind.BAR, table_id="t", x="cat", y="val", title=f"Chart{bad}")
    spec = DeliverableSpec(
        title=f"Ti{bad}tle",
        subtitle=f"Su{bad}b",
        date="2026-10-02",
        tables=[tbl],
        charts=[chart],
        sections=[
            Section(
                heading=f"He{bad}ad",
                blocks=[
                    ParagraphBlock(text=f"pa{bad}ra"),
                    BulletsBlock(bullets=[f"bu{bad}l"]),
                    TableBlock(table_id="t"),
                    ChartBlock(chart_id="c"),
                ],
            )
        ],
    )
    text = "\n".join(_pages(spec))
    for good in ("Title", "Sub", "Head", "para", "bul", "cat", "Chart", "41.5"):
        assert good in text
    assert not set(bad) & set(text)


def test_FR_CON_09_pdf_handles_huge_cells_and_non_latin_text() -> None:
    tbl = Table(id="t", columns=["c"], rows=[["w" * 30_000], ["word " * 6_000], ["日本語 → ✓ emoji 😀"]])
    text = "\n".join(_pages(_one_section([TableBlock(table_id="t")], tables=[tbl])))
    assert "www" in text and "word" in text


def test_FR_CON_09_pdf_same_spec_gives_the_same_pdf() -> None:
    tbl = Table(id="t", columns=["x", "v"], rows=[["a", 1.0], ["b", 2.0]])
    chart = Chart(id="c", kind=ChartKind.LINE, table_id="t", x="x", y="v", title="C")
    spec = _one_section([TableBlock(table_id="t"), ChartBlock(chart_id="c")], tables=[tbl], charts=[chart])
    assert render_pdf(spec) == render_pdf(spec)
