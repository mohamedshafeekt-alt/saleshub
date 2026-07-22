"""ContactAccount ORM model: the many-to-many link between a Contact and an
Account, carrying the per-account is_primary flag.

A partial unique index enforces "at most one primary contact per account" at
the database level (mirrors the Lead.email unique-index + catch-IntegrityError
pattern used elsewhere) -- see create_account_contact/update_account_contact
in app/services/contact_account_service.py for where that's caught and turned
into PrimaryContactAlreadyExistsError.
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.contact import Contact

__all__ = ["ContactAccount"]


class ContactAccount(Base):
    __tablename__ = "contact_accounts"
    __table_args__ = (
        UniqueConstraint("contact_id", "account_id", name="uq_contact_accounts_contact_account"),
        Index(
            "uq_contact_accounts_one_primary_per_account",
            "account_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
        ),
    )

    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    contact: Mapped["Contact"] = relationship("Contact", lazy="joined")
    account: Mapped["Account"] = relationship("Account", lazy="joined")
