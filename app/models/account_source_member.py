"""AccountSourceMember: one person in an Account's "Source Detail" chain
(e.g. Ram -> TT Bhat -> Radhika) -- a platform User or a Contact, in order."""

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["AccountSourceMember"]


class AccountSourceMember(Base):
    __tablename__ = "account_source_members"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL) <> (contact_id IS NOT NULL)", name="ck_account_source_members_one_person"
        ),
        # A person appears at most once per chain.
        UniqueConstraint("account_id", "user_id", name="uq_account_source_members_user"),
        UniqueConstraint("account_id", "contact_id", name="uq_account_source_members_contact"),
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
