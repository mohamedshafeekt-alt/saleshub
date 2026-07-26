"""AccountDocument response schema."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AccountDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    file_name: str
    file_url: str
    content_type: str
    uploaded_by: int
    created_at: datetime
