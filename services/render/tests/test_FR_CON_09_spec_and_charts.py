"""Acceptance tests for DeliverableSpec and ChartData (FR-CON-09; AGR-01)."""

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tilo_render.charts import ChartData
from tilo_render.spec import Chart, ChartBlock, ChartKind, DeliverableSpec, ParagraphBlock, Section, Table, TableBlock


def make_spec(**kwargs: Any) -> DeliverableSpec:
    defaults = {"title": "Title", "date": "2026-10-01", "tables": [], "charts": [], "sections": []}
    return DeliverableSpec(**(defaults | kwargs))


def test_FR_CON_09_spec_rejects_unknown_ids_columns_and_non_numeric_values() -> None:
    table = Table(id="table1", columns=["label", "value"], rows=[["A", 10], ["B", 20]])
    chart = Chart(id="c1", kind=ChartKind.BAR, table_id="t2", x="label", y=["value"], title="C")

    with pytest.raises(ValueError, match="Unknown table_id: t2"):
        make_spec(tables=[table], charts=[chart])

    with pytest.raises(ValueError, match="Unknown table_id: t2"):
        make_spec(tables=[table], sections=[Section(heading="S", blocks=[TableBlock(table_id="t2")])])

    with pytest.raises(ValueError, match="Unknown chart_id: c2"):
        c1 = Chart(id="c1", kind=ChartKind.BAR, table_id="table1", x="label", y=["value"], title="C")
        make_spec(tables=[table], charts=[c1], sections=[Section(heading="S", blocks=[ChartBlock(chart_id="c2")])])

    with pytest.raises(ValueError, match="Column miss not found in table table1"):
        c1 = Chart(id="c1", kind=ChartKind.BAR, table_id="table1", x="miss", y=["value"], title="C")
        make_spec(tables=[table], charts=[c1])

    with pytest.raises(ValueError, match="Column miss not found in table table1"):
        c1 = Chart(id="c1", kind=ChartKind.BAR, table_id="table1", x="label", y=["miss"], title="C")
        make_spec(tables=[table], charts=[c1])

    for bad_val in ("not_a_number", float("nan"), float("inf")):
        with pytest.raises(ValueError, match="Non-numeric value in column value"):
            t_bad = Table(id="table1", columns=["label", "value"], rows=[["A", bad_val], ["B", 20]])
            c1 = Chart(id="c1", kind=ChartKind.BAR, table_id="table1", x="label", y=["value"], title="C")
            make_spec(tables=[t_bad], charts=[c1])

    for raw_val in (True, None):
        with pytest.raises(ValueError):
            Table(id="table1", columns=["label", "value"], rows=[["A", raw_val]])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="Table cannot be empty"):
        Table(id="table1", columns=[], rows=[])
    with pytest.raises(ValueError, match="Table cannot be empty"):
        Table(id="table1", columns=["label", "value"], rows=[])

    t_two = Table(id="table1", columns=["l", "v", "o"], rows=[["A", 10, 5], ["B", 20, 15]])
    with pytest.raises(ValueError, match="Pie chart can only have one y column"):
        c1 = Chart(id="c1", kind=ChartKind.PIE, table_id="table1", x="l", y=["v", "o"], title="C")
        make_spec(tables=[t_two], charts=[c1])

    t_neg = Table(id="table1", columns=["l", "v"], rows=[["A", -10], ["B", 20]])
    with pytest.raises(ValueError, match="Pie chart cannot have negative values"):
        c1 = Chart(id="c1", kind=ChartKind.PIE, table_id="table1", x="l", y=["v"], title="C")
        make_spec(tables=[t_neg], charts=[c1])

    t_zero = Table(id="table1", columns=["l", "v"], rows=[["A", 0], ["B", 0]])
    with pytest.raises(ValueError, match="Pie chart total cannot be zero"):
        c1 = Chart(id="c1", kind=ChartKind.PIE, table_id="table1", x="l", y=["v"], title="C")
        make_spec(tables=[t_zero], charts=[c1])

    t_big = Table(id="table1", columns=["l", "v"], rows=[["A", 10**400]])
    with pytest.raises(ValueError, match="Integer too large for precise representation in column v"):
        c1 = Chart(id="c1", kind=ChartKind.BAR, table_id="table1", x="l", y=["v"], title="C")
        make_spec(tables=[t_big], charts=[c1])


def test_FR_CON_09_spec_enforces_the_safety_limits() -> None:
    with pytest.raises(ValueError, match="At most 60 sections allowed"):
        make_spec(sections=[Section(heading="S", blocks=[]) for _ in range(61)])

    with pytest.raises(ValueError, match="At most 500 rows per table allowed"):
        Table(id="t", columns=["x", "y"], rows=[[f"r{i}", i] for i in range(501)])

    t_201 = Table(id="t", columns=["x", "y"], rows=[[f"r{i}", i] for i in range(201)])
    with pytest.raises(ValueError, match="At most 200 points per chart allowed"):
        c1 = Chart(id="c1", kind=ChartKind.LINE, table_id="t", x="x", y=["y"], title="C")
        make_spec(tables=[t_201], charts=[c1])

    with pytest.raises(ValueError, match="At most 20000 characters per paragraph allowed"):
        ParagraphBlock(text="a" * 20_001)


@given(
    st.lists(
        st.tuples(
            st.text(min_size=1, max_size=16),
            st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
            st.integers(min_value=-9007199254740992, max_value=9007199254740992),
        ),
        min_size=1,
        max_size=25,
    )
)
def test_FR_CON_09_chart_data_equals_the_source_table(source_rows: list[tuple[str, float, int]]) -> None:
    rows: list[list[str | int | float]] = [[label, val_a, val_b] for label, val_a, val_b in source_rows]
    table = Table(id="table1", columns=["label", "series_a", "series_b"], rows=rows)
    c1 = Chart(id="c1", kind=ChartKind.BAR, table_id="table1", x="label", y=["series_a", "series_b"], title="C")
    spec = make_spec(tables=[table], charts=[c1])

    chart_data = ChartData.from_spec(spec, "c1")
    assert chart_data.categories == [label for label, _, _ in source_rows]
    assert chart_data.series["series_a"] == [float(val_a) for _, val_a, _ in source_rows]
    assert chart_data.series["series_b"] == [float(val_b) for _, _, val_b in source_rows]


def test_FR_CON_09_chart_data_is_deterministic() -> None:
    table = Table(id="table1", columns=["label", "value1", "value2"], rows=[["A", 10, 15], ["B", 20, 25]])
    c1 = Chart(id="c1", kind=ChartKind.BAR, table_id="table1", x="label", y=["value1", "value2"], title="C")
    spec = make_spec(tables=[table], charts=[c1])

    data1 = ChartData.from_spec(spec, "c1")
    data2 = ChartData.from_spec(spec, "c1")

    assert data1 == data2
    assert data1.categories == ["A", "B"]
    assert data1.series == {"value1": [10.0, 20.0], "value2": [15.0, 25.0]}
