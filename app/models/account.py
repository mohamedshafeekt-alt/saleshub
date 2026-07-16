"""Account ORM model: converted-lead / customer record owned by a Sales Rep."""

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import LeadTier

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
