"""DealContact ORM model: many-to-many join between a Deal and its stakeholder Contacts."""

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["DealContact"]


class DealContact(Base):
    __tablename__ = "deal_contacts"
    __table_args__ = (UniqueConstraint("deal_id", "contact_id", name="uq_deal_contacts_deal_id_contact_id"),)

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
