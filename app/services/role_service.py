"""Role business logic: create/list/update (permission set)/soft-delete."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission
from app.models.role import Role
from app.schemas.role import RoleCreate, RoleUpdate


class RoleNameAlreadyExistsError(Exception):
    """Raised when attempting to create/rename a role to a name already in use."""


class RoleNotFoundError(Exception):
    """Raised when a role id doesn't match an existing, non-deleted role."""


async def _load_permissions(db: AsyncSession, permission_ids: list[int]) -> list[Permission]:
    if not permission_ids:
        return []
    result = await db.execute(select(Permission).where(Permission.id.in_(permission_ids)))
    return list(result.scalars().all())


async def create_role(db: AsyncSession, data: RoleCreate) -> Role:
    role = Role(
        name=data.name,
        description=data.description,
        permissions=await _load_permissions(db, data.permission_ids),
    )
    db.add(role)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise RoleNameAlreadyExistsError(f"Role name already exists: {data.name}") from exc

    return role


async def list_roles(db: AsyncSession) -> list[Role]:
    result = await db.execute(
        select(Role).where(Role.is_delete.is_(False)).order_by(Role.name)
    )
    return list(result.scalars().all())


async def _get_role(db: AsyncSession, role_id: int) -> Role:
    result = await db.execute(select(Role).where(Role.id == role_id, Role.is_delete.is_(False)))
    role = result.scalar_one_or_none()
    if role is None:
        raise RoleNotFoundError(f"Role not found: {role_id}")
    return role


async def update_role(db: AsyncSession, role_id: int, data: RoleUpdate) -> Role:
    role = await _get_role(db, role_id)
    role.name = data.name
    role.description = data.description
    role.permissions = await _load_permissions(db, data.permission_ids)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise RoleNameAlreadyExistsError(f"Role name already exists: {data.name}") from exc

    return role


async def soft_delete_role(db: AsyncSession, role_id: int) -> None:
    role = await _get_role(db, role_id)
    role.is_delete = True
    await db.flush()
