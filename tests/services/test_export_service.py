"""app.services.export_service: rows_to_xlsx builds an in-memory workbook
from a header list + row-of-values list, with no per-resource logic."""

import io

import openpyxl

from app.services.export_service import rows_to_xlsx


def test_rows_to_xlsx_writes_header_and_rows() -> None:
    headers = ["Name", "Value"]
    rows = [["Alpha", 1], ["Beta", 2]]

    buffer = rows_to_xlsx(headers, rows, sheet_name="Widgets")

    assert isinstance(buffer, io.BytesIO)
    assert buffer.tell() == 0

    workbook = openpyxl.load_workbook(buffer)
    sheet = workbook.active
    assert sheet.title == "Widgets"
    assert [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))] == headers
    data_rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert data_rows == [("Alpha", 1), ("Beta", 2)]


def test_rows_to_xlsx_with_no_rows_still_writes_header() -> None:
    buffer = rows_to_xlsx(["A", "B"], [])

    workbook = openpyxl.load_workbook(buffer)
    sheet = workbook.active
    assert sheet.title == "Sheet1"
    assert sheet.max_row == 1
