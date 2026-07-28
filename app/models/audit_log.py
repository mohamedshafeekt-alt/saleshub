"""AuditLog ORM model: one row per mutating action across the app (user,
lead, account, deal, contact create/update/delete, login/logout,
deactivate), written by app.services.audit_service.log_audit."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User

__all__ = ["AuditLog"]


class AuditLog(Base):
    __tablename__ = "audit_logs"

    table_name: Mapped[str] = mapped_column(index=True)
    record_id: Mapped[int]
    action: Mapped[str]
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    description: Mapped[str]
    actor: Mapped["User"] = relationship("User", lazy="joined")
