"""LeadActivity request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field
from app.schemas.base import ORMBase

from app.models.enums import LeadActivityType


class LeadActivityCreate(BaseModel):
    type: LeadActivityType
    note: str = Field(min_length=1)


class LeadActivityUpdate(BaseModel):
    """Partial update: only supplied fields are applied."""

    type: LeadActivityType | None = None
    note: str | None = Field(default=None, min_length=1)


class LeadActivityRead(ORMBase):

    id: int
    lead_id: int
    type: LeadActivityType | None
    note: str
    created_by: int
    created_at: datetime
    updated_by: int | None
    updated_at: datetime


class LeadActivityDetailRead(LeadActivityRead):
    """LeadActivityRead plus the creator's/editor's display names, for the
    single-lead detail view (the Activity log needs "Logged by <name>" /
    "Edited by <name>", not an id)."""

    created_by_name: str
    updated_by_name: str | None
