"""tilo_render: PDF and PPTX deliverables from templates with data-bound charts (PRD 12.4, FR-CON-09).

Deterministic code only: no model calls, no network, no clock (services/render/CLAUDE.md).
"""

from .charts import ChartData
from .pptx import render_pptx
from .spec import (
    MAX_CHART_POINTS,
    MAX_PARAGRAPH_CHARS,
    MAX_SECTIONS,
    MAX_TABLE_ROWS,
    Block,
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

__all__ = [
    "Block",
    "BulletsBlock",
    "Chart",
    "ChartBlock",
    "ChartData",
    "ChartKind",
    "DeliverableSpec",
    "MAX_CHART_POINTS",
    "MAX_PARAGRAPH_CHARS",
    "MAX_SECTIONS",
    "MAX_TABLE_ROWS",
    "ParagraphBlock",
    "Section",
    "Table",
    "TableBlock",
    "render_pptx",
]
