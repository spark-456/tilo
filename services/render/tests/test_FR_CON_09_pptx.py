"""Acceptance tests for AGR-02 PPTX renderer with native charts (FR-CON-09)."""

import io
import json

import pptx
from pptx.dml.color import RGBColor
from tilo_render.pptx import _find_repo_root, render_pptx
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
    t_rows: list[list[str | int | float]] = rows or [["Alpha", 10.0, 5.0], ["Beta", 20.0, 15.0], ["Gamma", 30.0, 25.0]]
    return DeliverableSpec(
        title="Sample Report",
        subtitle="Subtitle text",
        date="2026-10-02",
        tables=[Table(id="t1", columns=["label", "s1", "s2"], rows=t_rows)],
        charts=[
            Chart(id="c_bar", kind=ChartKind.BAR, table_id="t1", x="label", y=["s1", "s2"], title="Bar Chart"),
            Chart(id="c_line", kind=ChartKind.LINE, table_id="t1", x="label", y="s1", title="Line Chart"),
            Chart(id="c_pie", kind=ChartKind.PIE, table_id="t1", x="label", y="s2", title="Pie Chart"),
        ],
        sections=[
            Section(
                heading="Overview",
                blocks=[
                    ParagraphBlock(text="Intro paragraph."),
                    BulletsBlock(bullets=["Point 1", "Point 2"]),
                    TableBlock(table_id="t1"),
                    ChartBlock(chart_id="c_bar"),
                    ChartBlock(chart_id="c_line"),
                    ChartBlock(chart_id="c_pie"),
                ],
            )
        ],
    )


def test_FR_CON_09_pptx_chart_values_equal_the_source_table() -> None:
    spec = _make_sample_spec()
    prs = pptx.Presentation(io.BytesIO(render_pptx(spec)))
    chart_shapes = [sh.chart for s in prs.slides for sh in s.shapes if sh.has_chart]
    assert len(chart_shapes) == len(spec.charts)
    for chart_def, chart in zip(spec.charts, chart_shapes, strict=True):
        tbl = next(t for t in spec.tables if t.id == chart_def.table_id)
        x_idx = tbl.columns.index(chart_def.x)
        assert [getattr(c, "label", str(c)) for c in chart.plots[0].categories] == [str(r[x_idx]) for r in tbl.rows]
        for y_col in chart_def.y_columns:
            y_idx = tbl.columns.index(y_col)
            assert list(next(s for s in chart.series if s.name == y_col).values) == [float(r[y_idx]) for r in tbl.rows]


def test_FR_CON_09_pptx_opens_and_has_one_slide_per_block() -> None:
    assert len(pptx.Presentation(io.BytesIO(render_pptx(_make_sample_spec()))).slides) == 8


def test_FR_CON_09_pptx_splits_long_content_across_slides() -> None:
    b_spec = DeliverableSpec(
        title="B",
        date="2026-10-02",
        sections=[Section(heading="H", blocks=[BulletsBlock(bullets=[f"b{i}" for i in range(300)])])],
    )
    b_slides = [s for s in pptx.Presentation(io.BytesIO(render_pptx(b_spec))).slides]
    assert len([s for s in b_slides if any("•" in sh.text for sh in s.shapes if sh.has_text_frame)]) == 38

    p_spec = DeliverableSpec(
        title="P",
        date="2026-10-02",
        sections=[Section(heading="H", blocks=[ParagraphBlock(text="word " * 4000)])],
    )
    p_slides = [s for s in pptx.Presentation(io.BytesIO(render_pptx(p_spec))).slides]
    assert len([s for s in p_slides if any("word" in sh.text for sh in s.shapes if sh.has_text_frame)]) >= 20

    long_rows: list[list[str | int | float]] = [[f"Item {i}", float(i), float(i * 2)] for i in range(25)]
    t_slides = [s for s in pptx.Presentation(io.BytesIO(render_pptx(_make_sample_spec(rows=long_rows)))).slides]
    assert len([s for s in t_slides if any(sh.has_table for sh in s.shapes)]) == 3


def test_FR_CON_09_pptx_colours_come_from_token_roles() -> None:
    prs = pptx.Presentation(io.BytesIO(render_pptx(_make_sample_spec())))
    tokens = json.loads((_find_repo_root() / "design" / "tokens.json").read_text(encoding="utf-8"))
    assert prs.slides[0].background.fill.fore_color.rgb == RGBColor.from_string(
        tokens["color"]["brand"]["primary"]["value"].lstrip("#")
    )


def test_FR_CON_09_pptx_escapes_untrusted_text() -> None:
    bad_xml = "<script>alert('xss')</script> & evil \ufffe\uffff\r\x00\x07<tag>'\""
    bad_cat = "cat \ufffe\uffff\ud800\r\x00\x07<tag>&'\""
    spec = DeliverableSpec(
        title=f"D {bad_xml}",
        date="2026-10-02",
        tables=[Table(id="t_bad", columns=["cat", "v"], rows=[[bad_cat, 1.0]])],
        charts=[Chart(id="c_bad", kind=ChartKind.BAR, table_id="t_bad", x="cat", y="v", title="Chart")],
        sections=[
            Section(
                heading=f"H {bad_xml}",
                blocks=[
                    ParagraphBlock(text=(bad_xml * 800)[:20000]),
                    BulletsBlock(bullets=[f"B {bad_xml}"]),
                    TableBlock(table_id="t_bad"),
                    ChartBlock(chart_id="c_bad"),
                ],
            )
        ],
    )
    prs = pptx.Presentation(io.BytesIO(render_pptx(spec)))
    all_text = " ".join(sh.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    cats = [
        getattr(pt, "label", str(pt))
        for s in prs.slides
        for sh in s.shapes
        if sh.has_chart
        for pt in sh.chart.plots[0].categories
    ]
    assert "<tag>" in all_text and "&" in all_text and "<script>" in all_text
    for forbidden in ["\ufffe", "\uffff", "\ud800", "\x00", "\x07", "_x000D_"]:
        assert forbidden not in all_text and all(forbidden not in cat for cat in cats)
