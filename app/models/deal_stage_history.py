"""DealStageHistory ORM model: an audit trail row for each Deal stage transition.

Also the source of truth for *when* a deal closed. `Deal.updated_at` is not --
`Base.updated_at` carries `onupdate=func.now()`, so renaming a deal or editing
its value bumps it, which would drag a long-closed deal into the current
period's numbers and quietly drop it out of the period it actually closed in.
The predicates below read the real transition timestamp instead, and are shared
by the dashboard tiles and the deals-list `date_field=closed_at` filter so both
answer the same question.
"""

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, ForeignKey, Subquery, and_, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.deal import Deal

if TYPE_CHECKING:
    from app.models.deal_stage import DealStage
    from app.models.user import User

__all__ = ["DealStageHistory", "entered_current_stage_in", "stage_as_of"]


class DealStageHistory(Base):
    __tablename__ = "deal_stage_history"

    deal_id: Mapped[int] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_stage_id: Mapped[int | None] = mapped_column(ForeignKey("deal_stages.id"), nullable=True)
    to_stage_id: Mapped[int] = mapped_column(ForeignKey("deal_stages.id"), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(nullable=True)

    changed_by_user: Mapped["User"] = relationship("User", lazy="joined", foreign_keys=[changed_by])
    from_stage: Mapped["DealStage | None"] = relationship(
        "DealStage", lazy="joined", foreign_keys=[from_stage_id]
    )
    to_stage: Mapped["DealStage"] = relationship("DealStage", lazy="joined", foreign_keys=[to_stage_id])

    @property
    def changed_by_name(self) -> str:
        return " ".join(filter(None, [self.changed_by_user.first_name, self.changed_by_user.last_name]))

    @property
    def from_stage_name(self) -> str | None:
        return self.from_stage.name if self.from_stage is not None else None

    @property
    def to_stage_name(self) -> str:
        return self.to_stage.name


def _latest_entry_into_current_stage() -> ColumnElement[datetime]:
    """Scalar subquery on Deal: when it MOST RECENTLY moved into the stage it is
    in now. Evaluates to SQL NULL if no such transition was ever recorded -- not
    reflected in the annotation, since ColumnElement's parameter is invariant."""
    return (
        select(func.max(DealStageHistory.created_at))
        .where(
            DealStageHistory.deal_id == Deal.id,
            DealStageHistory.to_stage_id == Deal.stage_id,
        )
        .correlate(Deal)
        .scalar_subquery()
    )


def entered_current_stage_in(lo: date | None, hi: date | None) -> ColumnElement[bool]:
    """SQL predicate on Deal: the deal's LATEST move into its CURRENT stage falls
    within [lo, hi], both dates inclusive. Either bound may be None to leave that
    end open. For a deal sitting in a terminal stage, this is its close date.

    Latest, not "any" -- a deal won in March, re-opened, then re-won in August has
    two transitions into Closed Won, and an `EXISTS ... IN range` test would count
    it under BOTH months, so summing the months would exceed the distinct deal
    count. Only the most recent close counts, which also makes the tile, the
    Closed Won funnel bar and the `date_field=closed_at` drill-down agree by
    construction whatever the deal's history looks like.

    ponytail: anchored to the deal's *current* stage, so re-opening a deal removes
    it from the period it closed in, and re-winning it moves it to the newer
    period rather than leaving it in both. Swap for a plain "entered stage X, ever"
    event count if immutable historical close numbers (commission runs) ever
    matter more than tile/list agreement.

    A deal with no recorded transition into its current stage is never matched
    (NULL comparisons are never true) -- same as before.
    """
    latest = _latest_entry_into_current_stage()
    conditions = []
    if lo is not None:
        conditions.append(latest >= lo)
    if hi is not None:
        conditions.append(latest < hi + timedelta(days=1))
    if not conditions:
        return latest.is_not(None)
    return and_(*conditions)


def stage_as_of(as_of: date) -> Subquery:
    """Subquery of (deal_id, stage_id) giving each deal's stage as of the end of
    `as_of`, taken from its latest transition at or before then.

    Lets a past period be reported as it actually stood rather than projecting
    today's stages backwards -- a deal that closed *after* `as_of` was still
    open then, and a period's pipeline count has to say so.
    """
    ranked = (
        select(
            DealStageHistory.deal_id,
            DealStageHistory.to_stage_id.label("stage_id"),
            func.row_number()
            .over(
                partition_by=DealStageHistory.deal_id,
                order_by=(DealStageHistory.created_at.desc(), DealStageHistory.id.desc()),
            )
            .label("rn"),
        )
        .where(DealStageHistory.created_at < as_of + timedelta(days=1))
        .subquery()
    )
    return select(ranked.c.deal_id, ranked.c.stage_id).where(ranked.c.rn == 1).subquery()
