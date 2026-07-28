"""Role request/response schemas."""

from pydantic import BaseModel
from app.schemas.base import ORMBase

from app.schemas.permission import PermissionRead


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleRead(ORMBase):

    id: int
    name: str
    description: str | None
    permissions: list[PermissionRead]
