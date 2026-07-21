"""Notification ORM model: one row per recipient, for the in-app bell/panel."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import NotificationType

if TYPE_CHECKING:
    from app.models.user import User

__all__ = ["Notification"]

_notification_type_enum = Enum(
    NotificationType, name="notification_type", values_callable=lambda enum_cls: [m.value for m in enum_cls]
)


class Notification(Base):
    __tablename__ = "notifications"

    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[NotificationType] = mapped_column(_notification_type_enum, nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(nullable=False)
    is_read: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(nullable=False)
    entity_id: Mapped[int] = mapped_column(nullable=False)

    recipient: Mapped["User"] = relationship("User", foreign_keys=[recipient_id], lazy="joined")
    actor: Mapped["User | None"] = relationship("User", foreign_keys=[actor_id], lazy="joined")
