"""Bulk contact import response schemas."""

from pydantic import BaseModel


class ContactImportRowError(BaseModel):
    row: int
    error: str


class ContactImportResult(BaseModel):
    created: int
    errors: list[ContactImportRowError]
