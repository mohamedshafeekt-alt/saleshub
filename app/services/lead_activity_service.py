"""LeadActivity business logic: create/list/update/delete a
Note/Meeting/Call/Comment/Follow-up against a Lead, gated by the same
existence/ownership check as the rest of the Lead API."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import LeadActivityType
from app.models.lead_activity import LeadActivity
from app.models.user import User
from app.schemas.lead_activity import LeadActivityCreate, LeadActivityUpdate
from app.services.lead_service import get_lead


class LeadActivityNotFoundError(Exception):
    """Raised when an activity id does not exist on the given lead."""


async def create_lead_activity(
    db: AsyncSession, lead_id: int, data: LeadActivityCreate, requester: User
) -> LeadActivity:
    await get_lead(db, lead_id, requester)

    activity = LeadActivity(lead_id=lead_id, type=data.type, note=data.note, created_by=requester.id)
    db.add(activity)
    await db.flush()
    return activity


async def list_lead_activities(
    db: AsyncSession,
    lead_id: int,
    requester: User,
    *,
    types: list[LeadActivityType] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[LeadActivity]:
    await get_lead(db, lead_id, requester)

    query = select(LeadActivity).where(LeadActivity.lead_id == lead_id)
    if types:
        query = query.where(LeadActivity.type.in_(types))
    if date_from is not None:
        query = query.where(LeadActivity.created_at >= date_from)
    if date_to is not None:
        query = query.where(LeadActivity.created_at < date_to)
    query = query.order_by(LeadActivity.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


async def _get_activity_or_raise(db: AsyncSession, lead_id: int, activity_id: int, requester: User) -> LeadActivity:
    await get_lead(db, lead_id, requester)

    result = await db.execute(
        select(LeadActivity)
        .where(LeadActivity.id == activity_id, LeadActivity.lead_id == lead_id)
        .options(selectinload(LeadActivity.creator), selectinload(LeadActivity.updater))
    )
    activity = result.scalar_one_or_none()
    if activity is None:
        raise LeadActivityNotFoundError(f"Activity not found: {activity_id}")
    return activity


async def update_lead_activity(
    db: AsyncSession, lead_id: int, activity_id: int, data: LeadActivityUpdate, requester: User
) -> LeadActivity:
    activity = await _get_activity_or_raise(db, lead_id, activity_id, requester)

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


async def delete_lead_activity(db: AsyncSession, lead_id: int, activity_id: int, requester: User) -> None:
    activity = await _get_activity_or_raise(db, lead_id, activity_id, requester)
    await db.delete(activity)
    await db.flush()
