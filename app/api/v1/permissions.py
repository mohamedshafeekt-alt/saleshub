"""GET /permissions (the permission catalog, for the role-builder checkbox UI)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permission_codes import ROLES_MANAGE
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.permission import Permission
from app.schemas.permission import PermissionRead

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("", response_model=list[PermissionRead])
async def list_permissions_route(db: AsyncSession = Depends(get_db)) -> list[PermissionRead]:
    result = await db.execute(select(Permission).order_by(Permission.module, Permission.code))
    return [PermissionRead.model_validate(permission) for permission in result.scalars().all()]


tag_router_permissions(router, ROLES_MANAGE)
