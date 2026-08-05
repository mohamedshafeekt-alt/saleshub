from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.permission_codes import DASHBOARD_VIEW
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardOverviewResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOverviewResponse)
async def get_dashboard_route(
    period: Literal["this_week", "this_month", "custom"] = Query("this_month"),
    start_date: date | None = Query(None, description="Required when period='custom'"),
    end_date: date | None = Query(None, description="Required when period='custom'"),
    granularity: Literal["daily", "weekly", "monthly"] = Query("monthly"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardOverviewResponse:
    if period == "custom" and (start_date is None or end_date is None):
        raise HTTPException(status_code=422, detail="start_date and end_date are required when period='custom'")

    # ponytail: sequential, not asyncio.gather — a single AsyncSession can't run concurrent queries
    return DashboardOverviewResponse(
        summary=await dashboard_service.get_summary(db, period=period, start_date=start_date, end_date=end_date),
        funnel=await dashboard_service.get_funnel(db, period=period, start_date=start_date, end_date=end_date),
        deal_distribution=await dashboard_service.get_deal_distribution(
            db, period=period, start_date=start_date, end_date=end_date
        ),
        leaderboard=await dashboard_service.get_leaderboard(db, period=period, start_date=start_date, end_date=end_date),
        drop_off_reasons=await dashboard_service.get_drop_off_reasons(
            db, period=period, start_date=start_date, end_date=end_date
        ),
        conversion_trend=await dashboard_service.get_conversion_trend(
            db, granularity=granularity, period=period, start_date=start_date, end_date=end_date
        ),
        activity_feed=await dashboard_service.get_activity_feed(
            db, period=period, start_date=start_date, end_date=end_date, limit=limit, offset=offset
        ),
    )


tag_router_permissions(router, DASHBOARD_VIEW)
