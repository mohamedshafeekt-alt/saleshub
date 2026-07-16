"""Deal business logic: account-existence-gated creation with initial stage
history, role-scoped listing/search, ownership-checked get/update/delete,
stage-transition history logging, and cold-reason enforcement."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.deal import Deal
from app.models.deal_stage_history import DealStageHistory
from app.models.enums import DealStage
from app.models.user import User, UserRole
from app.schemas.deal import DealCreate, DealUpdate
from app.services.account_service import AccountNotFoundError, get_account


class DealNotFoundError(Exception):
    """Raised when a deal id does not exist."""


class DealAccessForbiddenError(Exception):
    """Raised when a Sales Rep tries to access a deal they don't own."""


class ColdReasonRequiredError(Exception):
    """Raised when a deal's stage is set to cold_deals without a cold_reason."""


async def create_deal(db: AsyncSession, data: DealCreate, requester: User) -> Deal:
    result = await db.execute(select(Account).where(Account.id == data.account_id))
    if result.scalar_one_or_none() is None:
        raise AccountNotFoundError(f"Account not found: {data.account_id}")

    if data.stage == DealStage.COLD_DEALS and data.cold_reason is None:
        raise ColdReasonRequiredError("cold_reason is required when stage is cold_deals")

    deal = Deal(**data.model_dump())
    db.add(deal)
    await db.flush()

    db.add(
        DealStageHistory(
            deal_id=deal.id, from_stage=None, to_stage=deal.stage, changed_by=requester.id
        )
    )
    await db.flush()
    return deal


async def list_deals(
    db: AsyncSession,
    *,
    requester: User,
    owner_id: int | None = None,
    account_id: int | None = None,
    stage: DealStage | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Deal], int]:
    if requester.role == UserRole.SALES_REP:
        owner_id = requester.id

    filters = []
    if owner_id is not None:
        filters.append(Deal.owner_id == owner_id)
    if account_id is not None:
        filters.append(Deal.account_id == account_id)
    if stage is not None:
        filters.append(Deal.stage == stage)
    if search is not None:
        filters.append(Deal.deal_name.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count(Deal.id)).where(*filters))).scalar_one()
    items_query = select(Deal).where(*filters).order_by(Deal.created_at.desc()).limit(limit).offset(offset)
    items = list((await db.execute(items_query)).scalars().all())
    return items, total


async def _get_deal_or_raise(db: AsyncSession, deal_id: int, requester: User) -> Deal:
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if deal is None:
        raise DealNotFoundError(f"Deal not found: {deal_id}")
    if requester.role == UserRole.SALES_REP and deal.owner_id != requester.id:
        raise DealAccessForbiddenError(f"Not permitted to access deal: {deal_id}")
    return deal


async def get_deal(db: AsyncSession, deal_id: int, requester: User) -> Deal:
    return await _get_deal_or_raise(db, deal_id, requester)


async def update_deal(db: AsyncSession, deal_id: int, data: DealUpdate, requester: User) -> Deal:
    deal = await _get_deal_or_raise(db, deal_id, requester)

    updates = data.model_dump(exclude_unset=True, exclude={"note"})

    if "account_id" in updates:
        result = await db.execute(select(Account).where(Account.id == updates["account_id"]))
        if result.scalar_one_or_none() is None:
            raise AccountNotFoundError(f"Account not found: {updates['account_id']}")

    old_stage = deal.stage

    for field, value in updates.items():
        setattr(deal, field, value)

    if "stage" in updates and updates["stage"] != old_stage:
        db.add(
            DealStageHistory(
                deal_id=deal.id,
                from_stage=old_stage,
                to_stage=deal.stage,
                changed_by=requester.id,
                note=data.note,
            )
        )

    if deal.stage == DealStage.COLD_DEALS and deal.cold_reason is None:
        raise ColdReasonRequiredError("cold_reason is required when stage is cold_deals")

    await db.flush()
    return deal


async def delete_deal(db: AsyncSession, deal_id: int, requester: User) -> None:
    deal = await _get_deal_or_raise(db, deal_id, requester)
    await db.delete(deal)
    await db.flush()


async def list_stage_history(
    db: AsyncSession, deal_id: int, requester: User
) -> list[DealStageHistory]:
    await _get_deal_or_raise(db, deal_id, requester)

    query = (
        select(DealStageHistory)
        .where(DealStageHistory.deal_id == deal_id)
        .order_by(DealStageHistory.created_at.asc())
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_deals_for_account(db: AsyncSession, account_id: int, requester: User) -> list[Deal]:
    await get_account(db, account_id, requester)

    result = await db.execute(select(Deal).where(Deal.account_id == account_id))
    return list(result.scalars().all())
