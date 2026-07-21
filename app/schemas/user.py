"""User request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserStatus
from app.schemas.role import RoleRead


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str | None = None
    role_id: int


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str | None
    phone_number: str | None
    avatar_url: str | None
    role: RoleRead
    is_active: bool
    status: UserStatus
    created_at: datetime
    last_login_at: datetime | None


class UserUpdate(BaseModel):
    first_name: str
    last_name: str | None = None
    phone_number: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
