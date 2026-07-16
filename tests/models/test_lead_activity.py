"""app.models.lead_activity: LeadActivity ORM model construction + constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadActivityType, LeadSource
from app.models.lead import Lead
from app.models.lead_activity import LeadActivity
from app.models.user import User, UserRole


async def _make_lead_and_user(db_session: AsyncSession, suffix: str = "a") -> tuple[Lead, User]:
    user = User(
        email=f"activity-user-{suffix}@example.com", hashed_password="x", first_name="Rep", role=UserRole.SALES_REP
    )
    db_session.add(user)
    await db_session.flush()

    lead = Lead(
        first_name="Jane",
        company="Acme Corp",
        email=f"activity-lead-{suffix}@example.com",
        source=LeadSource.WEBSITE,
        owner_id=user.id,
    )
    db_session.add(lead)
    await db_session.flush()
    return lead, user


async def test_lead_activity_persists_with_all_fields_and_inherits_timestamps(db_session: AsyncSession):
    lead, user = await _make_lead_and_user(db_session, "persist")

    activity = LeadActivity(
        lead_id=lead.id, type=LeadActivityType.CALL, note="Discussed pricing", created_by=user.id
    )
    db_session.add(activity)
    await db_session.flush()
    await db_session.refresh(activity)

    assert activity.id is not None
    assert activity.lead_id == lead.id
    assert activity.type == LeadActivityType.CALL
    assert activity.note == "Discussed pricing"
    assert activity.created_by == user.id
    assert activity.created_at is not None
    assert activity.updated_at is not None


async def test_lead_activity_accepts_all_type_values(db_session: AsyncSession):
    lead, user = await _make_lead_and_user(db_session, "types")

    for index, activity_type in enumerate(LeadActivityType):
        activity = LeadActivity(lead_id=lead.id, type=activity_type, created_by=user.id, note=f"note {index}")
        db_session.add(activity)
        await db_session.flush()
        await db_session.refresh(activity)

        assert activity.type == activity_type


async def test_lead_id_is_required(db_session: AsyncSession):
    _, user = await _make_lead_and_user(db_session, "no-lead")

    db_session.add(LeadActivity(lead_id=None, type=LeadActivityType.NOTE, note="orphan", created_by=user.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_created_by_is_required(db_session: AsyncSession):
    lead, _ = await _make_lead_and_user(db_session, "no-creator")

    db_session.add(LeadActivity(lead_id=lead.id, type=LeadActivityType.NOTE, note="anonymous", created_by=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()
