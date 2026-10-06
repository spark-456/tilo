"""Data-bound ChartData extracted deterministically from DeliverableSpec tables (FR-CON-09)."""

from pydantic import BaseModel, ConfigDict

from tilo_render.spec import DeliverableSpec


class ChartData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    categories: list[str]
    series: dict[str, list[float]]

    @classmethod
    def from_spec(cls, spec: DeliverableSpec, chart_id: str) -> "ChartData":
        chart = next((c for c in spec.charts if c.id == chart_id), None)
        if chart is None:
            raise ValueError(f"Unknown chart_id: {chart_id}")
        table = next(t for t in spec.tables if t.id == chart.table_id)

        x_idx = table.columns.index(chart.x)
        y_cols = chart.y_columns
        y_idxs = [table.columns.index(y_col) for y_col in y_cols]

        categories = [str(row[x_idx]) for row in table.rows]
        series = {y_col: [float(row[y_idx]) for row in table.rows] for y_col, y_idx in zip(y_cols, y_idxs, strict=True)}
        return cls(categories=categories, series=series)
