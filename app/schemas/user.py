"""User request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator
from app.schemas.base import ORMBase

from app.models.user import UserStatus
from app.schemas.role import RoleRead
from app.services.storage import resolve_file_url


class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str | None = None
    role_id: int


class UserRead(ORMBase):

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

    @field_validator("avatar_url")
    @classmethod
    def _resolve_avatar_url(cls, value: str | None) -> str | None:
        return resolve_file_url(value) if value is not None else None


class UserUpdate(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str | None = None
    phone_number: str | None = None


class UserRoleUpdate(BaseModel):
    role_id: int


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def _require_password_strength(cls, value: str) -> str:
        if not any(c.isupper() for c in value):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in value):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in value):
            raise ValueError("Password must contain at least one digit")
        return value
