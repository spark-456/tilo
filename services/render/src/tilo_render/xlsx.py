"""Excel workbooks from the tables of a DeliverableSpec (DOCS-OUT A4, MIT `openpyxl`).

Each table becomes a sheet: bold header row, frozen and filtered, typed numbers and ISO dates, column widths from the
content, and a totals row of plain same-sheet `SUM` formulas under the numeric columns. Everything a model wrote is
data: a string is always stored as a string (never a formula, link or macro), and the workbook has no external parts.
Total cells are capped so the file stays small and can be screened.
"""

import io
import re
from datetime import UTC, date, datetime
from math import isfinite
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from tilo_render.spec import BulletsBlock, DeliverableSpec, ParagraphBlock, Table, TableBlock
from tilo_render.text import sanitize_text

MAX_XLSX_CELLS = 7000  # table cells (header and totals included) plus report lines, across all sheets
MAX_CELL_CHARS = 32_000  # Excel's own limit is 32,767
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NOT_A_QUANTITY = re.compile(r"\b(year|id|rank|code|zip|phone|index|no)\b|#", re.IGNORECASE)
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_HEADER_FILL = PatternFill("solid", start_color="E8EDF3", end_color="E8EDF3")


def text_value(value: Any) -> str:
    return sanitize_text(str(value))[:MAX_CELL_CHARS]


def put(sheet: Worksheet, row: int, column: int, value: Any, *, bold: bool = False) -> None:
    """One cell: numbers stay numbers, ISO dates become dates, every other string is stored as a string."""
    cell = sheet.cell(row=row, column=column)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        value = str(value)
    if isinstance(value, (int, float)) and isfinite(value):
        cell.value = value
    else:
        plain = text_value(value)
        if _ISO_DATE.fullmatch(plain):
            try:
                cell.value = date.fromisoformat(plain)
                cell.number_format = "yyyy-mm-dd"
            except ValueError:
                cell.value = plain
        else:
            cell.value = plain
            cell.data_type = "s"  # a leading "=", "+", "-" or "@" is text here, never a formula
    if bold:
        cell.font = Font(bold=True)


def _sheet_name(base: str, used: set[str]) -> str:
    name = _BAD_SHEET_CHARS.sub(" ", sanitize_text(base)).replace("\n", " ").strip().strip("'").strip() or "Sheet"
    candidate, n = name[:31], 1
    while candidate.lower() in used:
        n += 1
        suffix = f" {n}"
        candidate = name[: 31 - len(suffix)].rstrip().strip("'") + suffix
    used.add(candidate.lower())
    return candidate


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _table_sheet(sheet: Worksheet, table: Table) -> None:
    for column, name in enumerate(table.columns, 1):
        put(sheet, 1, column, name, bold=True)
        sheet.cell(row=1, column=column).fill = _HEADER_FILL
    for r, row in enumerate(table.rows, 2):
        for column, value in enumerate(row, 1):
            put(sheet, r, column, value)
    last = len(table.rows) + 1
    summed = [
        c
        for c, name in enumerate(table.columns, 1)
        if all(_is_number(row[c - 1]) for row in table.rows) and not _NOT_A_QUANTITY.search(name)
    ]
    if summed:
        total = last + 1
        if 1 not in summed:
            put(sheet, total, 1, "Total", bold=True)
        for c in summed:
            letter = get_column_letter(c)
            cell = sheet.cell(row=total, column=c, value=f"=SUM({letter}2:{letter}{last})")
            cell.font = Font(bold=True)  # a formula over this sheet's own range, never model text
    for c, name in enumerate(table.columns, 1):
        longest = max([len(text_value(name)), *(len(text_value(row[c - 1])) for row in table.rows)])
        sheet.column_dimensions[get_column_letter(c)].width = min(max(10, longest + 2), 60)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(table.columns))}{last}"


def _cell_count(spec: DeliverableSpec) -> int:
    tables = sum((len(t.rows) + 2) * len(t.columns) for t in spec.tables)
    lines = sum(len(b.bullets) if isinstance(b, BulletsBlock) else 1 for s in spec.sections for b in s.blocks)
    return tables + lines + 3 + len(spec.sections)


def _report_sheet(sheet: Worksheet, spec: DeliverableSpec) -> None:
    sheet.column_dimensions["A"].width = 100
    wrap = Alignment(wrap_text=True, vertical="top")
    row = 1
    for text, bold in ((spec.title, True), (spec.subtitle or "", False), (spec.date, False)):
        if text:
            put(sheet, row, 1, text, bold=bold)
            sheet.cell(row=row, column=1).alignment = wrap
            row += 1
    for section in spec.sections:
        row += 1
        put(sheet, row, 1, section.heading, bold=True)
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                items = [block.text]
            elif isinstance(block, BulletsBlock):
                items = [f"- {item}" for item in block.bullets]
            else:
                continue
            for item in items:
                row += 1
                put(sheet, row, 1, item)
                sheet.cell(row=row, column=1).alignment = wrap


def render_xlsx(spec: DeliverableSpec) -> bytes:
    # Revalidate objects constructed without validation before creating any workbook parts.
    spec = DeliverableSpec.model_validate(spec.model_dump())
    if _cell_count(spec) > MAX_XLSX_CELLS:
        raise ValueError("too many cells for one workbook")
    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    has_text = any(isinstance(b, ParagraphBlock | BulletsBlock) for s in spec.sections for b in s.blocks)
    if has_text or not spec.tables:
        _report_sheet(workbook.create_sheet(_sheet_name("Summary" if spec.tables else "Report", used)), spec)
    headings: dict[str, str] = {}  # the heading of the section that first shows each table
    for section in spec.sections:
        for block in section.blocks:
            if isinstance(block, TableBlock):
                headings.setdefault(block.table_id, section.heading)
    for table in spec.tables:
        _table_sheet(workbook.create_sheet(_sheet_name(headings.get(table.id, table.id), used)), table)
    moment = datetime.fromisoformat(spec.date).replace(tzinfo=UTC).replace(tzinfo=None)
    workbook.properties.creator = "Tilo"
    workbook.properties.title = text_value(spec.title)[:200]
    workbook.properties.created = workbook.properties.modified = moment
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
