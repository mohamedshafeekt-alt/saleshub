"""Combined Document read schema: a union row from AccountDocument and
DealDocument for the cross-entity Documents view."""

from datetime import datetime
from typing import Literal

from app.schemas.base import ORMBase


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
