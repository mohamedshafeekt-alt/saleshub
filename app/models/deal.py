"""Deal ORM model: an opportunity tied to an Account, moving through pipeline
stages (dynamic `DealStage` rows, not a fixed enum -- see
app/models/deal_stage.py)."""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.deal_scoring import priority as priority_for, score_summary, total_score
from app.db.base import Base
from app.models.enums import LeadTier

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.contact import Contact
    from app.models.deal_stage import DealStage
    from app.models.user import User

__all__ = ["Deal"]


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint(
            "originator_user_id IS NULL OR originator_contact_id IS NULL", name="ck_deals_one_originator"
        ),
    )

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
    # D1–D8 level keys, {"D1": "mild", ...}; see app/core/deal_scoring.py.
    scores: Mapped[dict[str, str] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    follow_up_date: Mapped[date | None] = mapped_column(nullable=True, index=True)
    # At most one of these: a platform User, or a Contact with is_originator.
    originator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    originator_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    # "not_sent" | "proposal_sent"; proposal_sent_at is set with the latter.
    proposal_status: Mapped[str] = mapped_column(nullable=False, default="not_sent", server_default="not_sent")
    proposal_sent_at: Mapped[date | None] = mapped_column(nullable=True)
    # created_at + the scored mode's SLA hours; stored (not derived on read)
    # so the dashboard can filter "past SLA" in SQL. Kept in step with
    # `scores` by create_deal/update_deal.
    proposal_sla_due_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)

    # Eager (joined) so DealRead's account_name/owner_name/stage_name/
    # stage_is_cold are always populated without an N+1 per deal -- same
    # pattern as DealStageHistory.changed_by_user.
    account: Mapped["Account"] = relationship(
        "Account", lazy="joined", foreign_keys=[account_id], overlaps="deals"
    )
    stage: Mapped["DealStage"] = relationship("DealStage", lazy="joined", foreign_keys=[stage_id])
    owner: Mapped["User"] = relationship("User", lazy="joined", foreign_keys=[owner_id])
    originator_user: Mapped["User | None"] = relationship(
        "User", lazy="joined", foreign_keys=[originator_user_id]
    )
    originator_contact: Mapped["Contact | None"] = relationship(
        "Contact", lazy="joined", foreign_keys=[originator_contact_id]
    )

    @property
    def originator(self) -> dict[str, object] | None:
        if self.originator_user is not None:
            u = self.originator_user
            return {"type": "user", "id": u.id, "name": " ".join(filter(None, [u.first_name, u.last_name]))}
        if self.originator_contact is not None:
            c = self.originator_contact
            return {"type": "contact", "id": c.id, "name": " ".join(filter(None, [c.first_name, c.last_name]))}
        return None

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

    @property
    def total_score(self) -> int | None:
        return total_score(self.scores)

    @property
    def response_mode(self) -> str | None:
        return score_summary(self.total_score)[0]

    @property
    def proposal_sla(self) -> str | None:
        return score_summary(self.total_score)[1]

    @property
    def priority(self) -> str | None:
        return priority_for(self.total_score)
