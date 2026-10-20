"""CSV files from the tables of a DeliverableSpec (DEMO-DELIVER): one real comma-separated file a spreadsheet opens.

A CSV holds one table: the file is the spec's first table, followed by the rows of every later table that has exactly
the same columns (a writer that split one list into parts); headings, paragraphs, charts and other tables are not part
of it. Numbers stay plain numbers (a computed column is its computed value: a CSV has no formulas), text is sanitised,
and a text cell a spreadsheet would read as a formula (it starts with =, +, -, @ or a tab) gets a leading apostrophe,
so a model-written cell never runs when the file is opened (CSV injection). UTF-8 with a byte-order mark so Excel reads
accents and symbols, CRLF line ends (RFC 4180). Deterministic code only: no model, no network, no clock.
"""

import csv
import io
from math import isfinite

from tilo_render.spec import DeliverableSpec
from tilo_render.text import sanitize_text

MAX_CSV_ROWS = 5000  # data rows across the joined tables
_FORMULA_START = ("=", "+", "-", "@", "\t")


def _cell(value: str | int | float) -> str:
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not isfinite(value):
            return ""
        return str(int(value)) if value.is_integer() and abs(value) < 2**53 else repr(value)
    text = sanitize_text(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def render_csv(spec: DeliverableSpec) -> bytes:
    """The spec's table as CSV bytes; ValueError when the spec has no table or too many rows for one file."""
    if not spec.tables:
        raise ValueError("A CSV file needs a table")
    first = spec.tables[0]
    rows = [row for table in spec.tables if table.columns == first.columns for row in table.rows]
    if len(rows) > MAX_CSV_ROWS:
        raise ValueError(f"At most {MAX_CSV_ROWS} rows in a CSV file")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([_cell(name) for name in first.columns])
    writer.writerows([_cell(value) for value in row] for row in rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
