"""Lead ORM model: prospecting record owned by a Sales Rep."""

from datetime import date

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import LeadSource, LeadTier

__all__ = ["Lead"]


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    company: Mapped[str] = mapped_column(nullable=False)
    domain: Mapped[str | None] = mapped_column(nullable=True)
    job_title: Mapped[str | None] = mapped_column(nullable=True)
    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(nullable=True)
    source: Mapped[LeadSource] = mapped_column(
        Enum(LeadSource, name="lead_source", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=False,
    )
    tier: Mapped[LeadTier] = mapped_column(
        Enum(LeadTier, name="lead_tier", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=False,
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    next_follow_up_date: Mapped[date | None] = mapped_column(nullable=True)
    follow_up_note: Mapped[str | None] = mapped_column(nullable=True)
