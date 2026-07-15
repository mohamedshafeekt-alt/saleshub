"""app.models.user: User ORM model constraints."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


async def test_duplicate_email_violates_unique_constraint(db_session: AsyncSession):
    db_session.add(
        User(email="dupe@example.com", hashed_password="x", first_name="Test", role=UserRole.SALES_REP)
    )
    await db_session.flush()

    db_session.add(
        User(email="dupe@example.com", hashed_password="y", first_name="Test", role=UserRole.ADMIN)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_is_required(db_session: AsyncSession):
    db_session.add(User(email="norole@example.com", hashed_password="x", first_name="Test", role=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_rejects_invalid_value(db_session: AsyncSession):
    db_session.add(
        User(email="badrole@example.com", hashed_password="x", first_name="Test", role="not_a_real_role")
    )
    with pytest.raises(Exception):  # noqa: B017 - exact type (LookupError/DataError) is DB-driver dependent
        await db_session.flush()


async def test_is_active_defaults_to_true(db_session: AsyncSession):
    user = User(
        email="active-default@example.com", hashed_password="x", first_name="Test", role=UserRole.SALES_REP
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.is_active is True


async def test_user_persists_and_is_queryable(db_session: AsyncSession):
    db_session.add(
        User(email="query-me@example.com", hashed_password="x", first_name="Test", role=UserRole.DELIVERY_SME)
    )
    await db_session.flush()

    result = await db_session.execute(select(User).where(User.email == "query-me@example.com"))
    fetched = result.scalar_one()

    assert fetched.role == UserRole.DELIVERY_SME
