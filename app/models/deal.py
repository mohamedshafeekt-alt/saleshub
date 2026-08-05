"""Deal ORM model: an opportunity tied to an Account, moving through pipeline
stages (dynamic `DealStage` rows, not a fixed enum -- see
app/models/deal_stage.py)."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import LeadTier

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.deal_stage import DealStage
    from app.models.user import User

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

    # Eager (joined) so DealRead's account_name/owner_name/stage_name/
    # stage_is_cold are always populated without an N+1 per deal -- same
    # pattern as DealStageHistory.changed_by_user.
    account: Mapped["Account"] = relationship(
        "Account", lazy="joined", foreign_keys=[account_id], overlaps="deals"
    )
    stage: Mapped["DealStage"] = relationship("DealStage", lazy="joined", foreign_keys=[stage_id])
    owner: Mapped["User"] = relationship("User", lazy="joined", foreign_keys=[owner_id])

    @property
    def account_name(self) -> str:
        return self.account.company

    @property
    def owner_name(self) -> str:
        return " ".join(filter(None, [self.owner.first_name, self.owner.last_name]))

    @property
    def stage_name(self) -> str:
        return self.stage.name

    @property
    def stage_is_cold(self) -> bool:
        return self.stage.is_cold
