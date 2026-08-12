"""Generic, allowlisted single-field/single-record patch -- backs the
`PATCH /deals/generic-patch` route. Deliberately small and reusable: any
future resource can register itself in `ALLOWED_TABLES` instead of writing
one-off dynamic-patch routes.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models.deal import Deal
from app.models.deal_stage import DealStage
from app.models.deal_stage_history import DealStageHistory

# ponytail: hardcoded allowlist, extend with new entries as new tables need
# generic-patch support rather than building a registration mechanism nobody
# asked for yet.
ALLOWED_TABLES: dict[str, type[Base]] = {
    "deals": Deal,
    "deal_stage_history": DealStageHistory,
    "deal_stages": DealStage,
}


class GenericPatchTableNotAllowedError(Exception):
    """Raised when `table` isn't in the generic-patch allowlist."""


class GenericPatchFieldNotAllowedError(Exception):
    """Raised when `field` isn't an actual column on the resolved model."""


class GenericPatchRecordNotFoundError(Exception):
    """Raised when no row with `record_id` exists in the resolved table."""


async def generic_patch(
    db: AsyncSession, *, table: str, record_id: int, field: str, value: Any, actor_id: int
) -> dict[str, Any]:
    model = ALLOWED_TABLES.get(table)
    if model is None:
        raise GenericPatchTableNotAllowedError(f"Table not allowed: {table}")

    if field not in model.__table__.columns:
        raise GenericPatchFieldNotAllowedError(f"Field not allowed on {table}: {field}")

    record = await db.get(model, record_id)
    if record is None:
        raise GenericPatchRecordNotFoundError(f"{table} record not found: {record_id}")

    # A stage move must leave a history row whichever door it came through.
    # deal_stage_history is what dates a close (see
    # deal_stage_history.entered_current_stage_in) -- a stage patched straight
    # onto the row here would otherwise disappear from Deals Closed, the
    # leaderboard and the Closed Won funnel bar, while update_deal's moves show up.
    if isinstance(record, Deal) and field == "stage_id" and value != record.stage_id:
        db.add(
            DealStageHistory(
                deal_id=record.id,
                from_stage_id=record.stage_id,
                to_stage_id=value,
                changed_by=actor_id,
            )
        )

    setattr(record, field, value)
    await db.flush()
    return {"id": record.id, "field": field, "value": value}
