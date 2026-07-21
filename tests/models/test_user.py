"""app.models.user: User ORM model constraints."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserStatus
from tests.support.roles import UserRole, role_id_for


async def test_duplicate_email_violates_unique_constraint(db_session: AsyncSession):
    db_session.add(
        User(
            email="dupe@example.com",
            hashed_password="x",
            first_name="Test",
            role_id=await role_id_for(db_session, UserRole.SALES_REP),
        )
    )
    await db_session.flush()

    db_session.add(
        User(
            email="dupe@example.com",
            hashed_password="y",
            first_name="Test",
            role_id=await role_id_for(db_session, UserRole.ADMIN),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_id_is_required(db_session: AsyncSession):
    db_session.add(User(email="norole@example.com", hashed_password="x", first_name="Test", role_id=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_id_rejects_unknown_role(db_session: AsyncSession):
    db_session.add(
        User(email="badrole@example.com", hashed_password="x", first_name="Test", role_id=999_999)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_is_active_defaults_to_true(db_session: AsyncSession):
    user = User(
        email="active-default@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.is_active is True


async def test_user_persists_and_is_queryable(db_session: AsyncSession):
    db_session.add(
        User(
            email="query-me@example.com",
            hashed_password="x",
            first_name="Test",
            role_id=await role_id_for(db_session, UserRole.DELIVERY_SME),
        )
    )
    await db_session.flush()

    result = await db_session.execute(select(User).where(User.email == "query-me@example.com"))
    fetched = result.scalar_one()

    assert fetched.role.name == UserRole.DELIVERY_SME.value


async def test_is_delete_defaults_to_false(db_session: AsyncSession):
    user = User(
        email="not-deleted@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.is_delete is False


async def test_profile_fields_default_to_none(db_session: AsyncSession):
    user = User(
        email="profile-fields-default@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.phone_number is None
    assert user.avatar_url is None
    assert user.last_login_at is None


async def test_status_is_invited_when_active_with_no_login(db_session: AsyncSession):
    user = User(
        email="never-logged-in@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
    )
    db_session.add(user)
    await db_session.flush()

    assert user.status == UserStatus.INVITED


async def test_status_is_active_when_active_with_a_login(db_session: AsyncSession):
    from datetime import UTC, datetime

    user = User(
        email="has-logged-in@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
        last_login_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db_session.add(user)
    await db_session.flush()

    assert user.status == UserStatus.ACTIVE


async def test_status_is_deactivated_when_is_active_false_regardless_of_login(db_session: AsyncSession):
    from datetime import UTC, datetime

    user = User(
        email="deactivated-with-login@example.com",
        hashed_password="x",
        first_name="Test",
        role_id=await role_id_for(db_session, UserRole.SALES_REP),
        is_active=False,
        last_login_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db_session.add(user)
    await db_session.flush()

    assert user.status == UserStatus.DEACTIVATED
