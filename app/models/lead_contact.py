"""LeadContact ORM model: an extra email/phone contact point for a Lead.

A Lead's own `email`/`phone` remain its primary contact; this table holds
that primary contact (mirrored on creation) plus any additional contacts
added via "+ Add another email" -- a Lead can have more than one.
"""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["LeadContact"]


class LeadContact(Base):
    __tablename__ = "lead_contacts"

    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(nullable=True)
    phone: Mapped[str | None] = mapped_column(nullable=True)
