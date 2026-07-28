"""AccountDocument response schema."""

from datetime import datetime

from app.schemas.base import ORMBase


class AccountDocumentRead(ORMBase):

    id: int
    account_id: int
    file_name: str
    file_url: str
    content_type: str
    uploaded_by: int
    created_at: datetime
