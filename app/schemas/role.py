"""Role request/response schemas."""

from pydantic import BaseModel, ConfigDict

from app.schemas.permission import PermissionRead


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    permissions: list[PermissionRead]
