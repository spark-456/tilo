"""tilo_render: PDF and PPTX deliverables from templates with data-bound charts (PRD 12.4, FR-CON-09).

Deterministic code only: no model calls, no network, no clock (services/render/CLAUDE.md).
"""

from .charts import ChartData
from .pdf import render_pdf
from .pptx import render_pptx
from .spec import (
    MAX_BLOCKS_PER_SECTION,
    MAX_BULLETS_PER_BLOCK,
    MAX_CHART_POINTS,
    MAX_ESTIMATED_SLIDES,
    MAX_PARAGRAPH_CHARS,
    MAX_REFERENCED_CHARTS,
    MAX_REFERENCED_TABLE_CELLS,
    MAX_SECTIONS,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_TOTAL_BLOCKS,
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
    "MAX_BLOCKS_PER_SECTION",
    "MAX_BULLETS_PER_BLOCK",
    "MAX_CHART_POINTS",
    "MAX_ESTIMATED_SLIDES",
    "MAX_PARAGRAPH_CHARS",
    "MAX_REFERENCED_CHARTS",
    "MAX_REFERENCED_TABLE_CELLS",
    "MAX_SECTIONS",
    "MAX_TABLE_COLUMNS",
    "MAX_TABLE_ROWS",
    "MAX_TOTAL_BLOCKS",
    "ParagraphBlock",
    "Section",
    "Table",
    "TableBlock",
    "render_pdf",
    "render_pptx",
]
