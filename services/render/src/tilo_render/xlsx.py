"""Excel workbooks from the tables of a DeliverableSpec (DOCS-OUT A4, MIT `openpyxl`).

Each table becomes a sheet: bold header row, frozen and filtered, typed numbers and ISO dates, column widths from the
content, and a totals row of plain same-sheet `SUM` formulas under the numeric columns. Everything a model wrote is
data: a string is always stored as a string (never a formula, link or macro), and the workbook has no external parts.
Total cells are capped so the file stays small and can be screened.
"""

import io
import re
import zipfile
from collections.abc import Sequence
from datetime import UTC, date, datetime
from math import isfinite
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, field_validator

from tilo_render.spec import BulletsBlock, DeliverableSpec, ParagraphBlock, Table, TableBlock
from tilo_render.text import sanitize_text

MAX_XLSX_CELLS = 7000  # table cells (header and totals included) plus report lines, across all sheets
MAX_CELL_CHARS = 32_000  # Excel's own limit is 32,767
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NOT_A_QUANTITY = re.compile(r"\b(year|id|rank|code|zip|phone|index|no)\b|#", re.IGNORECASE)
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
MAX_FILL_CELLS = 2000  # cells one writer reply may fill in a template
MAX_FILL_TEXT = 2000
MAX_TEMPLATE_BYTES = 8 * 1024 * 1024
MAX_TEMPLATE_EXPANDED = 32 * 1024 * 1024
_ADDRESS = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,4})")
_ACTIVE_PARTS = ("externallink", "vbaproject", "activex", "embeddings/", "oleobject")
_HEADER_FILL = PatternFill("solid", start_color="E8EDF3", end_color="E8EDF3")


def text_value(value: Any) -> str:
    return sanitize_text(str(value))[:MAX_CELL_CHARS]


def store(cell: Any, value: Any) -> None:
    """One cell: numbers stay numbers, ISO dates become dates, every other string is stored as a string."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        value = str(value)
    if isinstance(value, (int, float)) and isfinite(value):
        cell.value = value
        return
    plain = text_value(value)
    if _ISO_DATE.fullmatch(plain):
        try:
            cell.value = date.fromisoformat(plain)
            if cell.number_format == "General":  # a template's own date format wins
                cell.number_format = "yyyy-mm-dd"
            return
        except ValueError:
            pass
    cell.value = plain
    cell.data_type = "s"  # a leading "=", "+", "-" or "@" is text here, never a formula


def put(sheet: Worksheet, row: int, column: int, value: Any, *, bold: bool = False) -> None:
    cell = sheet.cell(row=row, column=column)
    store(cell, value)
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


class FillCell(BaseModel):
    """One value the writer chose for one cell of the user's template. Data only: never a formula."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    sheet: str = Field(min_length=1, max_length=31)
    cell: str
    value: StrictStr | StrictInt | StrictFloat

    @field_validator("cell")
    @classmethod
    def _plain_address(cls, value: str) -> str:
        found = _ADDRESS.fullmatch(value)
        if found is None or column_index_from_string(found.group(1)) > 16384:
            raise ValueError("a cell is one plain address such as B7")
        return value

    @field_validator("value")
    @classmethod
    def _bounded(cls, value: str | int | float) -> str | int | float:
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("a number must be finite")
        if isinstance(value, str) and len(value) > MAX_FILL_TEXT:
            raise ValueError("text is too long")
        return value


def _open_template(data: bytes) -> Workbook:
    """The template as a workbook, or ValueError: bounded, with no macros, embedded objects or external links."""
    if not isinstance(data, bytes) or not 4 < len(data) <= MAX_TEMPLATE_BYTES:
        raise ValueError("the template is not a bounded workbook")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            infos = package.infolist()
            names = [info.filename.lower() for info in infos]
            if len(infos) > 512 or sum(info.file_size for info in infos) > MAX_TEMPLATE_EXPANDED:
                raise ValueError("the template is too large")
            if any(marker in name for name in names for marker in _ACTIVE_PARTS) or any(
                name.endswith(".bin") and "printersettings" not in name for name in names
            ):
                raise ValueError("the template holds active or linked content")
        return load_workbook(io.BytesIO(data), keep_links=False, keep_vba=False)
    except ValueError:
        raise
    except Exception:
        raise ValueError("the template is not a readable workbook") from None


def fill_workbook(template: bytes, fills: Sequence[FillCell]) -> bytes:
    """A copy of the user's workbook with the writer's values in the named cells. Formatting, widths, merges, number
    formats and the template's own formulas stay. A fill may not create a sheet, write into a merged range other than
    its first cell, or overwrite a formula; any such fill refuses the whole reply (no half-filled file)."""
    if len(fills) > MAX_FILL_CELLS:
        raise ValueError("too many cells to fill")
    workbook = _open_template(template)
    for fill in (FillCell.model_validate(f.model_dump()) for f in fills):
        if fill.sheet not in workbook.sheetnames:
            raise ValueError("no such sheet in the template")
        cell = workbook[fill.sheet][fill.cell]
        if isinstance(cell, MergedCell) or cell.data_type == "f":
            raise ValueError("that cell is merged or holds a formula")
        store(cell, fill.value)
    workbook.calculation.fullCalcOnLoad = True  # the template's own formulas recompute when it is opened
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def describe_workbook(template: bytes, *, max_chars: int = 3500) -> str:
    """The template's sheets, merged ranges and filled cells as `A1=Label` (formulas as `[formula]`): what a writer
    needs to choose where values go. Bounded in rows, columns and characters."""
    workbook = _open_template(template)
    out: list[str] = []
    for sheet in workbook.worksheets[:10]:
        merged = ", ".join(str(r) for r in list(sheet.merged_cells.ranges)[:10])
        out.append(f'Sheet "{text_value(sheet.title)}" ({sheet.dimensions}){f"; merged {merged}" if merged else ""}')
        for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 200), max_col=min(sheet.max_column, 40)):
            items = []
            for cell in row:
                if cell.value is None:
                    continue
                shown = "[formula]" if cell.data_type == "f" else " ".join(text_value(cell.value)[:60].split())
                items.append(f"{cell.coordinate}={shown}")
            if items:
                out.append(" | ".join(items))
    text = "\n".join(out)
    return text if len(text) <= max_chars else text[: max_chars - 30].rstrip() + "\n(more cells left out)"
