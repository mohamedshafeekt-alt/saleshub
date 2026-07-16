"""User request/response schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str | None = None
    # Deliberate default (confirmed product decision, not an oversight):
    # omitting role on creation grants Admin, not a lower-privilege role.
    role: UserRole = UserRole.ADMIN


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str | None
    role: UserRole
    is_active: bool
