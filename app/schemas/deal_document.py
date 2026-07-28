"""DealDocument response schema."""

from datetime import datetime

from app.schemas.base import ORMBase


class DealDocumentRead(ORMBase):

    id: int
    deal_id: int
    file_name: str
    file_url: str
    content_type: str
    uploaded_by: int
    created_at: datetime
