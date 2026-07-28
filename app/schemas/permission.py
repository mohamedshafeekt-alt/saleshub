"""Permission catalog schemas."""

from app.schemas.base import ORMBase


class PermissionRead(ORMBase):

    id: int
    code: str
    label: str
    description: str | None
    module: str
