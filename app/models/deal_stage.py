"""DealStage ORM model: a per-company, admin-configurable pipeline stage.

Replaces the old fixed `DealStage` Python/Postgres enum -- deals now point at
a row here via `stage_id`, and `is_cold` (not a hardcoded enum comparison)
marks the stage that requires a `cold_reason` on the deal.
"""

from sqlalchemy import ColumnElement, ForeignKey, UniqueConstraint, or_
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = [
    "CLOSED_LOST_STAGE_NAME",
    "CLOSED_WON_STAGE_NAME",
    "DealStage",
    "is_terminal_stage",
]

# ponytail: stage identity (won/lost) is inferred from DealStage.name, not a
# dedicated stage_type column -- DealStage is per-company, so this breaks
# silently if a company renames these stages. Accepted for Phase 1's fixed
# stage list; add a DealStage.stage_type enum if per-company custom stages
# become real. Defined here rather than in a service because dashboard_service
# and deal_service both need it and each used to keep its own copy -- two
# places to forget when the rename finally happens.
CLOSED_WON_STAGE_NAME = "Closed Won"
CLOSED_LOST_STAGE_NAME = "Closed Lost"


class DealStage(Base):
    __tablename__ = "deal_stages"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_deal_stages_company_id_name"),)

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False)
    is_cold: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


def is_terminal_stage() -> ColumnElement[bool]:
    """SQL predicate on DealStage: this stage is out of the pipeline -- Closed
    Won, Closed Lost, or any cold stage.

    Needs DealStage in the query's FROM. Either join it explicitly, or wrap the
    predicate for a Deal-only query with ``Deal.stage.has(is_terminal_stage())``.
    """
    return or_(
        DealStage.is_cold.is_(True),
        DealStage.name.in_([CLOSED_WON_STAGE_NAME, CLOSED_LOST_STAGE_NAME]),
    )
