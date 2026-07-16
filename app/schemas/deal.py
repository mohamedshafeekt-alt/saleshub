"""Deal request/response schemas."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DealStage


class DealCreate(BaseModel):
    deal_name: str
    account_id: int
    value: float | None = None
    currency: str = "USD"
    expected_close_date: date | None = None
    stage: DealStage = DealStage.RECEIVED_REQUIREMENTS
    owner_id: int
    cold_reason: str | None = None


class DealUpdate(BaseModel):
    deal_name: str | None = None
    account_id: int | None = None
    value: float | None = None
    currency: str | None = None
    expected_close_date: date | None = None
    stage: DealStage | None = None
    owner_id: int | None = None
    cold_reason: str | None = None
    # Write-only input for the stage-history row's note. Never a column on
    # Deal -- must not be setattr'd onto the ORM object.
    note: str | None = None


class DealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deal_name: str
    account_id: int
    value: float | None
    currency: str
    expected_close_date: date | None
    stage: DealStage
    cold_reason: str | None
    owner_id: int


class DealStageHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deal_id: int
    from_stage: DealStage | None
    to_stage: DealStage
    changed_by: int
    note: str | None
    created_at: datetime
