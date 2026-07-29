"""Dashboard aggregation queries. Read-only — no mutations, no service-layer
error types; every function returns zeros/empty on no data rather than
raising, since an empty dashboard is a valid state."""

from datetime import date, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.account_activity import AccountActivity
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.deal_stage import DealStage
from app.models.deal_stage_history import DealStageHistory
from app.models.enums import LeadStatus
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.user import User
from app.schemas.dashboard import (
    ActivityFeedEntry,
    ActivityFeedResponse,
    ConversionTrendEntry,
    ConversionTrendResponse,
    DashboardSummary,
    DashboardTile,
    DealDistributionEntry,
    DealDistributionResponse,
    DropOffReasonEntry,
    DropOffReasonsResponse,
    FunnelResponse,
    FunnelStage,
    LeaderboardEntry,
    LeaderboardResponse,
)

# ponytail: stage identity (closed/won/lost) is inferred from DealStage.name,
# not a dedicated column — DealStage is per-company and this breaks silently
# if a company renames these stages. Accepted for Phase 1's fixed stage list
# (see docs/superpowers/specs/2026-07-28-dashboard-design.md); add a
# DealStage.stage_type enum if per-company custom stages become real.
CLOSED_WON_STAGE_NAME = "Closed Won"
CLOSED_LOST_STAGE_NAME = "Closed Lost"

QUALIFIED_LEAD_STATUSES = (LeadStatus.CONTACTED, LeadStatus.CONTACT_IN_FUTURE)

Period = Literal["today", "this_week", "this_month"]

_TRUNC_UNIT: dict[str, str] = {"daily": "day", "weekly": "week", "monthly": "month"}


def _period_bounds(period: Period, today: date) -> tuple[date, date, date, date]:
    if period == "today":
        start = today
    elif period == "this_week":
        start = today - timedelta(days=today.weekday())
    else:
        start = today.replace(day=1)
    length = (today - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return start, today, prev_start, prev_end


def _change_pct(value: int, prev: int) -> float | None:
    if prev == 0:
        return None
    return round((value - prev) / prev * 100, 1)


async def _count_leads(db: AsyncSession, lo: date, hi: date, *, qualified_only: bool) -> int:
    query = select(func.count(Lead.id)).where(
        Lead.created_at >= lo,
        Lead.created_at < hi + timedelta(days=1),
    )
    if qualified_only:
        query = query.where(Lead.status.in_(QUALIFIED_LEAD_STATUSES))
    result = await db.execute(query)
    return result.scalar_one()


async def _count_deals_in_pipeline(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(Deal.id))
        .join(DealStage, Deal.stage_id == DealStage.id)
        .where(
            DealStage.is_cold.is_(False),
            DealStage.name.not_in([CLOSED_WON_STAGE_NAME, CLOSED_LOST_STAGE_NAME]),
        )
    )
    return result.scalar_one()


async def _count_deals_closed(db: AsyncSession, lo: date, hi: date) -> int:
    # ponytail: Deal has no closed_at column — updated_at is used as the
    # closing timestamp. Acceptable since stage moves are the only thing
    # that touches a deal's updated_at in this codebase today.
    result = await db.execute(
        select(func.count(Deal.id))
        .join(DealStage, Deal.stage_id == DealStage.id)
        .where(
            DealStage.name == CLOSED_WON_STAGE_NAME,
            Deal.updated_at >= lo,
            Deal.updated_at < hi + timedelta(days=1),
        )
    )
    return result.scalar_one()


async def get_summary(db: AsyncSession, *, period: Period = "this_month") -> DashboardSummary:
    today = date.today()
    start, end, prev_start, prev_end = _period_bounds(period, today)

    leads_now = await _count_leads(db, start, end, qualified_only=False)
    leads_prev = await _count_leads(db, prev_start, prev_end, qualified_only=False)
    qualified_now = await _count_leads(db, start, end, qualified_only=True)
    qualified_prev = await _count_leads(db, prev_start, prev_end, qualified_only=True)
    pipeline_now = await _count_deals_in_pipeline(db)
    closed_now = await _count_deals_closed(db, start, end)
    closed_prev = await _count_deals_closed(db, prev_start, prev_end)

    return DashboardSummary(
        leads_generated=DashboardTile(value=leads_now, change_pct=_change_pct(leads_now, leads_prev)),
        qualified_leads=DashboardTile(value=qualified_now, change_pct=_change_pct(qualified_now, qualified_prev)),
        deals_in_pipeline=DashboardTile(value=pipeline_now, change_pct=None),
        deals_closed=DashboardTile(value=closed_now, change_pct=_change_pct(closed_now, closed_prev)),
    )


async def get_funnel(db: AsyncSession) -> FunnelResponse:
    result = await db.execute(
        select(DealStage.name, func.count(Deal.id))
        .join(Deal, Deal.stage_id == DealStage.id, isouter=True)
        .group_by(DealStage.id, DealStage.name, DealStage.sort_order)
        .order_by(DealStage.sort_order)
    )
    return FunnelResponse(stages=[FunnelStage(stage_name=name, count=count) for name, count in result.all()])


async def get_deal_distribution(db: AsyncSession) -> DealDistributionResponse:
    result = await db.execute(
        select(Deal.tier, func.count(Deal.id), func.coalesce(func.sum(Deal.value), 0))
        .where(Deal.tier.is_not(None))
        .group_by(Deal.tier)
    )
    return DealDistributionResponse(
        entries=[
            DealDistributionEntry(tier=tier.value, count=count, total_value=float(total_value))
            for tier, count, total_value in result.all()
        ]
    )


async def get_leaderboard(db: AsyncSession) -> LeaderboardResponse:
    result = await db.execute(
        select(
            User.id,
            User.first_name,
            User.last_name,
            func.coalesce(func.sum(Deal.value), 0),
            func.count(Deal.id),
        )
        .join(Deal, Deal.owner_id == User.id)
        .join(DealStage, Deal.stage_id == DealStage.id)
        .where(DealStage.name == CLOSED_WON_STAGE_NAME)
        .group_by(User.id, User.first_name, User.last_name)
        .order_by(func.sum(Deal.value).desc())
    )
    return LeaderboardResponse(
        entries=[
            LeaderboardEntry(
                owner_id=owner_id,
                owner_name=" ".join(filter(None, [first_name, last_name])),
                revenue=float(revenue),
                deals_closed=deals_closed,
            )
            for owner_id, first_name, last_name, revenue, deals_closed in result.all()
        ]
    )


def _drop_off_query(lo: date | None = None, hi: date | None = None):
    # ponytail: "stage lost" is the from_stage of the most recent transition
    # into the deal's current cold/lost stage (via DealStageHistory) — every
    # stage move writes a history row (including on create, from_stage=None),
    # so a deal created directly into a cold/lost stage has no prior stage.
    # Both that case AND a deal with no history row at all (defensive —
    # shouldn't happen via the real create/update service, but the join is
    # outer so such a deal still surfaces instead of silently vanishing from
    # the report) coalesce to "Unknown" rather than being dropped or null.
    from_stage = aliased(DealStage)
    latest_transition = (
        select(
            DealStageHistory.deal_id,
            DealStageHistory.from_stage_id,
            DealStageHistory.created_at,
            func.row_number()
            .over(partition_by=DealStageHistory.deal_id, order_by=DealStageHistory.created_at.desc())
            .label("rn"),
        )
        .join(Deal, Deal.id == DealStageHistory.deal_id)
        .where(DealStageHistory.to_stage_id == Deal.stage_id)
        .subquery()
    )
    query = (
        select(
            Deal.cold_reason,
            func.coalesce(from_stage.name, "Unknown"),
            func.count(Deal.id),
            func.coalesce(func.sum(Deal.value), 0),
        )
        .join(DealStage, Deal.stage_id == DealStage.id)
        .join(latest_transition, latest_transition.c.deal_id == Deal.id, isouter=True)
        .join(from_stage, from_stage.id == latest_transition.c.from_stage_id, isouter=True)
        .where(
            Deal.cold_reason.is_not(None),
            (DealStage.is_cold.is_(True)) | (DealStage.name == CLOSED_LOST_STAGE_NAME),
            (latest_transition.c.rn == 1) | (latest_transition.c.rn.is_(None)),
        )
        .group_by(Deal.cold_reason, from_stage.name)
    )
    if lo is not None and hi is not None:
        query = query.where(
            latest_transition.c.created_at >= lo,
            latest_transition.c.created_at < hi + timedelta(days=1),
        )
    return query.order_by(func.count(Deal.id).desc())


async def get_drop_off_reasons(db: AsyncSession, *, period: Period = "this_month") -> DropOffReasonsResponse:
    rows = (await db.execute(_drop_off_query())).all()

    today = date.today()
    start, end, prev_start, prev_end = _period_bounds(period, today)
    now_counts = {(reason, stage): count for reason, stage, count, _ in (await db.execute(_drop_off_query(start, end))).all()}
    prev_counts = {
        (reason, stage): count for reason, stage, count, _ in (await db.execute(_drop_off_query(prev_start, prev_end))).all()
    }

    return DropOffReasonsResponse(
        entries=[
            DropOffReasonEntry(
                reason=reason,
                stage_lost=stage_lost,
                count=count,
                lost_value=float(lost_value),
                change_pct=_change_pct(
                    now_counts.get((reason, stage_lost), 0), prev_counts.get((reason, stage_lost), 0)
                ),
            )
            for reason, stage_lost, count, lost_value in rows
        ]
    )


async def get_conversion_trend(
    db: AsyncSession, *, granularity: Literal["daily", "weekly", "monthly"] = "monthly"
) -> ConversionTrendResponse:
    period_col = func.date_trunc(_TRUNC_UNIT[granularity], DealStageHistory.created_at)
    result = await db.execute(
        select(period_col, DealStage.name, func.count(DealStageHistory.id))
        .join(DealStage, DealStageHistory.to_stage_id == DealStage.id)
        .group_by(period_col, DealStage.name)
        .order_by(period_col)
    )
    return ConversionTrendResponse(
        entries=[
            ConversionTrendEntry(period=period.date().isoformat(), stage_name=stage_name, count=count)
            for period, stage_name, count in result.all()
        ]
    )


async def get_activity_feed(db: AsyncSession, *, limit: int = 20, offset: int = 0) -> ActivityFeedResponse:
    deal_rows = (
        (await db.execute(select(DealActivity).order_by(DealActivity.created_at.desc()).limit(limit + offset)))
        .scalars()
        .all()
    )
    lead_rows = (
        (await db.execute(select(LeadActivity).order_by(LeadActivity.created_at.desc()).limit(limit + offset)))
        .scalars()
        .all()
    )
    account_rows = (
        (await db.execute(select(AccountActivity).order_by(AccountActivity.created_at.desc()).limit(limit + offset)))
        .scalars()
        .all()
    )

    merged = (
        [
            ActivityFeedEntry(
                entity_type="deal",
                entity_id=a.deal_id,
                type=a.type.value,
                note=a.note,
                created_by_name=a.created_by_name,
                created_at=a.created_at,
            )
            for a in deal_rows
        ]
        + [
            ActivityFeedEntry(
                entity_type="lead",
                entity_id=a.lead_id,
                type=a.type.value,
                note=a.note,
                created_by_name=a.created_by_name,
                created_at=a.created_at,
            )
            for a in lead_rows
        ]
        + [
            ActivityFeedEntry(
                entity_type="account",
                entity_id=a.account_id,
                type=a.type.value,
                note=a.note,
                created_by_name=a.created_by_name,
                created_at=a.created_at,
            )
            for a in account_rows
        ]
    )
    merged.sort(key=lambda e: e.created_at, reverse=True)
    return ActivityFeedResponse(entries=merged[offset : offset + limit])
