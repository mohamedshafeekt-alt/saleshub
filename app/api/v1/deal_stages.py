"""Deal stage CRUD -- the admin-configurable pipeline stages deals move
through. Reuses DEALS_ACCESS; no separate permission plumbing for this."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.permission_codes import DEALS_ACCESS
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.user import User
from app.schemas.deal_stage import DealStageCreate, DealStageRead, DealStageUpdate
from app.services.deal_stage_service import (
    DealStageInUseError,
    DealStageNotFoundError,
    create_deal_stage,
    delete_deal_stage,
    get_deal_stage,
    list_deal_stages,
    update_deal_stage,
)

router = APIRouter(prefix="/deal-stages", tags=["deal-stages"])


@router.post("", response_model=DealStageRead, status_code=status.HTTP_201_CREATED)
async def create_deal_stage_route(
    data: DealStageCreate,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealStageRead:
    stage = await create_deal_stage(db, data)
    await db.commit()
    return DealStageRead.model_validate(stage)


@router.get("", response_model=list[DealStageRead])
async def list_deal_stages_route(
    company_id: int | None = Query(None),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DealStageRead]:
    stages = await list_deal_stages(db, company_id=company_id)
    return [DealStageRead.model_validate(stage) for stage in stages]


@router.get("/{stage_id}", response_model=DealStageRead)
async def get_deal_stage_route(
    stage_id: int,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealStageRead:
    try:
        stage = await get_deal_stage(db, stage_id)
    except DealStageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return DealStageRead.model_validate(stage)


@router.patch("/{stage_id}", response_model=DealStageRead)
async def update_deal_stage_route(
    stage_id: int,
    data: DealStageUpdate,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealStageRead:
    try:
        stage = await update_deal_stage(db, stage_id, data)
    except DealStageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
    return DealStageRead.model_validate(stage)


@router.delete("/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal_stage_route(
    stage_id: int,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_deal_stage(db, stage_id)
    except DealStageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealStageInUseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()


tag_router_permissions(router, DEALS_ACCESS)
