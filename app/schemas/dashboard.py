from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.base import ORMBase


class DashboardTile(BaseModel):
    value: int
    change_pct: float | None = None


class DashboardSummary(BaseModel):
    leads_generated: DashboardTile
    leads_to_accounts: DashboardTile
    deals_in_pipeline: DashboardTile
    deals_closed: DashboardTile
    num_accounts: DashboardTile


class FunnelStage(BaseModel):
    stage_id: int
    stage_name: str
    count: int
    # Lets a client drill down into `GET /deals` correctly without guessing
    # from `stage_name` (dashboard_service.get_funnel): open stages are a live
    # snapshot (no date filter), terminal ones are period-scoped
    # (`date_field=closed_at` over the same range this funnel was requested
    # with).
    is_terminal: bool


class FunnelResponse(BaseModel):
    stages: list[FunnelStage]


class DealDistributionEntry(BaseModel):
    tier: str
    count: int
    total_value: float


class DealDistributionResponse(BaseModel):
    entries: list[DealDistributionEntry]


class LeaderboardEntry(BaseModel):
    owner_id: int
    owner_name: str
    revenue: float
    deals_closed: int


class LeaderboardResponse(BaseModel):
    entries: list[LeaderboardEntry]


class DropOffReasonEntry(BaseModel):
    reason: str
    stage_lost: str
    count: int
    lost_value: float
    change_pct: float | None = None


class DropOffReasonsResponse(BaseModel):
    entries: list[DropOffReasonEntry]


class ConversionTrendEntry(BaseModel):
    period: str
    stage_name: str
    count: int


class ConversionTrendResponse(BaseModel):
    entries: list[ConversionTrendEntry]


class ActivityFeedEntry(ORMBase):
    entity_type: Literal["deal", "lead", "account"]
    entity_id: int
    type: str
    note: str
    created_by_name: str
    created_at: datetime


class ActivityFeedResponse(BaseModel):
    entries: list[ActivityFeedEntry]


class DashboardOverviewResponse(BaseModel):
    summary: DashboardSummary
    funnel: FunnelResponse
    deal_distribution: DealDistributionResponse
    leaderboard: LeaderboardResponse
    drop_off_reasons: DropOffReasonsResponse
    conversion_trend: ConversionTrendResponse
    activity_feed: ActivityFeedResponse
