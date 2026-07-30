"""Shared xlsx-building helpers: header row(s) + data row(s), no
per-resource logic (callers own column selection/order)."""

import io
from typing import Any

from openpyxl import Workbook


def sheets_to_xlsx(sheets: list[tuple[str, list[str], list[list[Any]]]]) -> io.BytesIO:
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

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def rows_to_xlsx(headers: list[str], rows: list[list[Any]], sheet_name: str = "Sheet1") -> io.BytesIO:
    """Builds a single-sheet xlsx workbook: header row + one row per item."""
    return sheets_to_xlsx([(sheet_name, headers, rows)])


def field_value_sheet(sheet_name: str, fields: dict[str, Any]) -> tuple[str, list[str], list[list[Any]]]:
    """Turns a flat {label: value} dict into a ("Field", "Value") sheet
    tuple, for single-record detail sheets in sheets_to_xlsx."""
    return (sheet_name, ["Field", "Value"], [[key, value] for key, value in fields.items()])
