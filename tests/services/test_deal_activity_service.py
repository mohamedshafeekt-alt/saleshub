"""app.services.deal_activity_service: create/list/update/delete a deal
activity.

Covers: successful create; not-found/forbidden gating reuses Deal's own
existence/ownership check; list filtering by type and date range; update
stamps the editor; delete removes the row; activity-not-found on a real deal.
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal_activity import DealActivity
from app.models.enums import DealActivityType
from app.models.user import User
from app.schemas.deal_activity import DealActivityCreate, DealActivityUpdate
from app.services.deal_activity_service import (
    DealActivityNotFoundError,
    create_deal_activity,
    delete_deal_activity,
    list_deal_activities,
    update_deal_activity,
)
from app.services.deal_service import DealAccessForbiddenError, DealNotFoundError
from tests.support.roles import UserRole, role_id_for


async def _make_user(db_session: AsyncSession, email: str, role: UserRole) -> User:
    user = User(email=email, hashed_password="x", first_name="Test", role_id=await role_id_for(db_session, role))
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user, attribute_names=["role"])
    return user


async def _make_deal(make_account, make_deal, owner):
    account = await make_account(owner_id=owner.id, company=f"Acme {owner.email}")
    return await make_deal(account_id=account.id, owner_id=owner.id, deal_name=f"Deal for {owner.email}")


async def test_create_deal_activity_succeeds(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-deal-activity@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)

    data = DealActivityCreate(type=DealActivityType.CALL, note="Discussed pricing")
    activity = await create_deal_activity(db_session, deal.id, data, requester=owner)

    assert activity.id is not None
    assert activity.deal_id == deal.id
    assert activity.type == DealActivityType.CALL
    assert activity.note == "Discussed pricing"
    assert activity.created_by == owner.id


async def test_create_deal_activity_raises_not_found_for_missing_deal(db_session: AsyncSession):
    requester = await _make_user(db_session, "deal-activity-requester@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(DealNotFoundError):
        await create_deal_activity(
            db_session, 999_999, DealActivityCreate(type=DealActivityType.NOTE, note="x"), requester=requester
        )


async def test_create_deal_activity_raises_forbidden_for_non_owning_sales_rep(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-deal-activity-forbidden@example.com", UserRole.SALES_REP)
    other_rep = await _make_user(db_session, "other-rep-deal-activity@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)

    with pytest.raises(DealAccessForbiddenError):
        await create_deal_activity(
            db_session, deal.id, DealActivityCreate(type=DealActivityType.NOTE, note="x"), requester=other_rep
        )


async def test_list_deal_activities_filters_by_type(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-list-deal-activity@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)
    call = DealActivity(deal_id=deal.id, type=DealActivityType.CALL, note="call", created_by=owner.id)
    note = DealActivity(deal_id=deal.id, type=DealActivityType.NOTE, note="note", created_by=owner.id)
    db_session.add_all([call, note])
    await db_session.flush()

    results = await list_deal_activities(db_session, deal.id, owner, types=[DealActivityType.CALL])

    assert [activity.id for activity in results] == [call.id]


async def test_list_deal_activities_filters_by_date_range(db_session: AsyncSession, make_account, make_deal):
    owner = await _make_user(db_session, "owner-list-deal-activity-date@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)
    in_range = DealActivity(deal_id=deal.id, type=DealActivityType.NOTE, note="in range", created_by=owner.id)
    db_session.add(in_range)
    await db_session.flush()
    in_range.created_at = date(2026, 7, 10)
    out_of_range = DealActivity(
        deal_id=deal.id, type=DealActivityType.NOTE, note="out of range", created_by=owner.id
    )
    db_session.add(out_of_range)
    await db_session.flush()
    out_of_range.created_at = date(2026, 8, 1)
    await db_session.flush()

    results = await list_deal_activities(
        db_session, deal.id, owner, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
    )

    assert [activity.id for activity in results] == [in_range.id]


async def test_list_deal_activities_raises_not_found_for_missing_deal(db_session: AsyncSession):
    requester = await _make_user(db_session, "list-deal-activity-requester@example.com", UserRole.SALES_MANAGER)

    with pytest.raises(DealNotFoundError):
        await list_deal_activities(db_session, 999_999, requester)


async def test_update_deal_activity_applies_changes_and_stamps_editor(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-update-deal-activity@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)
    activity = DealActivity(deal_id=deal.id, type=DealActivityType.NOTE, note="original", created_by=owner.id)
    db_session.add(activity)
    await db_session.flush()

    updated = await update_deal_activity(
        db_session, deal.id, activity.id, DealActivityUpdate(note="revised"), requester=owner
    )

    assert updated.note == "revised"
    assert updated.updated_by == owner.id
    assert updated.updated_by_name == "Test"


async def test_update_deal_activity_raises_forbidden_for_non_owner(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-update-deal-activity-forbidden@example.com", UserRole.SALES_REP)
    manager = await _make_user(db_session, "manager-update-deal-activity@example.com", UserRole.SALES_MANAGER)
    admin = await _make_user(db_session, "admin-update-deal-activity@example.com", UserRole.ADMIN)
    deal = await _make_deal(make_account, make_deal, owner)
    activity = DealActivity(deal_id=deal.id, type=DealActivityType.NOTE, note="original", created_by=owner.id)
    db_session.add(activity)
    await db_session.flush()

    for non_owner in (manager, admin):
        with pytest.raises(DealAccessForbiddenError):
            await update_deal_activity(
                db_session, deal.id, activity.id, DealActivityUpdate(note="revised"), requester=non_owner
            )


async def test_update_deal_activity_raises_not_found_for_missing_activity(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-update-missing-deal-activity@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)

    with pytest.raises(DealActivityNotFoundError):
        await update_deal_activity(
            db_session, deal.id, 999_999, DealActivityUpdate(note="x"), requester=owner
        )


async def test_delete_deal_activity_removes_the_row_when_requester_is_admin(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-delete-deal-activity@example.com", UserRole.SALES_REP)
    admin = await _make_user(db_session, "admin-delete-deal-activity@example.com", UserRole.ADMIN)
    deal = await _make_deal(make_account, make_deal, owner)
    activity = DealActivity(deal_id=deal.id, type=DealActivityType.NOTE, note="to delete", created_by=owner.id)
    db_session.add(activity)
    await db_session.flush()
    activity_id = activity.id

    await delete_deal_activity(db_session, deal.id, activity_id, requester=admin)

    with pytest.raises(DealActivityNotFoundError):
        await update_deal_activity(
            db_session, deal.id, activity_id, DealActivityUpdate(note="x"), requester=owner
        )


async def test_delete_deal_activity_raises_forbidden_for_deal_owner(
    db_session: AsyncSession, make_account, make_deal
):
    owner = await _make_user(db_session, "owner-delete-deal-activity-forbidden@example.com", UserRole.SALES_REP)
    deal = await _make_deal(make_account, make_deal, owner)
    activity = DealActivity(deal_id=deal.id, type=DealActivityType.NOTE, note="to delete", created_by=owner.id)
    db_session.add(activity)
    await db_session.flush()

    with pytest.raises(DealAccessForbiddenError):
        await delete_deal_activity(db_session, deal.id, activity.id, requester=owner)
