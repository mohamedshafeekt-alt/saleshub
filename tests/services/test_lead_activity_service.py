"""app.services.lead_activity_service: create a lead activity.

Covers: successful create; not-found/forbidden gating reuses Lead's own
existence/ownership check.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadActivityType
from app.models.user import User, UserRole
from app.schemas.lead_activity import LeadActivityCreate
from app.services.lead_activity_service import create_lead_activity
from app.services.lead_service import LeadAccessForbiddenError, LeadNotFoundError


async def _make_user(db_session: AsyncSession, email: str, role: UserRole) -> User:
    user = User(email=email, hashed_password="x", first_name="Test", role=role)
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_lead_activity_succeeds(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-activity@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="activity-lead@example.com")

    data = LeadActivityCreate(type=LeadActivityType.CALL, note="Discussed pricing")
    activity = await create_lead_activity(db_session, lead.id, data, requester=owner)

    assert activity.id is not None
    assert activity.lead_id == lead.id
    assert activity.type == LeadActivityType.CALL
    assert activity.note == "Discussed pricing"
    assert activity.created_by == owner.id


async def test_create_lead_activity_raises_not_found_for_missing_lead(db_session: AsyncSession):
    requester = await _make_user(db_session, "activity-requester@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(LeadNotFoundError):
        await create_lead_activity(
            db_session, 999_999, LeadActivityCreate(type=LeadActivityType.NOTE, note="x"), requester=requester
        )


async def test_create_lead_activity_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_lead
):
    owner = await _make_user(db_session, "owner-activity-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-activity@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="activity-forbidden@example.com")

    with pytest.raises(LeadAccessForbiddenError):
        await create_lead_activity(
            db_session, lead.id, LeadActivityCreate(type=LeadActivityType.NOTE, note="x"), requester=other_rep
        )
