"""app.models.deal_activity: DealActivity ORM model construction + constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal_activity import DealActivity
from app.models.enums import DealActivityType
from app.models.user import User
from tests.support.roles import UserRole, role_id_for


async def _make_deal_and_user(db_session: AsyncSession, make_account, make_deal, suffix: str = "a"):
    user = User(
        email=f"deal-activity-user-{suffix}@example.com",
        hashed_password="x",
        first_name="Rep",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()

    account = await make_account(owner_id=user.id, company=f"Acme {suffix}")
    deal = await make_deal(account_id=account.id, owner_id=user.id, deal_name=f"Deal {suffix}")
    return deal, user


async def test_deal_activity_persists_with_all_fields_and_inherits_timestamps(
    db_session: AsyncSession, make_account, make_deal
):
    deal, user = await _make_deal_and_user(db_session, make_account, make_deal, "persist")

    activity = DealActivity(
        deal_id=deal.id, type=DealActivityType.CALL, note="Discussed pricing", created_by=user.id
    )
    db_session.add(activity)
    await db_session.flush()
    await db_session.refresh(activity)

    assert activity.id is not None
    assert activity.deal_id == deal.id
    assert activity.type == DealActivityType.CALL
    assert activity.note == "Discussed pricing"
    assert activity.created_by == user.id
    assert activity.created_at is not None
    assert activity.updated_at is not None


async def test_deal_activity_accepts_all_type_values(db_session: AsyncSession, make_account, make_deal):
    deal, user = await _make_deal_and_user(db_session, make_account, make_deal, "types")

    for index, activity_type in enumerate(DealActivityType):
        activity = DealActivity(deal_id=deal.id, type=activity_type, created_by=user.id, note=f"note {index}")
        db_session.add(activity)
        await db_session.flush()
        await db_session.refresh(activity)

        assert activity.type == activity_type


async def test_deal_id_is_required(db_session: AsyncSession, make_account, make_deal):
    _, user = await _make_deal_and_user(db_session, make_account, make_deal, "no-deal")

    db_session.add(DealActivity(deal_id=None, type=DealActivityType.NOTE, note="orphan", created_by=user.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_created_by_is_required(db_session: AsyncSession, make_account, make_deal):
    deal, _ = await _make_deal_and_user(db_session, make_account, make_deal, "no-creator")

    db_session.add(DealActivity(deal_id=deal.id, type=DealActivityType.NOTE, note="anonymous", created_by=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()
