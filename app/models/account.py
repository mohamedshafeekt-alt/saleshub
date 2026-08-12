"""Account ORM model: converted-lead / customer record owned by a Sales Rep."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import LeadTier

if TYPE_CHECKING:
    from app.models.contact_account import ContactAccount
    from app.models.deal import Deal
    from app.models.user import User

__all__ = ["Account"]


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company: Mapped[str] = mapped_column(nullable=False)
    domain: Mapped[str | None] = mapped_column(nullable=True)
    tier: Mapped[LeadTier] = mapped_column(
        Enum(LeadTier, name="lead_tier", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=False,
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    industry: Mapped[str | None] = mapped_column(nullable=True)
    city: Mapped[str | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(nullable=True)

    # owner_id is NOT NULL (unlike Lead's), so owner is always present -- no
    # "| None" needed, unlike Lead.owner.
    owner: Mapped["User"] = relationship("User", lazy="joined")
    # Contacts are reached via the ContactAccount link (a Contact can belong
    # to more than one Account) -- there is no direct Account.contacts anymore.
    # passive_deletes="all" (not True): get_account/delete_account eagerly
    # selectinload this collection, so it's already populated by the time an
    # Account is deleted. Plain passive_deletes=True still nulls out an
    # already-loaded child's FK on parent delete (contact_accounts.account_id
    # is NOT NULL -> IntegrityError); "all" defers fully to the FK's own ON
    # DELETE CASCADE regardless of what's loaded.
    contact_accounts: Mapped[list["ContactAccount"]] = relationship(
        "ContactAccount", order_by="ContactAccount.id", passive_deletes="all"
    )
    deals: Mapped[list["Deal"]] = relationship("Deal", order_by="Deal.id")

    @property
    def owner_name(self) -> str:
        return " ".join(filter(None, [self.owner.first_name, self.owner.last_name]))

    @property
    def contact_count(self) -> int:
        return len(self.contact_accounts)

    @property
    def deal_count(self) -> int:
        return len(self.deals)
