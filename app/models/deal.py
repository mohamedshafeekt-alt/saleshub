"""Deal ORM model: an opportunity tied to an Account, moving through pipeline
stages (dynamic `DealStage` rows, not a fixed enum -- see
app/models/deal_stage.py)."""

from datetime import date

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import LeadTier

__all__ = ["Deal"]


class Deal(Base):
    __tablename__ = "deals"

    deal_name: Mapped[str] = mapped_column(nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(nullable=False, default="USD", server_default="USD")
    expected_close_date: Mapped[date | None] = mapped_column(nullable=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("deal_stages.id"), nullable=False, index=True)
    tier: Mapped[LeadTier | None] = mapped_column(
        Enum(LeadTier, name="lead_tier", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=True,
    )
    cold_reason: Mapped[str | None] = mapped_column(nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
