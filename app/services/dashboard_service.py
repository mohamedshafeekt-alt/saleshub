"""Dashboard aggregation queries. Read-only — no mutations, no service-layer
error types; every function returns zeros/empty on no data rather than
raising, since an empty dashboard is a valid state."""

from datetime import date, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.account import Account
from app.models.account_activity import AccountActivity
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.deal_stage import (
    CLOSED_LOST_STAGE_NAME,
    CLOSED_WON_STAGE_NAME,
    DealStage,
    is_terminal_stage,
)
from app.models.deal_stage_history import DealStageHistory, entered_current_stage_in, stage_as_of
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

Period = Literal["this_week", "this_month", "custom"]

_TRUNC_UNIT: dict[str, str] = {"daily": "day", "weekly": "week", "monthly": "month"}


def _period_bounds(
    period: Period, today: date, *, start_date: date | None = None, end_date: date | None = None
) -> tuple[date, date, date, date]:
    if period == "custom":
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date are required when period='custom'")
        if end_date < start_date:
            raise ValueError("end_date must not be before start_date")
        start, end = start_date, end_date
    elif period == "this_week":
        start, end = today - timedelta(days=today.weekday()), today
    else:
        start, end = today.replace(day=1), today
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return start, end, prev_start, prev_end


def _change_pct(value: int, prev: int) -> float | None:
    if prev == 0:
        return None
    return round((value - prev) / prev * 100, 1)


async def _count_leads(db: AsyncSession, lo: date, hi: date) -> int:
    result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.created_at >= lo,
            Lead.created_at < hi + timedelta(days=1),
        )
    )
    return result.scalar_one()


async def _count_leads_converted(db: AsyncSession, lo: date, hi: date) -> int:
    # "Leads to Accounts" = leads that converted to an Account in this period.
    # Lead has no converted_at column, but convert_lead_to_account() creates
    # the Account (with source_lead_id set) in the same operation that flips
    # is_converted, so Account.created_at doubles as the conversion timestamp.
    # (Previously this counted Lead.status in {contacted, contact_in_future}
    # — a heuristic unrelated to actual conversion that drifted wildly from
    # real qualified-lead counts once a lead's status stopped being updated
    # after conversion.)
    result = await db.execute(
        select(func.count(Account.id)).where(
            Account.source_lead_id.is_not(None),
            Account.created_at >= lo,
            Account.created_at < hi + timedelta(days=1),
        )
    )
    return result.scalar_one()


async def _count_deals_in_pipeline(db: AsyncSession, as_of: date) -> int:
    """Deals still open at the end of `as_of` — a snapshot, not a period count.

    Reconstructed from stage history (`stage_as_of`) rather than read off
    Deal.stage_id, so a past period reports the pipeline as it actually stood:
    a deal that closed after `as_of` was open then and has to count. Deals with
    no history row at all fall back to their current stage instead of vanishing.
    """
    stage_then = stage_as_of(as_of)
    result = await db.execute(
        select(func.count(Deal.id))
        .join(stage_then, stage_then.c.deal_id == Deal.id, isouter=True)
        .join(DealStage, DealStage.id == func.coalesce(stage_then.c.stage_id, Deal.stage_id))
        .where(
            ~is_terminal_stage(),
            # A deal created after the snapshot didn't exist yet; without this
            # the coalesce fallback above would count it at its current stage.
            Deal.created_at < as_of + timedelta(days=1),
        )
    )
    return result.scalar_one()


async def _count_deals_closed(db: AsyncSession, lo: date, hi: date) -> int:
    result = await db.execute(
        select(func.count(Deal.id))
        .join(DealStage, Deal.stage_id == DealStage.id)
        .where(
            DealStage.name == CLOSED_WON_STAGE_NAME,
            entered_current_stage_in(lo, hi),
        )
    )
    return result.scalar_one()


async def _count_accounts(db: AsyncSession, lo: date, hi: date) -> int:
    result = await db.execute(
        select(func.count(Account.id)).where(
            Account.created_at >= lo,
            Account.created_at < hi + timedelta(days=1),
        )
    )
    return result.scalar_one()


async def get_summary(
    db: AsyncSession,
    *,
    period: Period = "this_month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> DashboardSummary:
    today = date.today()
    start, end, prev_start, prev_end = _period_bounds(period, today, start_date=start_date, end_date=end_date)

    leads_now = await _count_leads(db, start, end)
    leads_prev = await _count_leads(db, prev_start, prev_end)
    qualified_now = await _count_leads_converted(db, start, end)
    qualified_prev = await _count_leads_converted(db, prev_start, prev_end)
    # Snapshot tiles take a single as-of date, not a range: "how big was the
    # pipeline at the end of this period" vs "...at the end of the last one".
    pipeline_now = await _count_deals_in_pipeline(db, end)
    pipeline_prev = await _count_deals_in_pipeline(db, prev_end)
    closed_now = await _count_deals_closed(db, start, end)
    closed_prev = await _count_deals_closed(db, prev_start, prev_end)
    accounts_now = await _count_accounts(db, start, end)
    accounts_prev = await _count_accounts(db, prev_start, prev_end)

    return DashboardSummary(
        leads_generated=DashboardTile(value=leads_now, change_pct=_change_pct(leads_now, leads_prev)),
        leads_to_accounts=DashboardTile(value=qualified_now, change_pct=_change_pct(qualified_now, qualified_prev)),
        deals_in_pipeline=DashboardTile(value=pipeline_now, change_pct=_change_pct(pipeline_now, pipeline_prev)),
        deals_closed=DashboardTile(value=closed_now, change_pct=_change_pct(closed_now, closed_prev)),
        num_accounts=DashboardTile(value=accounts_now, change_pct=_change_pct(accounts_now, accounts_prev)),
    )


async def get_funnel(
    db: AsyncSession,
    *,
    period: Period = "this_month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> FunnelResponse:
    # Open stages: live count of deals CURRENTLY sitting there, period
    # ignored — "how many deals are in Evaluation right now", not "how many
    # entered Evaluation this period" (which double-counted a deal that
    # bounces through the same stage more than once in a window).
    # Terminal stages (Closed Won/Lost/Cold): period-scoped by when the deal
    # entered that stage, the same predicate _count_deals_closed and
    # get_leaderboard use — so the Closed Won bar always matches the Deals
    # Closed tile, and both match GET /deals?date_field=closed_at.
    today = date.today()
    start, end, _, _ = _period_bounds(period, today, start_date=start_date, end_date=end_date)
    in_scope = or_(~is_terminal_stage(), entered_current_stage_in(start, end))
    result = await db.execute(
        select(DealStage.name, func.count(Deal.id))
        .select_from(DealStage)
        .join(Deal, and_(Deal.stage_id == DealStage.id, in_scope), isouter=True)
        .group_by(DealStage.id, DealStage.name, DealStage.sort_order)
        .order_by(DealStage.sort_order)
    )
    return FunnelResponse(
        stages=[FunnelStage(stage_name=name, count=count) for name, count in result.all()]
    )


async def get_deal_distribution(
    db: AsyncSession,
    *,
    period: Period = "this_month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> DealDistributionResponse:
    # Same scoping as get_funnel: an open (non-terminal) stage counts every
    # deal CURRENTLY sitting there regardless of period -- only terminal
    # stages (Closed Won/Lost/Cold) are scoped by when the deal entered that
    # stage. Was `entered_current_stage_in` alone, which silently dropped any
    # open deal that hadn't changed stage within the period -- the funnel and
    # the Deals list both counted it, but this donut didn't, so the same
    # range showed 3 deals everywhere except here.
    today = date.today()
    start, end, _, _ = _period_bounds(period, today, start_date=start_date, end_date=end_date)
    in_scope = or_(~is_terminal_stage(), entered_current_stage_in(start, end))
    result = await db.execute(
        select(Deal.tier, func.count(Deal.id), func.coalesce(func.sum(Deal.value), 0))
        .join(DealStage, Deal.stage_id == DealStage.id)
        .where(in_scope)
        .group_by(Deal.tier)
    )
    return DealDistributionResponse(
        entries=[
            # tier is nullable on Deal -- untiered deals get an "Unassigned"
            # bucket instead of being dropped, so the sum of entries here
            # matches the Deals list's total count for the same range.
            DealDistributionEntry(
                tier=tier.value if tier is not None else "Unassigned",
                count=count,
                total_value=float(total_value),
            )
            for tier, count, total_value in result.all()
        ]
    )


async def get_leaderboard(
    db: AsyncSession,
    *,
    period: Period = "this_month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> LeaderboardResponse:
    # Revenue is credited to the period the deal was WON in (stage history),
    # not the period it was last edited in — same predicate as the tile.
    today = date.today()
    start, end, _, _ = _period_bounds(period, today, start_date=start_date, end_date=end_date)
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
        .where(
            DealStage.name == CLOSED_WON_STAGE_NAME,
            entered_current_stage_in(start, end),
        )
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
    # One row per deal (not grouped by reason) -- Account name/Tier are
    # per-deal attributes, so a "Count"/"Trend" aggregate no longer applies.
    query = (
        select(
            Deal.cold_reason,
            func.coalesce(from_stage.name, "Unknown"),
            Account.company,
            Account.tier,
            Deal.value,
        )
        .join(DealStage, Deal.stage_id == DealStage.id)
        .join(Account, Deal.account_id == Account.id)
        .join(latest_transition, latest_transition.c.deal_id == Deal.id, isouter=True)
        .join(from_stage, from_stage.id == latest_transition.c.from_stage_id, isouter=True)
        .where(
            Deal.cold_reason.is_not(None),
            (DealStage.is_cold.is_(True)) | (DealStage.name == CLOSED_LOST_STAGE_NAME),
            (latest_transition.c.rn == 1) | (latest_transition.c.rn.is_(None)),
        )
    )
    if lo is not None and hi is not None:
        # A deal with no history row at all (the "Unknown" case) has a NULL
        # latest_transition.created_at, which `>= lo` never matches — so
        # filtering on it directly would silently drop every "Unknown" row
        # from every period. Fall back to Deal.created_at (the only
        # timestamp such a deal has) so it can still be period-scoped.
        effective_ts = func.coalesce(latest_transition.c.created_at, Deal.created_at)
        query = query.where(
            effective_ts >= lo,
            effective_ts < hi + timedelta(days=1),
        )
    return query.order_by(Deal.value.desc())


async def get_drop_off_reasons(
    db: AsyncSession,
    *,
    period: Period = "this_month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> DropOffReasonsResponse:
    today = date.today()
    start, end, _, _ = _period_bounds(period, today, start_date=start_date, end_date=end_date)
    now_rows = (await db.execute(_drop_off_query(start, end))).all()

    return DropOffReasonsResponse(
        entries=[
            DropOffReasonEntry(
                reason=reason,
                stage_lost=stage_lost,
                account_name=account_name,
                tier=tier.value,
                lost_value=float(lost_value),
            )
            for reason, stage_lost, account_name, tier, lost_value in now_rows
        ]
    )


async def get_conversion_trend(
    db: AsyncSession,
    *,
    granularity: Literal["daily", "weekly", "monthly"] = "monthly",
    period: Period = "this_month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> ConversionTrendResponse:
    # Leads -> Account conversion rate per period bucket. This used to count
    # DealStageHistory transitions instead -- an unrelated deal-pipeline
    # metric that had nothing to do with leads or accounts, so there was no
    # way to manually verify a widget labeled "Leads to Account Conversion
    # Trend" against it. Reuses the same facts _count_leads/
    # _count_leads_converted already use for the single-window "Leads to
    # Accounts" tile (Account.created_at, where source_lead_id is set,
    # doubles as the conversion timestamp), just bucketed by granularity.
    today = date.today()
    start, end, _, _ = _period_bounds(period, today, start_date=start_date, end_date=end_date)

    leads_period_col = func.date_trunc(_TRUNC_UNIT[granularity], Lead.created_at)
    leads_result = await db.execute(
        select(leads_period_col, func.count(Lead.id))
        .where(Lead.created_at >= start, Lead.created_at < end + timedelta(days=1))
        .group_by(leads_period_col)
    )
    leads_by_period = {bucket.date().isoformat(): count for bucket, count in leads_result.all()}

    converted_period_col = func.date_trunc(_TRUNC_UNIT[granularity], Account.created_at)
    converted_result = await db.execute(
        select(converted_period_col, func.count(Account.id))
        .where(
            Account.source_lead_id.is_not(None),
            Account.created_at >= start,
            Account.created_at < end + timedelta(days=1),
        )
        .group_by(converted_period_col)
    )
    converted_by_period = {bucket.date().isoformat(): count for bucket, count in converted_result.all()}

    entries = []
    for p in sorted(set(leads_by_period) | set(converted_by_period)):
        created = leads_by_period.get(p, 0)
        converted = converted_by_period.get(p, 0)
        # A lead created in one bucket may convert in a later one -- an
        # accepted period-boundary simplification (same class as
        # _count_deals_in_pipeline's snapshot-vs-period tradeoff above),
        # not solved here with cohort tracking.
        rate = round(converted / created * 100, 1) if created else 0.0
        entries.append(
            ConversionTrendEntry(period=p, leads_created=created, leads_converted=converted, conversion_rate=rate)
        )
    return ConversionTrendResponse(entries=entries)


def _activity_type_value(activity_type: object, *, default: str = "system") -> str:
    # Normally always an enum member (loaded fresh from DB via a real
    # SELECT, so SQLAlchemy's Enum type always deserializes it) -- but an
    # object already resident in the session's identity map from an earlier
    # write in the same session/transaction (e.g. test fixtures that
    # construct rows directly with a raw string, then mutate/flush again)
    # can retain whatever Python value it was assigned. Tolerate both shapes
    # rather than crash on `.value`.
    if activity_type is None:
        return default
    value = getattr(activity_type, "value", None)
    return value if value is not None else str(activity_type)


async def get_activity_feed(
    db: AsyncSession,
    *,
    period: Period = "this_month",
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ActivityFeedResponse:
    today = date.today()
    start, end, _, _ = _period_bounds(period, today, start_date=start_date, end_date=end_date)
    lo, hi = start, end + timedelta(days=1)

    deal_rows = (
        (
            await db.execute(
                select(DealActivity)
                .where(DealActivity.created_at >= lo, DealActivity.created_at < hi)
                .order_by(DealActivity.created_at.desc())
                .limit(limit + offset)
            )
        )
        .scalars()
        .all()
    )
    lead_rows = (
        (
            await db.execute(
                select(LeadActivity)
                .where(LeadActivity.created_at >= lo, LeadActivity.created_at < hi)
                .order_by(LeadActivity.created_at.desc())
                .limit(limit + offset)
            )
        )
        .scalars()
        .all()
    )
    account_rows = (
        (
            await db.execute(
                select(AccountActivity)
                .where(AccountActivity.created_at >= lo, AccountActivity.created_at < hi)
                .order_by(AccountActivity.created_at.desc())
                .limit(limit + offset)
            )
        )
        .scalars()
        .all()
    )

    # Edits: same three tables, but keyed on updated_by/updated_at instead of
    # created_by/created_at, so an edit made in-period surfaces as its own
    # feed entry (sorted by when the edit happened) even if the activity was
    # originally created outside the period.
    deal_edit_rows = (
        (
            await db.execute(
                select(DealActivity)
                .where(DealActivity.updated_by.is_not(None), DealActivity.updated_at >= lo, DealActivity.updated_at < hi)
                .order_by(DealActivity.updated_at.desc())
                .limit(limit + offset)
            )
        )
        .scalars()
        .all()
    )
    lead_edit_rows = (
        (
            await db.execute(
                select(LeadActivity)
                .where(LeadActivity.updated_by.is_not(None), LeadActivity.updated_at >= lo, LeadActivity.updated_at < hi)
                .order_by(LeadActivity.updated_at.desc())
                .limit(limit + offset)
            )
        )
        .scalars()
        .all()
    )
    account_edit_rows = (
        (
            await db.execute(
                select(AccountActivity)
                .where(
                    AccountActivity.updated_by.is_not(None),
                    AccountActivity.updated_at >= lo,
                    AccountActivity.updated_at < hi,
                )
                .order_by(AccountActivity.updated_at.desc())
                .limit(limit + offset)
            )
        )
        .scalars()
        .all()
    )

    merged = (
        [
            ActivityFeedEntry(
                entity_type="deal",
                entity_id=a.deal_id,
                type=_activity_type_value(a.type),
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
                type=_activity_type_value(a.type),
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
                type=_activity_type_value(a.type),
                note=a.note,
                created_by_name=a.created_by_name,
                created_at=a.created_at,
            )
            for a in account_rows
        ]
        + [
            ActivityFeedEntry(
                entity_type="deal",
                entity_id=a.deal_id,
                type=_activity_type_value(a.type),
                note=a.note,
                created_by_name=a.updated_by_name or "Unknown",
                created_at=a.updated_at,
                action="edited",
            )
            for a in deal_edit_rows
            if a.updated_at is not None
        ]
        + [
            ActivityFeedEntry(
                entity_type="lead",
                entity_id=a.lead_id,
                type=_activity_type_value(a.type),
                note=a.note,
                created_by_name=a.updated_by_name or "Unknown",
                created_at=a.updated_at,
                action="edited",
            )
            for a in lead_edit_rows
            if a.updated_at is not None
        ]
        + [
            ActivityFeedEntry(
                entity_type="account",
                entity_id=a.account_id,
                type=_activity_type_value(a.type),
                note=a.note,
                created_by_name=a.updated_by_name or "Unknown",
                created_at=a.updated_at,
                action="edited",
            )
            for a in account_edit_rows
            if a.updated_at is not None
        ]
    )
    merged.sort(key=lambda e: e.created_at, reverse=True)
    return ActivityFeedResponse(entries=merged[offset : offset + limit])
