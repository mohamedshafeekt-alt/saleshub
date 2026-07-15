"""User ORM model: login identity + role for RBAC."""

from sqlalchemy import Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UserRole

__all__ = ["User", "UserRole"]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
