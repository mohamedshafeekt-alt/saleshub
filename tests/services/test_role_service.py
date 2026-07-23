"""Role service: create/list/update/soft-delete."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission
from app.schemas.role import RoleCreate, RoleUpdate
from app.services.role_service import (
    RoleNameAlreadyExistsError,
    RoleNotFoundError,
    create_role,
    list_roles,
    soft_delete_role,
    update_role,
)


async def _make_permission(db_session: AsyncSession, code: str) -> Permission:
    permission = Permission(code=code, label=code, module="Test")
    db_session.add(permission)
    await db_session.flush()
    return permission


async def test_create_role_with_permissions(db_session: AsyncSession):
    permission = await _make_permission(db_session, "widgets.manage")

    role = await create_role(
        db_session, RoleCreate(name="Widget Admin", description="d", permission_ids=[permission.id])
    )

    assert role.id is not None
    assert [p.code for p in role.permissions] == ["widgets.manage"]


async def test_create_role_duplicate_name_raises(db_session: AsyncSession):
    await create_role(db_session, RoleCreate(name="Dupe Role"))

    with pytest.raises(RoleNameAlreadyExistsError):
        await create_role(db_session, RoleCreate(name="Dupe Role"))


async def test_list_roles_excludes_soft_deleted(db_session: AsyncSession):
    kept = await create_role(db_session, RoleCreate(name="Kept Role"))
    deleted = await create_role(db_session, RoleCreate(name="Deleted Role"))
    await soft_delete_role(db_session, deleted.id)

    roles = await list_roles(db_session)

    names = {r.name for r in roles}
    assert kept.name in names
    assert deleted.name not in names


async def test_update_role_replaces_permission_set(db_session: AsyncSession):
    permission_a = await _make_permission(db_session, "a.access")
    permission_b = await _make_permission(db_session, "b.access")
    role = await create_role(db_session, RoleCreate(name="Role", permission_ids=[permission_a.id]))

    updated = await update_role(
        db_session, role.id, RoleUpdate(name="Renamed Role", permission_ids=[permission_b.id])
    )

    assert updated.name == "Renamed Role"
    assert [p.code for p in updated.permissions] == ["b.access"]


async def test_create_role_with_view_all_auto_grants_access(db_session: AsyncSession):
    result = await db_session.execute(select(Permission).where(Permission.code == "leads.view_all"))
    view_all = result.scalar_one()

    role = await create_role(
        db_session, RoleCreate(name="Scoped Role", permission_ids=[view_all.id])
    )

    codes = {p.code for p in role.permissions}
    assert codes == {"leads.access", "leads.view_all"}


async def test_update_role_missing_id_raises_not_found(db_session: AsyncSession):
    with pytest.raises(RoleNotFoundError):
        await update_role(db_session, 999_999, RoleUpdate(name="X"))


async def test_soft_delete_role_missing_id_raises_not_found(db_session: AsyncSession):
    with pytest.raises(RoleNotFoundError):
        await soft_delete_role(db_session, 999_999)
