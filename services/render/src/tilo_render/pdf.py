"""PDF report renderer with data-labelled charts (FR-CON-09; PRD 6.6, 12.4, 12.6)."""

import html
import io
import json
from pathlib import Path
from typing import Any

import yaml
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, TableStyle
from reportlab.platypus import Table as PlTable

from tilo_render.charts import ChartData
from tilo_render.spec import (
    BulletsBlock,
    ChartBlock,
    ChartKind,
    DeliverableSpec,
    ParagraphBlock,
    TableBlock,
)


def _find_repo_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in [cur] + list(cur.parents):
        if (parent / "design" / "tokens.json").exists():
            return parent
    return Path.cwd()


def _resolve_color(role: str, tokens: dict[str, Any]) -> colors.HexColor:
    node: Any = tokens.get("color", {})
    for part in role.split("."):
        if not isinstance(node, dict) or part not in node:
            return colors.HexColor("#5A3FE0")
        node = node[part]
    val = node["value"] if isinstance(node, dict) and "value" in node else str(node)
    return colors.HexColor(val)


def sanitize_text(text: str) -> str:
    return "".join(
        ch for ch in text if ch in "\t\n\r" or (ord(ch) >= 32 and ord(ch) != 127 and not (0x80 <= ord(ch) <= 0x9F))
    )


def escape_text(text: str) -> str:
    return html.escape(sanitize_text(text), quote=True)


def format_value(val: Any, num_format: str = "%g") -> str:
    if isinstance(val, (int, float)):
        return num_format % val
    return sanitize_text(str(val))


def render_pdf(
    spec: DeliverableSpec,
    template_path: Path | str | None = None,
    tokens_path: Path | str | None = None,
) -> bytes:
    root = _find_repo_root()
    tmpl_p = Path(template_path) if template_path else root / "templates" / "report" / "default.yaml"
    tok_p = Path(tokens_path) if tokens_path else root / "design" / "tokens.json"

    with open(tmpl_p, encoding="utf-8") as f:
        tmpl = yaml.safe_load(f)
    with open(tok_p, encoding="utf-8") as f:
        tokens = json.load(f)

    colors_cfg = tmpl.get("colors", {})
    col_map = {k: _resolve_color(v, tokens) for k, v in colors_cfg.items() if k != "chart_palette"}
    palette_roles = colors_cfg.get("chart_palette", ["brand.primary"])
    palette = [_resolve_color(r, tokens) for r in palette_roles]
    typo = {k: float(v) for k, v in tmpl.get("typography", {}).items()}
    num_format = str(tmpl.get("format", {}).get("number_format", "%g"))

    page_cfg = tmpl.get("page", {})
    margin_top = float(page_cfg.get("margin_top_pt", 54))
    margin_bottom = float(page_cfg.get("margin_bottom_pt", 54))
    margin_left = float(page_cfg.get("margin_left_pt", 54))
    margin_right = float(page_cfg.get("margin_right_pt", 54))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin_left,
        rightMargin=margin_right,
        topMargin=margin_top,
        bottomMargin=margin_bottom,
    )
    avail_width = doc.width

    title_s = ParagraphStyle(
        "DocTitle",
        fontName="Helvetica-Bold",
        fontSize=typo["title_size_pt"],
        leading=typo["title_size_pt"] * 1.25,
        textColor=col_map["title"],
        spaceAfter=6,
    )
    sub_s = ParagraphStyle(
        "DocSub",
        fontName="Helvetica",
        fontSize=typo["subtitle_size_pt"],
        leading=typo["subtitle_size_pt"] * 1.25,
        textColor=col_map["subtitle"],
        spaceAfter=4,
    )
    date_s = ParagraphStyle(
        "DocDate",
        fontName="Helvetica",
        fontSize=typo["date_size_pt"],
        leading=typo["date_size_pt"] * 1.25,
        textColor=col_map["date"],
        spaceAfter=14,
    )
    heading_s = ParagraphStyle(
        "Heading",
        fontName="Helvetica-Bold",
        fontSize=typo["heading_size_pt"],
        leading=typo["heading_size_pt"] * 1.25,
        textColor=col_map["heading"],
        spaceBefore=10,
        spaceAfter=6,
    )
    body_s = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=typo["body_size_pt"],
        leading=typo["body_size_pt"] * 1.35,
        textColor=col_map["body"],
        spaceAfter=6,
    )
    bullet_s = ParagraphStyle(
        "Bullet",
        fontName="Helvetica",
        fontSize=typo["bullet_size_pt"],
        leading=typo["bullet_size_pt"] * 1.35,
        textColor=col_map["bullet"],
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=3,
    )
    th_s = ParagraphStyle(
        "TH",
        fontName="Helvetica-Bold",
        fontSize=typo["table_header_size_pt"],
        leading=typo["table_header_size_pt"] * 1.2,
        textColor=col_map["table_header_fg"],
    )
    td_s = ParagraphStyle(
        "TD",
        fontName="Helvetica",
        fontSize=typo["table_body_size_pt"],
        leading=typo["table_body_size_pt"] * 1.2,
        textColor=col_map["table_row_fg"],
    )

    story: list[Any] = []
    story.append(Paragraph(escape_text(spec.title), title_s))
    if spec.subtitle:
        story.append(Paragraph(escape_text(spec.subtitle), sub_s))
    story.append(Paragraph(escape_text(spec.date), date_s))

    tbl_lookup = {t.id: t for t in spec.tables}
    chart_lookup = {c.id: c for c in spec.charts}

    for section in spec.sections:
        story.append(Paragraph(escape_text(section.heading), heading_s))
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                story.append(Paragraph(escape_text(block.text), body_s))
            elif isinstance(block, BulletsBlock):
                for bullet in block.bullets:
                    story.append(Paragraph(escape_text(bullet), bullet_s, bulletText="•"))
                story.append(Spacer(1, 4))
            elif isinstance(block, TableBlock):
                tbl = tbl_lookup[block.table_id]
                h_cells = [Paragraph(escape_text(col), th_s) for col in tbl.columns]
                d_rows = [
                    [Paragraph(escape_text(format_value(cell, num_format)), td_s) for cell in row] for row in tbl.rows
                ]
                col_w = avail_width / len(tbl.columns)
                table_flowable = PlTable(
                    [h_cells] + d_rows,
                    colWidths=[col_w] * len(tbl.columns),
                    repeatRows=1,
                )
                table_flowable.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), col_map["table_header_bg"]),
                            ("GRID", (0, 0), (-1, -1), 0.5, col_map["table_grid"]),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.append(table_flowable)
                story.append(Spacer(1, 8))
            elif isinstance(block, ChartBlock):
                ch = chart_lookup[block.chart_id]
                ch_data = ChartData.from_spec(spec, ch.id)
                ch_d = Drawing(avail_width, 180)
                ch_d.add(
                    String(
                        0,
                        165,
                        sanitize_text(ch.title),
                        fontName="Helvetica-Bold",
                        fontSize=typo["chart_title_size_pt"],
                        fillColor=col_map["chart_title"],
                    )
                )
                if ch.kind == ChartKind.BAR:
                    bc = VerticalBarChart()
                    bc.x, bc.y, bc.width, bc.height = 40, 20, avail_width - 60, 130
                    bc.data = [ch_data.series[col] for col in ch.y_columns]
                    bc.categoryAxis.categoryNames = [sanitize_text(c) for c in ch_data.categories]
                    bc.categoryAxis.labels.fontSize = typo["chart_label_size_pt"]
                    bc.valueAxis.labels.fontSize = typo["chart_label_size_pt"]
                    bc.barLabelFormat = num_format
                    bc.barLabels.fontSize = typo["chart_label_size_pt"]
                    bc.barLabels.nudge = 5
                    for idx, _ in enumerate(ch.y_columns):
                        bc.bars[idx].fillColor = palette[idx % len(palette)]
                    ch_d.add(bc)
                elif ch.kind == ChartKind.LINE:
                    lc = HorizontalLineChart()
                    lc.x, lc.y, lc.width, lc.height = 40, 20, avail_width - 60, 130
                    lc.data = [ch_data.series[col] for col in ch.y_columns]
                    lc.categoryAxis.categoryNames = [sanitize_text(c) for c in ch_data.categories]
                    lc.categoryAxis.labels.fontSize = typo["chart_label_size_pt"]
                    lc.valueAxis.labels.fontSize = typo["chart_label_size_pt"]
                    lc.lineLabelFormat = num_format
                    lc.lineLabels.fontSize = typo["chart_label_size_pt"]
                    for idx, _ in enumerate(ch.y_columns):
                        lc.lines[idx].strokeColor = palette[idx % len(palette)]
                    ch_d.add(lc)
                elif ch.kind == ChartKind.PIE:
                    pie = Pie()
                    pie.x, pie.y, pie.width, pie.height = (avail_width - 130) / 2, 15, 130, 130
                    y_col = ch.y_columns[0]
                    vals = ch_data.series[y_col]
                    pie.data = vals
                    pie.labels = [
                        f"{sanitize_text(c)}: {format_value(v, num_format)}" for c, v in zip(ch_data.categories, vals)
                    ]
                    pie.slices.labelRadius = 1.05
                    pie.slices.fontSize = typo["chart_label_size_pt"]
                    for idx, _ in enumerate(vals):
                        pie.slices[idx].fillColor = palette[idx % len(palette)]
                    ch_d.add(pie)
                story.append(ch_d)
                story.append(Spacer(1, 8))

    doc.build(story)
    return buf.getvalue()
