from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DashboardTile(BaseModel):
    value: int
    change_pct: float | None = None


class DashboardSummary(BaseModel):
    leads_generated: DashboardTile
    qualified_leads: DashboardTile
    deals_in_pipeline: DashboardTile
    deals_closed: DashboardTile


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


class ActivityFeedEntry(BaseModel):
    entity_type: Literal["deal", "lead", "account"]
    entity_id: int
    type: str
    note: str
    created_by_name: str
    created_at: datetime


class ActivityFeedResponse(BaseModel):
    entries: list[ActivityFeedEntry]
