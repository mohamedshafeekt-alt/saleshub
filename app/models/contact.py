"""Contact ORM model: a person, independent of any single Account.

A Contact is linked to the Account(s) they're associated with via
ContactAccount (see app/models/contact_account.py) -- a Contact can be
associated with more than one Account, and each association carries its own
is_primary flag (at most one primary contact per account, enforced by a
partial unique index on ContactAccount).
"""

from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact_account import ContactAccount

__all__ = ["Contact"]


class Contact(Base):
    __tablename__ = "contacts"

    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    email: Mapped[str | None] = mapped_column(unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    alternate_phone: Mapped[str | None] = mapped_column(nullable=True)
    job_title: Mapped[str | None] = mapped_column(nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(nullable=True)

    # passive_deletes: the FK's ON DELETE CASCADE handles removing these rows
    # in the database -- without this, SQLAlchemy instead tries to UPDATE
    # each row's contact_id to NULL on delete, which violates its NOT NULL.
    contact_accounts: Mapped[list["ContactAccount"]] = relationship(
        "ContactAccount", order_by="ContactAccount.id", passive_deletes=True
    )
