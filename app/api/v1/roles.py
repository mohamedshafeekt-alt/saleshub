"""POST/GET/PATCH/DELETE /roles (admin role management, Configuration/Roles tabs)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permission_codes import ROLES_MANAGE
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.schemas.role import RoleCreate, RoleRead, RoleUpdate
from app.services.role_service import (
    RoleNameAlreadyExistsError,
    RoleNotFoundError,
    create_role,
    list_roles,
    soft_delete_role,
    update_role,
)

router = APIRouter(prefix="/roles", tags=["roles"])


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role_route(data: RoleCreate, db: AsyncSession = Depends(get_db)) -> RoleRead:
    try:
        role = await create_role(db, data)
    except RoleNameAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return RoleRead.model_validate(role)


@router.get("", response_model=list[RoleRead])
async def list_roles_route(db: AsyncSession = Depends(get_db)) -> list[RoleRead]:
    roles = await list_roles(db)
    return [RoleRead.model_validate(role) for role in roles]


@router.patch("/{role_id}", response_model=RoleRead)
async def update_role_route(
    role_id: int, data: RoleUpdate, db: AsyncSession = Depends(get_db)
) -> RoleRead:
    try:
        role = await update_role(db, role_id, data)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RoleNameAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return RoleRead.model_validate(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role_route(role_id: int, db: AsyncSession = Depends(get_db)) -> None:
    try:
        await soft_delete_role(db, role_id)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()


tag_router_permissions(router, ROLES_MANAGE)
