"""Deal request/response schemas."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel
from app.schemas.base import ORMBase

from app.core.deal_scoring import validate_scores
from app.models.enums import LeadTier
from app.schemas.account_source import SourcePersonRef

# D1–D8 level keys; all-or-nothing, see app/core/deal_scoring.py.
DealScores = Annotated[dict[str, str] | None, AfterValidator(validate_scores)]
ProposalStatus = Literal["not_sent", "proposal_sent"]


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
    scores: DealScores = None
    follow_up_date: date | None = None
    originator: SourcePersonRef | None = None


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
    # Explicit null clears the scoring.
    scores: DealScores = None
    # Explicit null clears (follow_up_date, originator).
    follow_up_date: date | None = None
    originator: SourcePersonRef | None = None
    # Server-managed date: set to today on proposal_sent unless given;
    # cleared on not_sent.
    proposal_status: ProposalStatus | None = None
    proposal_sent_at: date | None = None
    # Write-only input for the stage-history row's note. Never a column on
    # Deal -- must not be setattr'd onto the ORM object.
    note: str | None = None


class DealContactRead(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None


class OriginatorRead(BaseModel):
    type: Literal["user", "contact"]
    id: int
    name: str


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
    account_name: str
    owner_name: str
    stage_name: str
    stage_is_cold: bool
    scores: dict[str, str] | None
    total_score: int | None
    response_mode: str | None
    proposal_sla: str | None
    created_at: datetime
    follow_up_date: date | None
    originator: OriginatorRead | None
    proposal_status: ProposalStatus
    proposal_sent_at: date | None
    proposal_sla_due_at: datetime | None


class ScoringLevelRead(BaseModel):
    key: str
    label: str
    description: str


class ScoringDimensionRead(BaseModel):
    key: str
    label: str
    levels: list[ScoringLevelRead]


class DealStageHistoryRead(ORMBase):

    id: int
    deal_id: int
    from_stage_id: int | None
    to_stage_id: int
    from_stage_name: str | None
    to_stage_name: str
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
