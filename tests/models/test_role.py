"""app.models.role: Role ORM model construction + permission relationship."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission
from app.models.role import Role


async def test_role_persists_with_permissions(db_session: AsyncSession):
    permission = Permission(code="widgets.manage", label="Manage Widgets", module="Widgets")
    db_session.add(permission)
    await db_session.flush()

    role = Role(name="Widget Admin", description="Manages widgets", permissions=[permission])
    db_session.add(role)
    await db_session.flush()
    await db_session.refresh(role)

    assert role.id is not None
    assert [p.code for p in role.permissions] == ["widgets.manage"]


async def test_role_name_must_be_unique(db_session: AsyncSession):
    db_session.add(Role(name="Dupe Role"))
    await db_session.flush()

    db_session.add(Role(name="Dupe Role"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_can_have_no_permissions(db_session: AsyncSession):
    role = Role(name="Empty Role")
    db_session.add(role)
    await db_session.flush()
    await db_session.refresh(role)

    assert role.permissions == []
