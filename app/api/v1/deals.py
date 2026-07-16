"""Deal CRUD + role-scoped list/search + stage-history."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import DealStage
from app.models.user import User, UserRole
from app.schemas.deal import DealCreate, DealRead, DealStageHistoryRead, DealUpdate
from app.schemas.generic_response import Page
from app.services.account_service import AccountNotFoundError
from app.services.deal_service import (
    ColdReasonRequiredError,
    DealAccessForbiddenError,
    DealNotFoundError,
    create_deal,
    delete_deal,
    get_deal,
    list_deals,
    list_stage_history,
    update_deal,
)

router = APIRouter(
    prefix="/deals",
    tags=["deals"],
    dependencies=[Depends(require_role(UserRole.SALES_REP, UserRole.SALES_MANAGER, UserRole.ADMIN))],
)


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
async def create_deal_route(
    data: DealCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealRead:
    try:
        deal = await create_deal(db, data, requester=current_user)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ColdReasonRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return DealRead.model_validate(deal)


@router.get("", response_model=Page[DealRead])
async def list_deals_route(
    owner_id: int | None = Query(None),
    account_id: int | None = Query(None),
    stage: DealStage | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[DealRead]:
    deals, total = await list_deals(
        db,
        requester=current_user,
        owner_id=owner_id,
        account_id=account_id,
        stage=stage,
        search=search,
        limit=limit,
        offset=offset,
    )
    return Page[DealRead](
        items=[DealRead.model_validate(deal) for deal in deals], total=total, limit=limit, offset=offset
    )


@router.get("/{deal_id}", response_model=DealRead)
async def get_deal_route(
    deal_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealRead:
    try:
        deal = await get_deal(db, deal_id, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return DealRead.model_validate(deal)


@router.patch("/{deal_id}", response_model=DealRead)
async def update_deal_route(
    deal_id: int,
    data: DealUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealRead:
    try:
        deal = await update_deal(db, deal_id, data, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ColdReasonRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return DealRead.model_validate(deal)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal_route(
    deal_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_deal(db, deal_id, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()


@router.get("/{deal_id}/stage-history", response_model=list[DealStageHistoryRead])
async def list_stage_history_route(
    deal_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DealStageHistoryRead]:
    try:
        history = await list_stage_history(db, deal_id, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return [DealStageHistoryRead.model_validate(row) for row in history]
