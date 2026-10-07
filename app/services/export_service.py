"""Shared xlsx-building helpers: header row(s) + data row(s), no
per-resource logic (callers own column selection/order)."""

import io
from typing import Any

from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

_HEADER_FILL = PatternFill("solid", fgColor="1B2A4A")
_BAND_FILL = PatternFill("solid", fgColor="F3F6FB")
_STAGE_FILLS = {"closed won": "D9F2E1", "closed lost": "FADBD8"}
_THIN = Side(style="thin", color="DDE3EC")
_MAX_WIDTH = 45
_WRAP_COLUMNS = {"Comment"}


def _style_sheet(sheet: Worksheet) -> None:
    """Dark header, frozen header + first column, filters, banded rows, sized
    columns, wrapped comments and readable date formats."""
    headers = [str(c.value) for c in sheet[1]]
    border = Border(top=_THIN, bottom=_THIN, left=_THIN, right=_THIN)
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = border
    sheet.row_dimensions[1].height = 32

    for row_number, row in enumerate(sheet.iter_rows(min_row=2), start=2):
        for header, cell in zip(headers, row, strict=True):
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=header in _WRAP_COLUMNS)
            if row_number % 2 == 1:
                cell.fill = _BAND_FILL
            if isinstance(cell.value, datetime):
                cell.number_format = "dd-mmm-yyyy hh:mm"
            elif isinstance(cell.value, date):
                cell.number_format = "dd-mmm-yyyy"
            if header == "Stage" and isinstance(cell.value, str) and cell.value.lower() in _STAGE_FILLS:
                cell.fill = PatternFill("solid", fgColor=_STAGE_FILLS[cell.value.lower()])

    for index, header in enumerate(headers, start=1):
        longest = max(
            [len(header), *(len(str(c.value)) for c in sheet[get_column_letter(index)][1:] if c.value is not None)]
        )
        sheet.column_dimensions[get_column_letter(index)].width = min(max(longest + 3, 10), _MAX_WIDTH)

    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions


def sheets_to_xlsx(sheets: list[tuple[str, list[str], list[list[Any]]]], styled: bool = False) -> io.BytesIO:
    """Builds an in-memory xlsx workbook with one sheet per (name, headers,
    rows) tuple, in order. Returns a seeked-to-0 BytesIO."""
    workbook = Workbook()
    default_sheet = workbook.active
    assert default_sheet is not None
    workbook.remove(default_sheet)
    for sheet_name, headers, rows in sheets:
        sheet = workbook.create_sheet(title=sheet_name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        if styled:
            _style_sheet(sheet)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def rows_to_xlsx(
    headers: list[str], rows: list[list[Any]], sheet_name: str = "Sheet1", styled: bool = False
) -> io.BytesIO:
    """Builds a single-sheet xlsx workbook: header row + one row per item."""
    return sheets_to_xlsx([(sheet_name, headers, rows)], styled=styled)


def field_value_sheet(sheet_name: str, fields: dict[str, Any]) -> tuple[str, list[str], list[list[Any]]]:
    """Turns a flat {label: value} dict into a ("Field", "Value") sheet
    tuple, for single-record detail sheets in sheets_to_xlsx."""
    return (sheet_name, ["Field", "Value"], [[key, value] for key, value in fields.items()])
