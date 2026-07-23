"""DealStageHistory ORM model: an audit trail row for each Deal stage transition."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

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
