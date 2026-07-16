"""LeadActivity business logic: create a Note/Meeting/Call/Comment against a
Lead, gated by the same existence/ownership check as the rest of the Lead API."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_activity import LeadActivity
from app.models.user import User
from app.schemas.lead_activity import LeadActivityCreate
from app.services.lead_service import get_lead


async def create_lead_activity(
    db: AsyncSession, lead_id: int, data: LeadActivityCreate, requester: User
) -> LeadActivity:
    await get_lead(db, lead_id, requester)

    activity = LeadActivity(lead_id=lead_id, type=data.type, note=data.note, created_by=requester.id)
    db.add(activity)
    await db.flush()
    return activity
