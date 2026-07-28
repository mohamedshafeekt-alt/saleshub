from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardOverviewResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOverviewResponse)
async def get_dashboard_route(
    period: Literal["today", "this_week", "this_month"] = Query("this_month"),
    granularity: Literal["daily", "weekly", "monthly"] = Query("monthly"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardOverviewResponse:
    # ponytail: sequential, not asyncio.gather — a single AsyncSession can't run concurrent queries
    return DashboardOverviewResponse(
        summary=await dashboard_service.get_summary(db, period=period),
        funnel=await dashboard_service.get_funnel(db),
        deal_distribution=await dashboard_service.get_deal_distribution(db),
        leaderboard=await dashboard_service.get_leaderboard(db),
        drop_off_reasons=await dashboard_service.get_drop_off_reasons(db, period=period),
        conversion_trend=await dashboard_service.get_conversion_trend(db, granularity=granularity),
        activity_feed=await dashboard_service.get_activity_feed(db, limit=limit, offset=offset),
    )
