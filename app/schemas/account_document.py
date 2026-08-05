"""AccountDocument response schema."""

from datetime import datetime

from pydantic import field_validator

from app.schemas.base import ORMBase
from app.services.storage import resolve_file_url


class AccountDocumentRead(ORMBase):

    id: int
    account_id: int
    file_name: str
    file_url: str
    content_type: str
    uploaded_by: int
    created_at: datetime

    @field_validator("file_url")
    @classmethod
    def _resolve_file_url(cls, value: str) -> str:
        return resolve_file_url(value)
