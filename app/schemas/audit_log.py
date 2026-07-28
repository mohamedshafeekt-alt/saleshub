"""AuditLogRead: response shape for GET /api/v1/audit-log."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    table_name: str
    record_id: int
    action: str
    actor_id: int
    actor_name: str
    description: str
    created_at: datetime

