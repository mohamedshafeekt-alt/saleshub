"""User ORM model: login identity + role (a set of permissions) for RBAC."""

from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import UserStatus
from app.models.role import Role

__all__ = ["User", "UserStatus"]


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    phone_number: Mapped[str | None] = mapped_column(nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)

    role: Mapped["Role"] = relationship(lazy="selectin")

    @property
    def status(self) -> UserStatus:
        if not self.is_active:
            return UserStatus.DEACTIVATED
        if self.last_login_at is None:
            return UserStatus.INVITED
        return UserStatus.ACTIVE

    @property
    def permission_codes(self) -> set[str]:
        return {permission.code for permission in self.role.permissions}
