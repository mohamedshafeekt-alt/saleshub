"""DealActivity request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DealActivityType


class DealActivityCreate(BaseModel):
    type: DealActivityType
    note: str = Field(min_length=1)


class DealActivityUpdate(BaseModel):
    """Partial update: only supplied fields are applied."""

    type: DealActivityType | None = None
    note: str | None = Field(default=None, min_length=1)


class DealActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deal_id: int
    type: DealActivityType
    note: str
    created_by: int
    created_at: datetime
    updated_by: int | None
    updated_at: datetime


class DealActivityDetailRead(DealActivityRead):
    """DealActivityRead plus the creator's/editor's display names, for the
    single-deal detail view (the Activity log needs "Logged by <name>" /
    "Edited by <name>", not an id)."""

    created_by_name: str
    updated_by_name: str | None
