"""LeadActivity request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import LeadActivityType


class LeadActivityCreate(BaseModel):
    type: LeadActivityType
    note: str = Field(min_length=1)


class LeadActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    type: LeadActivityType
    note: str
    created_by: int
    created_at: datetime


class LeadActivityDetailRead(LeadActivityRead):
    """LeadActivityRead plus the creator's display name, for the single-lead
    detail view (the Activity log needs "Logged by <name>", not an id)."""

    created_by_name: str
