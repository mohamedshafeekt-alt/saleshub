"""Generic single-field table patch request/response schemas."""

from typing import Any

from pydantic import BaseModel


class GenericPatchRequest(BaseModel):
    table: str
    record_id: int
    field: str
    value: Any


class GenericPatchResponse(BaseModel):
    id: int
    field: str
    value: Any
