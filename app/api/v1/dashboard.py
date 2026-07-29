from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import (
    ActivityFeedResponse,
    ConversionTrendResponse,
    DashboardSummary,
    DealDistributionResponse,
    DropOffReasonsResponse,
    FunnelResponse,
    LeaderboardResponse,
)
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_summary_route(
    period: Literal["today", "this_week", "this_month"] = Query("this_month"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    return await dashboard_service.get_summary(db, period=period)


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelResponse:
    return await dashboard_service.get_funnel(db)


@router.get("/deal-distribution", response_model=DealDistributionResponse)
async def get_deal_distribution_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealDistributionResponse:
    return await dashboard_service.get_deal_distribution(db)


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardResponse:
    return await dashboard_service.get_leaderboard(db)


@router.get("/drop-off-reasons", response_model=DropOffReasonsResponse)
async def get_drop_off_reasons_route(
    period: Literal["today", "this_week", "this_month"] = Query("this_month"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DropOffReasonsResponse:
    return await dashboard_service.get_drop_off_reasons(db, period=period)


@router.get("/conversion-trend", response_model=ConversionTrendResponse)
async def get_conversion_trend_route(
    granularity: Literal["daily", "weekly", "monthly"] = Query("monthly"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversionTrendResponse:
    return await dashboard_service.get_conversion_trend(db, granularity=granularity)


@router.get("/activity-feed", response_model=ActivityFeedResponse)
async def get_activity_feed_route(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityFeedResponse:
    return await dashboard_service.get_activity_feed(db, limit=limit, offset=offset)
