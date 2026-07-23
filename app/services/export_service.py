"""Shared xlsx-building helper: header row + one row per item, no
per-resource logic (callers own column selection/order)."""

import io
from typing import Any

from openpyxl import Workbook


def rows_to_xlsx(headers: list[str], rows: list[list[Any]], sheet_name: str = "Sheet1") -> io.BytesIO:
    """Builds an in-memory xlsx workbook: header row + one row per item in
    rows. Returns a seeked-to-0 BytesIO."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = sheet_name
    sheet.append(headers)
    for row in rows:
        sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
