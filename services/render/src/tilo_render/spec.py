"""DeliverableSpec and safety validation for tilo-render (FR-CON-09; PRD 6.6, 12.4, 12.6)."""

import datetime
import math
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_SECTIONS = 60
MAX_TABLE_ROWS = 500
MAX_CHART_POINTS = 200
MAX_PARAGRAPH_CHARS = 20_000


class ParagraphBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if len(value) > MAX_PARAGRAPH_CHARS:
            raise ValueError(f"At most {MAX_PARAGRAPH_CHARS} characters per paragraph allowed")
        return value


class BulletsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bullets: list[str]

    @field_validator("bullets")
    @classmethod
    def _validate_bullets(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Bullets block cannot be empty")
        for item in value:
            if len(item) > MAX_PARAGRAPH_CHARS:
                raise ValueError(f"At most {MAX_PARAGRAPH_CHARS} characters per bullet allowed")
        return value


class TableBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    table_id: str = Field(min_length=1)


class ChartBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    chart_id: str = Field(min_length=1)


Block = ParagraphBlock | BulletsBlock | TableBlock | ChartBlock


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    heading: str = Field(min_length=1)
    blocks: list[Block] = Field(default_factory=list)


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    columns: list[str]
    rows: list[list[Any]]

    @model_validator(mode="after")
    def _validate_table(self) -> "Table":
        if not self.columns or not self.rows:
            raise ValueError("Table cannot be empty")
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
            for row in table.rows:
                for y_idx, y_col in zip(y_idxs, y_cols, strict=True):
                    fval = _coerce_finite_float(row[y_idx], y_col)
                    if chart.kind == ChartKind.PIE and fval < 0:
                        raise ValueError("Pie chart cannot have negative values")

        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, TableBlock) and block.table_id not in table_ids:
                    raise ValueError(f"Unknown table_id: {block.table_id}")
                if isinstance(block, ChartBlock) and block.chart_id not in chart_ids:
                    raise ValueError(f"Unknown chart_id: {block.chart_id}")

        return self
