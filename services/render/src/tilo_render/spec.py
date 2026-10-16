"""DeliverableSpec and safety validation for tilo-render (FR-CON-09; PRD 6.6, 12.4, 12.6)."""

import base64
import datetime
import io
import math
import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

MAX_SECTIONS = 60
MAX_TABLE_ROWS = 500
MAX_CHART_POINTS = 200
MAX_PARAGRAPH_CHARS = 20_000
MAX_TABLE_COLUMNS = 20
MAX_BULLETS_PER_BLOCK = 500
MAX_BLOCKS_PER_SECTION = 30
MAX_TOTAL_BLOCKS = 120
MAX_REFERENCED_TABLE_CELLS = 25_000
MAX_REFERENCED_CHARTS = 20
MAX_ESTIMATED_SLIDES = 250


class ParagraphBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["paragraph"] = "paragraph"
    text: str

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if len(value) > MAX_PARAGRAPH_CHARS:
            raise ValueError(f"At most {MAX_PARAGRAPH_CHARS} characters per paragraph allowed")
        return value


class BulletsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["bullets"] = "bullets"
    bullets: list[str]

    @field_validator("bullets")
    @classmethod
    def _validate_bullets(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Bullets block cannot be empty")
        if len(value) > MAX_BULLETS_PER_BLOCK:
            raise ValueError(f"At most {MAX_BULLETS_PER_BLOCK} bullets per block allowed")
        for item in value:
            if len(item) > MAX_PARAGRAPH_CHARS:
                raise ValueError(f"At most {MAX_PARAGRAPH_CHARS} characters per bullet allowed")
        return value


class TableBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["table"] = "table"
    table_id: str = Field(min_length=1)


class ChartBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["chart"] = "chart"
    chart_id: str = Field(min_length=1)


def slide_chunks(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.split("\n"):
        while len(line) > 22:
            split = line.rfind(" ", 0, 22)
            split = 22 if split <= 0 else split + 1
            lines.append(line[:split])
            line = line[split:]
        lines.append(line)
    return ["\n".join(lines[i : i + 12]) for i in range(0, len(lines), 12)]


class SlideBlock(BaseModel):
    """GEN-06: bounded slide design; image bytes only, never a path or URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["slide"] = "slide"
    layout: Literal["two_column", "image", "stat"]
    title: str = Field(min_length=1, max_length=120)
    left: str = Field(default="", max_length=MAX_PARAGRAPH_CHARS)
    right: str = Field(default="", max_length=MAX_PARAGRAPH_CHARS)
    notes: str = Field(default="", max_length=MAX_PARAGRAPH_CHARS)
    image_base64: str | None = Field(default=None, max_length=1_400_000)

    @model_validator(mode="after")
    def _image(self) -> "SlideBlock":
        if self.layout == "image" and not self.image_base64:
            raise ValueError("Image layout requires recorded image bytes")
        if self.layout == "image" and self.right:
            raise ValueError("Image captions belong in left; right must be empty")
        if self.image_base64:
            from PIL import Image

            try:
                raw = base64.b64decode(self.image_base64, validate=True)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in {"PNG", "JPEG"} or image.width * image.height > 4_000_000:
                        raise ValueError("Unsupported or oversized slide image")
                    image.verify()
            except Exception as exc:
                raise ValueError("Invalid slide image") from exc
        return self

    @property
    def pages(self) -> int:
        return max(len(slide_chunks(self.left)), len(slide_chunks(self.right)))


Block = Annotated[ParagraphBlock | BulletsBlock | TableBlock | ChartBlock | SlideBlock, Field(discriminator="type")]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    heading: str = Field(min_length=1)
    blocks: list[Block] = Field(default_factory=list)

    @field_validator("blocks")
    @classmethod
    def _validate_blocks_length(cls, value: list[Block]) -> list[Block]:
        if len(value) > MAX_BLOCKS_PER_SECTION:
            raise ValueError(f"At most {MAX_BLOCKS_PER_SECTION} blocks per section allowed")
        return value


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    columns: list[str]
    rows: list[list[StrictStr | StrictInt | StrictFloat]]

    @model_validator(mode="after")
    def _validate_table(self) -> "Table":
        if not self.columns or not self.rows:
            raise ValueError("Table cannot be empty")
        if len(self.columns) > MAX_TABLE_COLUMNS:
            raise ValueError(f"At most {MAX_TABLE_COLUMNS} columns per table allowed")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError(f"Duplicate column names in table {self.id}")
        if len(self.rows) > MAX_TABLE_ROWS:
            raise ValueError(f"At most {MAX_TABLE_ROWS} rows per table allowed")
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError(f"Row length mismatch in table {self.id}")
        return self


class ChartKind(StrEnum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"


class Chart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    kind: ChartKind
    table_id: str = Field(min_length=1)
    x: str = Field(min_length=1)
    y: str | list[str]
    title: str = Field(min_length=1)

    @property
    def y_columns(self) -> list[str]:
        return [self.y] if isinstance(self.y, str) else list(self.y)


def _coerce_finite_float(val: Any, col_name: str) -> float:
    if isinstance(val, bool) or not isinstance(val, int | float):
        raise ValueError(f"Non-numeric value in column {col_name}")
    if isinstance(val, int) and abs(val) > 2**53:
        raise ValueError(f"Integer too large for precise representation in column {col_name}")
    fval = float(val)
    if math.isnan(fval) or math.isinf(fval):
        raise ValueError(f"Non-numeric value in column {col_name}")
    return fval


class DeliverableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1)
    subtitle: str | None = None
    date: str = Field(min_length=1)
    tables: list[Table] = Field(default_factory=list)
    charts: list[Chart] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, value: str) -> str:
        try:
            datetime.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO date: {value}") from exc
        return value

    @field_validator("sections")
    @classmethod
    def _validate_sections_length(cls, value: list[Section]) -> list[Section]:
        if len(value) > MAX_SECTIONS:
            raise ValueError(f"At most {MAX_SECTIONS} sections allowed")
        return value

    @model_validator(mode="after")
    def _validate_cross_references(self) -> "DeliverableSpec":
        table_ids: dict[str, Table] = {}
        for tbl in self.tables:
            if tbl.id in table_ids:
                raise ValueError(f"Duplicate table_id: {tbl.id}")
            table_ids[tbl.id] = tbl

        chart_ids: set[str] = set()
        for ch in self.charts:
            if ch.id in chart_ids:
                raise ValueError(f"Duplicate chart_id: {ch.id}")
            chart_ids.add(ch.id)

        for chart in self.charts:
            if chart.table_id not in table_ids:
                raise ValueError(f"Unknown table_id: {chart.table_id}")
            table = table_ids[chart.table_id]

            if chart.x not in table.columns:
                raise ValueError(f"Column {chart.x} not found in table {chart.table_id}")

            y_cols = chart.y_columns
            if not y_cols:
                raise ValueError(f"Chart {chart.id} must specify at least one y column")
            if chart.kind == ChartKind.PIE and len(y_cols) > 1:
                raise ValueError("Pie chart can only have one y column")

            for y_col in y_cols:
                if y_col not in table.columns:
                    raise ValueError(f"Column {y_col} not found in table {chart.table_id}")

            if len(table.rows) * len(y_cols) > MAX_CHART_POINTS:
                raise ValueError(f"At most {MAX_CHART_POINTS} points per chart allowed")

            y_idxs = [table.columns.index(y_col) for y_col in y_cols]
            pie_total = 0.0
            for row in table.rows:
                for y_idx, y_col in zip(y_idxs, y_cols, strict=True):
                    fval = _coerce_finite_float(row[y_idx], y_col)
                    if chart.kind == ChartKind.PIE:
                        if fval < 0:
                            raise ValueError("Pie chart cannot have negative values")
                        pie_total += fval
            if chart.kind == ChartKind.PIE and pie_total == 0:
                raise ValueError("Pie chart total cannot be zero")

        total_blocks = sum(len(section.blocks) for section in self.sections)
        if total_blocks > MAX_TOTAL_BLOCKS:
            raise ValueError(f"At most {MAX_TOTAL_BLOCKS} blocks across all sections allowed")

        referenced_cells = 0
        referenced_charts = 0
        slide_count = 1 + len(self.sections)
        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, SlideBlock):
                    slide_count += block.pages
                elif isinstance(block, ParagraphBlock):
                    slide_count += max(1, math.ceil(len(block.text) / 1000))
                elif isinstance(block, BulletsBlock):
                    slide_count += max(1, math.ceil(len(block.bullets) / 8))
                elif isinstance(block, TableBlock):
                    if block.table_id not in table_ids:
                        raise ValueError(f"Unknown table_id: {block.table_id}")
                    tbl = table_ids[block.table_id]
                    referenced_cells += len(tbl.rows) * len(tbl.columns)
                    slide_count += max(1, math.ceil(len(tbl.rows) / 10))
                elif isinstance(block, ChartBlock):
                    if block.chart_id not in chart_ids:
                        raise ValueError(f"Unknown chart_id: {block.chart_id}")
                    referenced_charts += 1
                    slide_count += 1

        if referenced_cells > MAX_REFERENCED_TABLE_CELLS:
            raise ValueError(f"At most {MAX_REFERENCED_TABLE_CELLS} referenced table cells allowed")
        if referenced_charts > MAX_REFERENCED_CHARTS:
            raise ValueError(f"At most {MAX_REFERENCED_CHARTS} chart references allowed")
        if slide_count > MAX_ESTIMATED_SLIDES:
            raise ValueError(f"At most {MAX_ESTIMATED_SLIDES} estimated slides allowed")

        return self


# The HTTP service accepts untrusted requests. Keep its work envelope separate
# from the renderer's structural model, which also serves trusted local callers.
MAX_REQUEST_TABLE_CELLS = 1200
MAX_REQUEST_CHARTS = 4
MAX_TEXT_LINES = 40
MAX_TABLE_CELL_CHARS = 200
MAX_RENDER_LINES = 2000
MAX_RENDER_CHARS = 40_000


def _text_work(value: str, *, cell: bool = False) -> tuple[int, int]:
    lines = 1 + len(re.findall(r"\r\n|\r|\n", value))
    if lines > MAX_TEXT_LINES or (cell and len(value) > MAX_TABLE_CELL_CHARS):
        raise ValueError("Render text exceeds the line or cell-character budget")
    return lines, len(value)


class RequestDeliverableSpec(DeliverableSpec):
    """Bound repeated table/chart references and every rendered text surface."""

    @model_validator(mode="after")
    def _request_work_budget(self) -> "RequestDeliverableSpec":
        table_ids = {table.id: table for table in self.tables}
        chart_ids = {chart.id for chart in self.charts}
        for table in self.tables:
            for value in [*table.columns, *(v for row in table.rows for v in row)]:
                _text_work(str(value), cell=True)
        referenced_cells = 0
        referenced_charts = 0
        work_lines = work_chars = 0

        def charge(text: str, copies: int = 1) -> None:
            nonlocal work_lines, work_chars
            lines, chars = _text_work(text)
            work_lines += lines * copies
            work_chars += chars * copies
            if work_lines > MAX_RENDER_LINES or work_chars > MAX_RENDER_CHARS:
                raise ValueError("Render exceeds the total line or character budget")

        charge(self.title)
        charge(self.subtitle or "")
        for chart in self.charts:
            _text_work(chart.title)
        slide_count = 1 + len(self.sections)
        for section in self.sections:
            charge(section.heading)
            for block in section.blocks:
                if isinstance(block, SlideBlock):
                    slide_count += block.pages
                    charge(block.title, block.pages)
                    charge(block.left)
                    charge(block.right)
                    charge(block.notes, block.pages)
                elif isinstance(block, ParagraphBlock):
                    slide_count += max(1, math.ceil(len(block.text) / 1000))
                    charge(block.text)
                elif isinstance(block, BulletsBlock):
                    slide_count += max(1, math.ceil(len(block.bullets) / 8))
                    for bullet in block.bullets:
                        charge(bullet)
                elif isinstance(block, TableBlock):
                    if block.table_id not in table_ids:
                        raise ValueError(f"Unknown table_id: {block.table_id}")
                    tbl = table_ids[block.table_id]
                    referenced_cells += len(tbl.rows) * len(tbl.columns)
                    slide_count += max(1, math.ceil(len(tbl.rows) / 10))
                    for column in tbl.columns:
                        charge(column, 1 + math.ceil(len(tbl.rows) / 10))
                    for row in tbl.rows:
                        for value in row:
                            charge(str(value))
                elif isinstance(block, ChartBlock):
                    if block.chart_id not in chart_ids:
                        raise ValueError(f"Unknown chart_id: {block.chart_id}")
                    referenced_charts += 1
                    slide_count += 1
                    chart = next(c for c in self.charts if c.id == block.chart_id)
                    charge(chart.title)
                    tbl = table_ids[chart.table_id]
                    for row in tbl.rows:
                        for value in row:
                            charge(str(value))

        if referenced_cells > MAX_REQUEST_TABLE_CELLS:
            raise ValueError(f"At most {MAX_REQUEST_TABLE_CELLS} referenced table cells allowed")
        if referenced_charts > MAX_REQUEST_CHARTS:
            raise ValueError(f"At most {MAX_REQUEST_CHARTS} chart references allowed")
        if slide_count > MAX_ESTIMATED_SLIDES:
            raise ValueError(f"At most {MAX_ESTIMATED_SLIDES} estimated slides allowed")

        return self
