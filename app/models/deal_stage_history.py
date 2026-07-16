"""DealStageHistory ORM model: an audit trail row for each Deal stage transition."""

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DealStage

__all__ = ["DealStageHistory"]

_deal_stage_enum = Enum(
    DealStage, name="deal_stage", values_callable=lambda enum_cls: [m.value for m in enum_cls]
)


class DealStageHistory(Base):
    __tablename__ = "deal_stage_history"

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_stage: Mapped[DealStage | None] = mapped_column(_deal_stage_enum, nullable=True)
    to_stage: Mapped[DealStage] = mapped_column(_deal_stage_enum, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(nullable=True)
