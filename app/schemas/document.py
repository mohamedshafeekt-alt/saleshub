"""Combined Document read schema: a union row from AccountDocument and
DealDocument for the cross-entity Documents view."""

from datetime import datetime
from typing import Literal

from pydantic import field_validator

from app.schemas.base import ORMBase
from app.services.storage import resolve_file_url


class DocumentRead(ORMBase):

    id: int
    source: Literal["account", "deal"]
    entity_id: int
    entity_name: str
    file_name: str
    file_url: str
    content_type: str
    uploaded_by: int
    created_at: datetime

    @field_validator("file_url")
    @classmethod
    def _resolve_file_url(cls, value: str) -> str:
        return resolve_file_url(value)
