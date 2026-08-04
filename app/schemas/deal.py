"""Deal request/response schemas."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel
from app.schemas.base import ORMBase

from app.models.enums import LeadTier


class DealCreate(BaseModel):
    deal_name: str
    account_id: int
    contact_ids: list[int] = []
    value: float | None = None
    currency: str = "USD"
    expected_close_date: date | None = None
    stage_id: int
    # Not required on create -- intentionally absent from the "New Deal" UI,
    # per the mockups. Settable via create/update, never mandatory.
    tier: LeadTier | None = None
    owner_id: int
    cold_reason: str | None = None


class DealUpdate(BaseModel):
    deal_name: str | None = None
    account_id: int | None = None
    contact_ids: list[int] | None = None
    value: float | None = None
    currency: str | None = None
    expected_close_date: date | None = None
    stage_id: int | None = None
    tier: LeadTier | None = None
    owner_id: int | None = None
    cold_reason: str | None = None
    # Write-only input for the stage-history row's note. Never a column on
    # Deal -- must not be setattr'd onto the ORM object.
    note: str | None = None


class DealContactRead(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None


class DealRead(ORMBase):

    id: int
    deal_name: str
    account_id: int
    contacts: list[DealContactRead] = []
    value: float | None
    currency: str
    expected_close_date: date | None
    stage_id: int
    tier: LeadTier | None
    cold_reason: str | None
    owner_id: int


class DealStageHistoryRead(ORMBase):

    id: int
    deal_id: int
    from_stage_id: int | None
    to_stage_id: int
    changed_by: int
    changed_by_name: str
    note: str | None
    created_at: datetime


class DealBoardColumn(BaseModel):
    stage_id: int
    stage_name: str
    total_value: float
    deals: list[DealRead]


class DealsListResponse(BaseModel):
    view: Literal["list", "board"]
    items: list[DealRead] | None = None
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    columns: list[DealBoardColumn] | None = None
