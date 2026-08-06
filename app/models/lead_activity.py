"""LeadActivity ORM model: a Note/Meeting/Call/Comment logged against a Lead."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import LeadActivityType

if TYPE_CHECKING:
    from app.models.user import User

__all__ = ["LeadActivity"]


class LeadActivity(Base):
    __tablename__ = "lead_activities"

    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[LeadActivityType | None] = mapped_column(
        Enum(LeadActivityType, name="lead_activity_type", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=True,
    )
    note: Mapped[str] = mapped_column(nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    creator: Mapped["User"] = relationship("User", lazy="joined", foreign_keys=[created_by])
    updater: Mapped["User | None"] = relationship("User", lazy="joined", foreign_keys=[updated_by])

    @property
    def created_by_name(self) -> str:
        return " ".join(filter(None, [self.creator.first_name, self.creator.last_name]))

    @property
    def updated_by_name(self) -> str | None:
        if self.updater is None:
            return None
        return " ".join(filter(None, [self.updater.first_name, self.updater.last_name]))
