"""tilo_render: PDF and PPTX deliverables from templates with data-bound charts (PRD 12.4, FR-CON-09).

Deterministic code only: no model calls, no network, no clock (services/render/CLAUDE.md).
"""

import importlib
from typing import TYPE_CHECKING, Any

from .charts import ChartData
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

if TYPE_CHECKING:
    from .pdf import render_pdf
    from .pptx import render_pptx

_RENDERERS = {"render_pdf": ".pdf", "render_pptx": ".pptx"}


def __getattr__(name: str) -> Any:
    """`render_pdf` and `render_pptx` import on first use: reportlab and python-pptx take seconds to load, and a caller
    that only needs `tilo_render.spec` (tilo-api, at boot) must not pay for them."""
    module = _RENDERERS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value


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
