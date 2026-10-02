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
    return next((p for p in [cur, *cur.parents] if (p / "design" / "tokens.json").exists()), Path.cwd())


def _resolve_color(role: str, tokens: dict[str, Any]) -> colors.HexColor:
    node: Any = tokens.get("color", {})
    for part in role.split("."):
        if not isinstance(node, dict) or part not in node:
            return colors.HexColor("#5A3FE0")
        node = node[part]
    val = node["value"] if isinstance(node, dict) and "value" in node else str(node)
    return colors.HexColor(val)


def sanitize_text(text: str) -> str:
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        c
        for c in norm
        if c in "\t\n"
        or (
            32 <= ord(c) != 127
            and not (0x80 <= ord(c) <= 0x9F)
            and not (0xD800 <= ord(c) <= 0xDFFF)
            and ord(c) not in (0xFFFE, 0xFFFF)
        )
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
    palette = [_resolve_color(r, tokens) for r in colors_cfg.get("chart_palette", ["brand.primary"])]
    typo = {k: float(v) for k, v in tmpl.get("typography", {}).items()}
    num_format = str(tmpl.get("format", {}).get("number_format", "%g"))
    page_cfg = tmpl.get("page", {})

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=float(page_cfg.get("margin_left_pt", 54)),
        rightMargin=float(page_cfg.get("margin_right_pt", 54)),
        topMargin=float(page_cfg.get("margin_top_pt", 54)),
        bottomMargin=float(page_cfg.get("margin_bottom_pt", 54)),
    )
    aw = doc.width

    def _ps(name: str, font: str, sz: float, col: colors.HexColor, **kw: Any) -> ParagraphStyle:
        kw.setdefault("leading", sz * 1.25)
        return ParagraphStyle(name, fontName=font, fontSize=sz, textColor=col, **kw)

    title_s = _ps("T", "Helvetica-Bold", typo["title_size_pt"], col_map["title"], spaceAfter=6)
    sub_s = _ps("S", "Helvetica", typo["subtitle_size_pt"], col_map["subtitle"], spaceAfter=4)
    date_s = _ps("D", "Helvetica", typo["date_size_pt"], col_map["date"], spaceAfter=14)
    heading_s = _ps("H", "Helvetica-Bold", typo["heading_size_pt"], col_map["heading"], spaceBefore=10, spaceAfter=6)
    body_s = _ps(
        "B", "Helvetica", typo["body_size_pt"], col_map["body"], leading=typo["body_size_pt"] * 1.35, spaceAfter=6
    )
    bullet_s = _ps(
        "BL",
        "Helvetica",
        typo["bullet_size_pt"],
        col_map["bullet"],
        leading=typo["bullet_size_pt"] * 1.35,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=3,
    )
    th_s = _ps("TH", "Helvetica-Bold", typo["table_header_size_pt"], col_map["table_header_fg"])
    td_s = _ps("TD", "Helvetica", typo["table_body_size_pt"], col_map["table_row_fg"])

    story: list[Any] = [Paragraph(escape_text(spec.title), title_s)]
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
                d_rows = [[Paragraph(escape_text(format_value(c, num_format)), td_s) for c in row] for row in tbl.rows]
                col_w = aw / len(tbl.columns)
                table_flowable = PlTable([h_cells] + d_rows, colWidths=[col_w] * len(tbl.columns), repeatRows=1)
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
                story.extend([table_flowable, Spacer(1, 8)])
            elif isinstance(block, ChartBlock):
                ch = chart_lookup[block.chart_id]
                ch_data = ChartData.from_spec(spec, ch.id)
                ch_d = Drawing(aw, 180)
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
                if ch.kind in (ChartKind.BAR, ChartKind.LINE):
                    chart_obj = VerticalBarChart() if ch.kind == ChartKind.BAR else HorizontalLineChart()
                    chart_obj.x, chart_obj.y, chart_obj.width, chart_obj.height = 40, 20, aw - 60, 130
                    chart_obj.data = [ch_data.series[col] for col in ch.y_columns]
                    chart_obj.categoryAxis.categoryNames = [sanitize_text(str(c)) for c in ch_data.categories]
                    chart_obj.categoryAxis.labels.fontSize = typo["chart_label_size_pt"]
                    chart_obj.valueAxis.labels.fontSize = typo["chart_label_size_pt"]
                    if ch.kind == ChartKind.BAR:
                        chart_obj.barLabelFormat = num_format
                        chart_obj.barLabels.fontSize, chart_obj.barLabels.nudge = typo["chart_label_size_pt"], 5
                        for idx, _ in enumerate(ch.y_columns):
                            chart_obj.bars[idx].fillColor = palette[idx % len(palette)]
                    else:
                        chart_obj.lineLabelFormat = num_format
                        chart_obj.lineLabels.fontSize = typo["chart_label_size_pt"]
                        for idx, _ in enumerate(ch.y_columns):
                            chart_obj.lines[idx].strokeColor = palette[idx % len(palette)]
                    ch_d.add(chart_obj)
                elif ch.kind == ChartKind.PIE:
                    pie = Pie()
                    pie.x, pie.y, pie.width, pie.height = (aw - 130) / 2, 15, 130, 130
                    vals = ch_data.series[ch.y_columns[0]]
                    pie.data = vals
                    pie.labels = [
                        f"{sanitize_text(str(c))}: {format_value(v, num_format)}"
                        for c, v in zip(ch_data.categories, vals, strict=True)
                    ]
                    pie.slices.labelRadius, pie.slices.fontSize = 1.05, typo["chart_label_size_pt"]
                    for idx, _ in enumerate(vals):
                        pie.slices[idx].fillColor = palette[idx % len(palette)]
                    ch_d.add(pie)
                story.extend([ch_d, Spacer(1, 8)])

    doc.build(story)
    return buf.getvalue()
