"""Acceptance tests for DeliverableSpec and ChartData (FR-CON-09; AGR-01)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tilo_render.charts import ChartData
from tilo_render.spec import (
    Chart,
    ChartBlock,
    ChartKind,
    DeliverableSpec,
    ParagraphBlock,
    Section,
    Table,
    TableBlock,
)


def test_FR_CON_09_spec_rejects_unknown_ids_columns_and_non_numeric_values() -> None:
    table = Table(id="table1", columns=["label", "value"], rows=[["A", 10], ["B", 20]])

    # Unknown table ID in chart
    with pytest.raises(ValueError, match="Unknown table_id: table2"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table],
            charts=[Chart(id="chart1", kind=ChartKind.BAR, table_id="table2", x="label", y=["value"], title="Chart")],
            sections=[],
        )

    # Unknown table ID in section TableBlock
    with pytest.raises(ValueError, match="Unknown table_id: table2"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table],
            charts=[],
            sections=[Section(heading="Sec", blocks=[TableBlock(table_id="table2")])],
        )

    # Unknown chart ID in section ChartBlock
    with pytest.raises(ValueError, match="Unknown chart_id: chart2"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table],
            charts=[Chart(id="chart1", kind=ChartKind.BAR, table_id="table1", x="label", y=["value"], title="Chart")],
            sections=[Section(heading="Sec", blocks=[ChartBlock(chart_id="chart2")])],
        )

    # Unknown column in chart (x)
    with pytest.raises(ValueError, match="Column missing_col not found in table table1"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table],
            charts=[
                Chart(id="chart1", kind=ChartKind.BAR, table_id="table1", x="missing_col", y=["value"], title="Chart")
            ],
            sections=[],
        )

    # Unknown column in chart (y)
    with pytest.raises(ValueError, match="Column missing_y not found in table table1"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table],
            charts=[
                Chart(id="chart1", kind=ChartKind.BAR, table_id="table1", x="label", y=["missing_y"], title="Chart")
            ],
            sections=[],
        )

    # Non-numeric values in table referenced by chart (string, bool, None, NaN)
    for bad_val in ("not_a_number", True, None, float("nan"), float("inf")):
        table_bad = Table(id="table1", columns=["label", "value"], rows=[["A", bad_val], ["B", 20]])
        with pytest.raises(ValueError, match="Non-numeric value in column value"):
            DeliverableSpec(
                title="Title",
                date="2026-10-01",
                tables=[table_bad],
                charts=[
                    Chart(id="chart1", kind=ChartKind.BAR, table_id="table1", x="label", y=["value"], title="Chart")
                ],
                sections=[],
            )

    # Empty table
    with pytest.raises(ValueError, match="Table cannot be empty"):
        Table(id="table1", columns=[], rows=[])
    with pytest.raises(ValueError, match="Table cannot be empty"):
        Table(id="table1", columns=["label", "value"], rows=[])

    # Pie chart with multiple y columns
    table_two_y = Table(id="table1", columns=["label", "value", "other"], rows=[["A", 10, 5], ["B", 20, 15]])
    with pytest.raises(ValueError, match="Pie chart can only have one y column"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table_two_y],
            charts=[
                Chart(
                    id="chart1",
                    kind=ChartKind.PIE,
                    table_id="table1",
                    x="label",
                    y=["value", "other"],
                    title="Chart",
                )
            ],
            sections=[],
        )

    # Pie chart with negative y value
    table_neg = Table(id="table1", columns=["label", "value"], rows=[["A", -10], ["B", 20]])
    with pytest.raises(ValueError, match="Pie chart cannot have negative values"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table_neg],
            charts=[Chart(id="chart1", kind=ChartKind.PIE, table_id="table1", x="label", y=["value"], title="Chart")],
            sections=[],
        )


def test_FR_CON_09_spec_enforces_the_safety_limits() -> None:
    # At most 60 sections
    with pytest.raises(ValueError, match="At most 60 sections allowed"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[],
            charts=[],
            sections=[Section(heading=f"Sec {i}", blocks=[]) for i in range(61)],
        )

    # At most 500 rows per table
    with pytest.raises(ValueError, match="At most 500 rows per table allowed"):
        Table(id="t_big", columns=["x", "y"], rows=[[f"r{i}", i] for i in range(501)])

    # At most 200 points per chart
    table_201 = Table(id="t_201", columns=["x", "y"], rows=[[f"r{i}", i] for i in range(201)])
    with pytest.raises(ValueError, match="At most 200 points per chart allowed"):
        DeliverableSpec(
            title="Title",
            date="2026-10-01",
            tables=[table_201],
            charts=[Chart(id="c1", kind=ChartKind.LINE, table_id="t_201", x="x", y=["y"], title="Too many points")],
            sections=[],
        )

    # At most 20,000 characters per paragraph
    with pytest.raises(ValueError, match="At most 20000 characters per paragraph allowed"):
        ParagraphBlock(text="a" * 20_001)


@given(
    st.lists(
        st.tuples(
            st.text(min_size=1, max_size=16),
            st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
            st.integers(min_value=-1000, max_value=1000),
        ),
        min_size=1,
        max_size=25,
    )
)
def test_FR_CON_09_chart_data_equals_the_source_table(
    source_rows: list[tuple[str, float, int]],
) -> None:
    rows = [[label, val_a, val_b] for label, val_a, val_b in source_rows]
    table = Table(id="table1", columns=["label", "series_a", "series_b"], rows=rows)
    spec = DeliverableSpec(
        title="Title",
        date="2026-10-01",
        tables=[table],
        charts=[
            Chart(
                id="chart1",
                kind=ChartKind.BAR,
                table_id="table1",
                x="label",
                y=["series_a", "series_b"],
                title="Chart",
            )
        ],
        sections=[],
    )

    chart_data = ChartData.from_spec(spec, "chart1")
    assert chart_data.categories == [row[0] for row in rows]
    assert chart_data.series["series_a"] == [float(row[1]) for row in rows]
    assert chart_data.series["series_b"] == [float(row[2]) for row in rows]


def test_FR_CON_09_chart_data_is_deterministic() -> None:
    table = Table(id="table1", columns=["label", "value1", "value2"], rows=[["A", 10, 15], ["B", 20, 25]])
    spec = DeliverableSpec(
        title="Title",
        date="2026-10-01",
        tables=[table],
        charts=[
            Chart(
                id="chart1",
                kind=ChartKind.BAR,
                table_id="table1",
                x="label",
                y=["value1", "value2"],
                title="Chart",
            )
        ],
        sections=[],
    )

    data1 = ChartData.from_spec(spec, "chart1")
    data2 = ChartData.from_spec(spec, "chart1")

    assert data1 == data2
    assert data1.categories == ["A", "B"]
    assert data1.series == {"value1": [10.0, 20.0], "value2": [15.0, 25.0]}
