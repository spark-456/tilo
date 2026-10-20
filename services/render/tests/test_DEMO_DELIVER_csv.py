"""DEMO-DELIVER: `tilo_render.csv_table.render_csv` makes one real CSV file from a DeliverableSpec's table."""

import csv
import io

import pytest
from tilo_render.csv_table import MAX_CSV_ROWS, render_csv
from tilo_render.spec import DeliverableSpec


def spec(*tables: dict) -> DeliverableSpec:
    return DeliverableSpec.model_validate({"title": "Prices", "date": "2026-10-20", "tables": list(tables)})


def rows_of(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


PRICES = {
    "id": "t1",
    "columns": ["Item", "Qty", "Unit cost"],
    "rows": [["Chairs, folding", 40, 3.5], ['Say "hi"', 8, 20.0]],
    "formulas": [{"column": "Cost", "expr": "[Qty] * [Unit cost]"}],
}


def test_DEMO_DELIVER_csv_is_utf8_with_a_bom_crlf_rows_quoted_and_numbers_plain() -> None:
    data = render_csv(spec(PRICES))
    assert data.startswith("\ufeff".encode()) and data.endswith(b"\r\n")
    assert rows_of(data) == [
        ["Item", "Qty", "Unit cost", "Cost"],
        ["Chairs, folding", "40", "3.5", "140"],
        ['Say "hi"', "8", "20", "160"],
    ]


def test_DEMO_DELIVER_csv_joins_tables_with_the_same_columns_and_leaves_others_out() -> None:
    more = {"id": "t2", "columns": ["Item", "Qty", "Unit cost"], "rows": [["Tables", 2, 50]]}
    other = {"id": "t3", "columns": ["Note"], "rows": [["not in the file"]]}
    data = render_csv(spec({**PRICES, "formulas": []}, more, other))
    assert [row[0] for row in rows_of(data)] == ["Item", "Chairs, folding", 'Say "hi"', "Tables"]
    assert b"not in the file" not in data


@pytest.mark.parametrize("text", ["=HYPERLINK(1)", "+1+2", "-3+4", "@SUM(1)", "\tTab"])
def test_DEMO_DELIVER_csv_text_a_spreadsheet_would_run_gets_an_apostrophe(text: str) -> None:
    table = {"id": "t1", "columns": [text, "Amount"], "rows": [[text, -5], ["plain", 1.25]]}
    rows = rows_of(render_csv(spec(table)))
    assert rows[0][0] == "'" + text and rows[1] == ["'" + text, "-5"] and rows[2] == ["plain", "1.25"]


def test_DEMO_DELIVER_csv_needs_a_table_and_fits_one_file() -> None:
    with pytest.raises(ValueError):
        render_csv(spec())
    big = {"id": "t1", "columns": ["n"], "rows": [[i] for i in range(500)]}
    tables = [{**big, "id": f"t{i}"} for i in range(MAX_CSV_ROWS // 500 + 1)]
    with pytest.raises(ValueError):
        render_csv(spec(*tables))
