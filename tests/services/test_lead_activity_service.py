"""app.services.lead_activity_service: create/list/update/delete a lead
activity.

Covers: successful create; not-found/forbidden gating reuses Lead's own
existence/ownership check; list filtering by type and date range; update
stamps the editor; delete removes the row; activity-not-found on a real lead.
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LeadActivityType
from app.models.lead_activity import LeadActivity
from app.models.user import User
from tests.support.roles import UserRole, role_id_for
from app.schemas.lead_activity import LeadActivityCreate, LeadActivityUpdate
from app.services.lead_activity_service import (
    LeadActivityNotFoundError,
    create_lead_activity,
    delete_lead_activity,
    list_lead_activities,
    update_lead_activity,
)
from app.services.lead_service import LeadAccessForbiddenError, LeadNotFoundError


async def _make_user(db_session: AsyncSession, email: str, role: UserRole) -> User:
    user = User(email=email, hashed_password="x", first_name="Test", role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
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


async def test_list_lead_activities_filters_by_type(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-list-activity@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="list-activity@example.com")
    call = LeadActivity(lead_id=lead.id, type=LeadActivityType.CALL, note="call", created_by=owner.id)
    note = LeadActivity(lead_id=lead.id, type=LeadActivityType.NOTE, note="note", created_by=owner.id)
    db_session.add_all([call, note])
    await db_session.flush()

    results = await list_lead_activities(db_session, lead.id, owner, types=[LeadActivityType.CALL])

    assert [activity.id for activity in results] == [call.id]


async def test_list_lead_activities_filters_by_date_range(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-list-activity-date@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="list-activity-date@example.com")
    in_range = LeadActivity(lead_id=lead.id, type=LeadActivityType.NOTE, note="in range", created_by=owner.id)
    db_session.add(in_range)
    await db_session.flush()
    in_range.created_at = date(2026, 7, 10)
    out_of_range = LeadActivity(
        lead_id=lead.id, type=LeadActivityType.NOTE, note="out of range", created_by=owner.id
    )
    db_session.add(out_of_range)
    await db_session.flush()
    out_of_range.created_at = date(2026, 8, 1)
    await db_session.flush()

    results = await list_lead_activities(
        db_session, lead.id, owner, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
    )

    assert [activity.id for activity in results] == [in_range.id]


async def test_list_lead_activities_raises_not_found_for_missing_lead(db_session: AsyncSession):
    requester = await _make_user(db_session, "list-activity-requester@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(LeadNotFoundError):
        await list_lead_activities(db_session, 999_999, requester)


async def test_update_lead_activity_applies_changes_and_stamps_editor(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-update-activity@example.com", UserRole.SALES_REP)
    editor = await _make_user(db_session, "editor-update-activity@example.com", UserRole.SALES_MANAGER)
    lead = await make_lead(owner_id=owner.id, email="update-activity@example.com")
    activity = LeadActivity(lead_id=lead.id, type=LeadActivityType.NOTE, note="original", created_by=owner.id)
    db_session.add(activity)
    await db_session.flush()

    updated = await update_lead_activity(
        db_session, lead.id, activity.id, LeadActivityUpdate(note="revised"), requester=editor
    )

    assert updated.note == "revised"
    assert updated.updated_by == editor.id
    assert updated.updated_by_name == "Test"


async def test_update_lead_activity_raises_not_found_for_missing_activity(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-update-missing-activity@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="update-missing-activity@example.com")

    with pytest.raises(LeadActivityNotFoundError):
        await update_lead_activity(
            db_session, lead.id, 999_999, LeadActivityUpdate(note="x"), requester=owner
        )


async def test_delete_lead_activity_removes_the_row(db_session: AsyncSession, make_lead):
    owner = await _make_user(db_session, "owner-delete-activity@example.com", UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="delete-activity@example.com")
    activity = LeadActivity(lead_id=lead.id, type=LeadActivityType.NOTE, note="to delete", created_by=owner.id)
    db_session.add(activity)
    await db_session.flush()
    activity_id = activity.id

    await delete_lead_activity(db_session, lead.id, activity_id, requester=owner)

    with pytest.raises(LeadActivityNotFoundError):
        await update_lead_activity(
            db_session, lead.id, activity_id, LeadActivityUpdate(note="x"), requester=owner
        )
