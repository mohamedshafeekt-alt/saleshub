"""DealStage ORM model: a per-company, admin-configurable pipeline stage.

Replaces the old fixed `DealStage` Python/Postgres enum -- deals now point at
a row here via `stage_id`, and `is_cold` (not a hardcoded enum comparison)
marks the stage that requires a `cold_reason` on the deal.
"""

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["DealStage"]


class DealStage(Base):
    __tablename__ = "deal_stages"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_deal_stages_company_id_name"),)

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False)
    is_cold: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
