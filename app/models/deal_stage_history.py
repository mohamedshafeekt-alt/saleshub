"""DealStageHistory ORM model: an audit trail row for each Deal stage transition."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User

__all__ = ["DealStageHistory"]


class DealStageHistory(Base):
    __tablename__ = "deal_stage_history"

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_stage_id: Mapped[int | None] = mapped_column(ForeignKey("deal_stages.id"), nullable=True)
    to_stage_id: Mapped[int] = mapped_column(ForeignKey("deal_stages.id"), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(nullable=True)

    changed_by_user: Mapped["User"] = relationship("User", lazy="joined", foreign_keys=[changed_by])

    @property
    def changed_by_name(self) -> str:
        return " ".join(filter(None, [self.changed_by_user.first_name, self.changed_by_user.last_name]))
