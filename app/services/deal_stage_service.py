"""DealStage business logic: plain CRUD plus a delete guard so a stage in use
by any deal can't be removed out from under it."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal import Deal
from app.models.deal_stage import DealStage
from app.schemas.deal_stage import DealStageCreate, DealStageUpdate


class DealStageNotFoundError(Exception):
    """Raised when a deal stage id does not exist."""


class DealStageInUseError(Exception):
    """Raised when attempting to delete a deal stage still referenced by deals."""


async def create_deal_stage(db: AsyncSession, data: DealStageCreate) -> DealStage:
    stage = DealStage(**data.model_dump())
    db.add(stage)
    await db.flush()
    return stage


async def list_deal_stages(db: AsyncSession, *, company_id: int | None = None) -> list[DealStage]:
    query = select(DealStage).order_by(DealStage.sort_order)
    if company_id is not None:
        query = query.where(DealStage.company_id == company_id)
    return list((await db.execute(query)).scalars().all())


async def _get_deal_stage_or_raise(db: AsyncSession, stage_id: int) -> DealStage:
    stage = await db.get(DealStage, stage_id)
    if stage is None:
        raise DealStageNotFoundError(f"Deal stage not found: {stage_id}")
    return stage


async def get_deal_stage(db: AsyncSession, stage_id: int) -> DealStage:
    return await _get_deal_stage_or_raise(db, stage_id)


async def update_deal_stage(db: AsyncSession, stage_id: int, data: DealStageUpdate) -> DealStage:
    stage = await _get_deal_stage_or_raise(db, stage_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(stage, field, value)
    await db.flush()
    return stage


async def delete_deal_stage(db: AsyncSession, stage_id: int) -> None:
    stage = await _get_deal_stage_or_raise(db, stage_id)

    in_use = (
        await db.execute(select(Deal.id).where(Deal.stage_id == stage_id).limit(1))
    ).scalar_one_or_none()
    if in_use is not None:
        raise DealStageInUseError(f"Deal stage {stage_id} is still referenced by deals")

    await db.delete(stage)
    await db.flush()
