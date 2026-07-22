"""app.models.permission: Permission ORM model construction + constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission


async def test_permission_persists_with_all_fields(db_session: AsyncSession):
    permission = Permission(code="widgets.manage", label="Manage Widgets", description="Do widget things", module="Widgets")
    db_session.add(permission)
    await db_session.flush()
    await db_session.refresh(permission)

    assert permission.id is not None
    assert permission.code == "widgets.manage"
    assert permission.is_active is True
    assert permission.is_delete is False


async def test_permission_code_must_be_unique(db_session: AsyncSession):
    db_session.add(Permission(code="dupe.code", label="A", module="M"))
    await db_session.flush()

    db_session.add(Permission(code="dupe.code", label="B", module="M"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
