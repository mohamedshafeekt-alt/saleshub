"""Bulk lead import response schemas."""

from pydantic import BaseModel


class LeadImportRowError(BaseModel):
    row: int
    error: str


class LeadImportResult(BaseModel):
    created: int
    errors: list[LeadImportRowError]
