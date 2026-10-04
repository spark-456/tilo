"""PDF report renderer with data-labelled charts (FR-CON-09; PRD 6.6, 12.4, 12.6).

Deterministic: no model calls, no network, no clock. All deliverable text is untrusted, so it is sanitised and
XML-escaped before it enters a reportlab `Paragraph`; chart text goes into `String` shapes, which parse no markup.
"""

import html
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors, pagesizes
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, TableStyle
from reportlab.platypus import Table as PlTable
from tilo_contracts import Manifest

from tilo_render.charts import ChartData
from tilo_render.spec import (
    BulletsBlock,
    ChartBlock,
    ChartKind,
    DeliverableSpec,
    ParagraphBlock,
    TableBlock,
)
from tilo_render.text import PROVENANCE_HEADING, find_repo_root, lines, provenance_lines, sanitize_text, wrap_long_token

_PAGE_SIZES = {"A4": pagesizes.A4, "LETTER": pagesizes.LETTER}
_CHART_H = 180


def _resolve_color(role: str, tokens: dict[str, Any]) -> colors.Color:
    node: Any = tokens.get("color", {})
    for part in role.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"Unknown colour role in template: {role}")
        node = node[part]
    return colors.HexColor(node["value"] if isinstance(node, dict) and "value" in node else str(node))


def _markup(text: str) -> str:
    """Untrusted text to reportlab markup: sanitised, escaped; newlines become the only markup we emit (<br/>)."""
    return "<br/>".join(html.escape(line, quote=True) for line in lines(text))


def _flat(text: str) -> str:
    """Sanitised single-line text for places that take plain strings (chart shapes, PDF metadata)."""
    return sanitize_text(text).replace("\n", " ")


def _formatter(spec_fmt: str) -> Callable[[Any], str]:
    def fmt(val: Any) -> str:
        if isinstance(val, bool) or not isinstance(val, int | float):
            return sanitize_text(str(val))
        return f"{val:,}" if isinstance(val, int) else format(val, spec_fmt)

    return fmt


def _chart(ch: Any, data: ChartData, aw: float, fmt: Callable[[Any], str], th: dict[str, Any]) -> Drawing:
    typo, col, palette = th["typo"], th["colors"], th["palette"]
    drawing = Drawing(aw, _CHART_H)
    drawing.add(
        String(
            0,
            _CHART_H - 15,
            _flat(ch.title),
            fontName="Helvetica-Bold",
            fontSize=typo["chart_title_size_pt"],
            fillColor=col["chart_title"],
        )
    )
    size = typo["chart_label_size_pt"]
    if ch.kind == ChartKind.PIE:
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = (aw - 130) / 2, 15, 130, 130
        values = data.series[ch.y_columns[0]]
        pie.data = values
        pie.labels = [f"{wrap_long_token(_flat(c))}: {fmt(v)}" for c, v in zip(data.categories, values, strict=True)]
        pie.slices.labelRadius, pie.slices.fontSize, pie.slices.fontColor = 1.05, size, col["chart_label"]
        for idx in range(len(values)):
            pie.slices[idx].fillColor = palette[idx % len(palette)]
        drawing.add(pie)
        return drawing
    is_bar = ch.kind == ChartKind.BAR
    chart: Any = VerticalBarChart() if is_bar else HorizontalLineChart()
    chart.x, chart.y, chart.width, chart.height = 40, 20, aw - 60, 130
    chart.data = [data.series[c] for c in ch.y_columns]
    chart.categoryAxis.categoryNames = [wrap_long_token(_flat(c)) for c in data.categories]
    chart.categoryAxis.labels.fontSize = chart.valueAxis.labels.fontSize = size
    labels = chart.barLabels if is_bar else chart.lineLabels
    labels.fontSize, labels.fillColor = size, col["chart_label"]
    if is_bar:
        chart.barLabelFormat, labels.nudge = fmt, 5  # a data label on every bar
    else:
        chart.lineLabelFormat = fmt  # a data label on every point
    for idx in range(len(ch.y_columns)):
        if is_bar:
            chart.bars[idx].fillColor = palette[idx % len(palette)]
        else:
            chart.lines[idx].strokeColor = palette[idx % len(palette)]
    drawing.add(chart)
    return drawing


def render_pdf(
    spec: DeliverableSpec,
    *,
    manifest: Manifest | None = None,
    template_path: Path | str | None = None,
    tokens_path: Path | str | None = None,
) -> bytes:
    root = find_repo_root()
    tmpl = yaml.safe_load(Path(template_path or root / "templates" / "report" / "default.yaml").read_text("utf-8"))
    tokens = json.loads(Path(tokens_path or root / "design" / "tokens.json").read_text("utf-8"))

    cfg = tmpl.get("colors", {})
    col = {k: _resolve_color(v, tokens) for k, v in cfg.items() if k != "chart_palette"}
    palette = [_resolve_color(r, tokens) for r in cfg["chart_palette"]]
    typo = {k: float(v) for k, v in tmpl["typography"].items()}
    fmt = _formatter(str(tmpl["format"]["number_format"]))
    page = tmpl.get("page", {})
    theme = {"typo": typo, "colors": col, "palette": palette}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=_PAGE_SIZES[str(page.get("size", "A4")).upper()],
        leftMargin=float(page["margin_left_pt"]),
        rightMargin=float(page["margin_right_pt"]),
        topMargin=float(page["margin_top_pt"]),
        bottomMargin=float(page["margin_bottom_pt"]),
        title=_flat(spec.title),
        author="Tilo",
        invariant=True,  # fixed creation date and document id: the same spec gives the same bytes
    )

    def style(name: str, font: str, size_key: str, colour: str, lead: float = 1.25, **kw: Any) -> ParagraphStyle:
        size = typo[size_key]
        return ParagraphStyle(name, fontName=font, fontSize=size, leading=size * lead, textColor=col[colour], **kw)

    title_s = style("T", "Helvetica-Bold", "title_size_pt", "title", spaceAfter=6)
    sub_s = style("S", "Helvetica", "subtitle_size_pt", "subtitle", spaceAfter=4)
    date_s = style("D", "Helvetica", "date_size_pt", "date", spaceAfter=14)
    head_s = style("H", "Helvetica-Bold", "heading_size_pt", "heading", spaceBefore=10, spaceAfter=6)
    body_s = style("B", "Helvetica", "body_size_pt", "body", 1.35, spaceAfter=6)
    bullet_s = style(
        "BL", "Helvetica", "bullet_size_pt", "bullet", 1.35, leftIndent=15, firstLineIndent=-10, spaceAfter=3
    )
    th_s = style("TH", "Helvetica-Bold", "table_header_size_pt", "table_header_fg")
    td_s = style("TD", "Helvetica", "table_body_size_pt", "table_row_fg")

    story: list[Any] = [Paragraph(_markup(spec.title), title_s)]
    if spec.subtitle:
        story.append(Paragraph(_markup(spec.subtitle), sub_s))
    story.append(Paragraph(_markup(spec.date), date_s))

    tables = {t.id: t for t in spec.tables}
    charts = {c.id: c for c in spec.charts}
    for section in spec.sections:
        story.append(Paragraph(_markup(section.heading), head_s))
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                # One Paragraph per line (reportlab would collapse "\n" into a space); a blank line is a gap.
                for line in lines(block.text):
                    story.append(Paragraph(_markup(line), body_s) if line.strip() else Spacer(1, body_s.leading))
            elif isinstance(block, BulletsBlock):
                for line in (ln for item in block.bullets for ln in lines(item) if ln.strip()):
                    story.append(Paragraph(_markup(line), bullet_s, bulletText="•"))
                story.append(Spacer(1, 4))
            elif isinstance(block, TableBlock):
                tbl = tables[block.table_id]
                head = [Paragraph(_markup(c), th_s) for c in tbl.columns]
                body = [[Paragraph(_markup(fmt(c)), td_s) for c in row] for row in tbl.rows]
                flow = PlTable(
                    [head, *body],
                    colWidths=[doc.width / len(tbl.columns)] * len(tbl.columns),
                    repeatRows=1,
                    splitInRow=1,
                )
                flow.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), col["table_header_bg"]),
                            ("GRID", (0, 0), (-1, -1), 0.5, col["table_grid"]),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.extend([flow, Spacer(1, 8)])
            elif isinstance(block, ChartBlock):
                chart = charts[block.chart_id]
                story.extend([_chart(chart, ChartData.from_spec(spec, chart.id), doc.width, fmt, theme), Spacer(1, 8)])

    if manifest is not None:
        story.append(Paragraph(_markup(PROVENANCE_HEADING), head_s))
        for line in provenance_lines(manifest):
            story.append(Paragraph(_markup(line), bullet_s, bulletText="•"))
        story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()
