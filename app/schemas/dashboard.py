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
    stage_name: str
    count: int


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
    account_name: str
    tier: str
    lost_value: float


class DropOffReasonsResponse(BaseModel):
    entries: list[DropOffReasonEntry]


class ConversionTrendEntry(BaseModel):
    period: str
    leads_created: int
    leads_converted: int
    conversion_rate: float


class ConversionTrendResponse(BaseModel):
    entries: list[ConversionTrendEntry]


class ActivityFeedEntry(ORMBase):
    entity_type: Literal["deal", "lead", "account"]
    entity_id: int
    type: str
    note: str
    created_by_name: str
    created_at: datetime
    # "edited" entries reuse created_by_name/created_at for whoever made the
    # edit and when -- so an edited activity sorts into the feed by its edit
    # time, not its original creation time.
    action: Literal["created", "edited"] = "created"


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
