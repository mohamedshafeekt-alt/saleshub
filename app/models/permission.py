"""Permission ORM model: the RBAC permission catalog, as data rather than a code enum."""

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    module: Mapped[str] = mapped_column(nullable=False)
