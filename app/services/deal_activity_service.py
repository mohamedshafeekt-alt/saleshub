"""DealActivity business logic: create/list/update/delete a
Note/Meeting/Call/Comment/Follow-up against a Deal, gated by the same
existence/ownership check as the rest of the Deal API."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permission_codes import DEALS_DELETE_ANY_ACTIVITY, DEALS_VIEW_ALL
from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.enums import DealActivityType
from app.models.user import User
from app.schemas.deal_activity import DealActivityCreate, DealActivityUpdate
from app.services.deal_service import DealAccessForbiddenError, get_deal


class DealActivityNotFoundError(Exception):
    """Raised when an activity id does not exist on the given deal."""


async def create_deal_activity(
    db: AsyncSession, deal_id: int, data: DealActivityCreate, requester: User
) -> DealActivity:
    await get_deal(db, deal_id, requester)

    activity = DealActivity(
        deal_id=deal_id, title=data.title, type=data.type, note=data.note, created_by=requester.id
    )
    db.add(activity)
    await db.flush()
    return activity


async def list_deal_activities(
    db: AsyncSession,
    deal_id: int,
    requester: User,
    *,
    types: list[DealActivityType] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DealActivity]:
    await get_deal(db, deal_id, requester)

    query = select(DealActivity).where(DealActivity.deal_id == deal_id)
    if types:
        query = query.where(DealActivity.type.in_(types))
    if date_from is not None:
        query = query.where(DealActivity.created_at >= date_from)
    if date_to is not None:
        query = query.where(DealActivity.created_at < date_to)
    query = query.order_by(DealActivity.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_deal_and_activity_or_raise(
    db: AsyncSession, deal_id: int, activity_id: int, requester: User
) -> tuple[Deal, DealActivity]:
    deal = await get_deal(db, deal_id, requester)

    result = await db.execute(
        select(DealActivity)
        .where(DealActivity.id == activity_id, DealActivity.deal_id == deal_id)
        .options(selectinload(DealActivity.creator), selectinload(DealActivity.updater))
    )
    activity = result.scalar_one_or_none()
    if activity is None:
        raise DealActivityNotFoundError(f"Activity not found: {activity_id}")
    return deal, activity


async def update_deal_activity(
    db: AsyncSession, deal_id: int, activity_id: int, data: DealActivityUpdate, requester: User
) -> DealActivity:
    deal, activity = await _get_deal_and_activity_or_raise(db, deal_id, activity_id, requester)
    if DEALS_VIEW_ALL not in requester.permission_codes and deal.owner_id != requester.id:
        raise DealAccessForbiddenError(f"Only the deal owner can edit its activities: deal {deal_id}")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(activity, field, value)
    activity.updated_by = requester.id

    await db.flush()
    # updated_at's onupdate is server-computed (func.now() on Base), so after
    # an UPDATE SQLAlchemy marks it expired rather than refetching it --
    # accessing it later outside an async context would raise MissingGreenlet.
    # Refresh now, while still awaitable, and reload updater for updated_by_name.
    await db.refresh(activity)
    await db.refresh(activity, attribute_names=["updater"])
    return activity


async def delete_deal_activity(db: AsyncSession, deal_id: int, activity_id: int, requester: User) -> None:
    if DEALS_DELETE_ANY_ACTIVITY not in requester.permission_codes:
        raise DealAccessForbiddenError(f"Not permitted to delete activities on deal: {deal_id}")

    _, activity = await _get_deal_and_activity_or_raise(db, deal_id, activity_id, requester)
    await db.delete(activity)
    await db.flush()
