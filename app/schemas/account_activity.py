"""AccountActivity request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field
from app.schemas.base import ORMBase

from app.models.enums import AccountActivityType


class AccountActivityCreate(BaseModel):
    type: AccountActivityType
    note: str = Field(min_length=1)


class AccountActivityUpdate(BaseModel):
    """Partial update: only supplied fields are applied."""

    type: AccountActivityType | None = None
    note: str | None = Field(default=None, min_length=1)


class AccountActivityRead(ORMBase):

    id: int
    account_id: int
    type: AccountActivityType
    note: str
    created_by: int
    created_at: datetime
    updated_by: int | None
    updated_at: datetime


class AccountActivityDetailRead(AccountActivityRead):
    """AccountActivityRead plus the creator's/editor's display names, for the
    single-account detail view (the Activity log needs "Logged by <name>" /
    "Edited by <name>", not an id)."""

    created_by_name: str
    updated_by_name: str | None
