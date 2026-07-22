"""Role ORM model: an admin-creatable, named set of permissions."""

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.permission import Permission
from app.models.role_permission import role_permissions


class Role(Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions, lazy="selectin")
