"""Lead CRUD + role-scoped list/search."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import LeadSource, LeadTier
from app.models.user import User, UserRole
from app.schemas.lead import LeadCreate, LeadRead, LeadUpdate
from app.services.lead_service import (
    DuplicateLeadEmailError,
    LeadAccessForbiddenError,
    LeadNotFoundError,
    create_lead,
    delete_lead,
    get_lead,
    list_leads,
    update_lead,
)

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
    dependencies=[Depends(require_role(UserRole.SALES_REP, UserRole.SALES_MANAGER, UserRole.ADMIN))],
)


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
async def create_lead_route(
    data: LeadCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadRead:
    try:
        lead = await create_lead(db, data)
    except DuplicateLeadEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return LeadRead.model_validate(lead)


@router.get("", response_model=list[LeadRead])
async def list_leads_route(
    owner_id: int | None = Query(None),
    source: LeadSource | None = Query(None),
    tier: LeadTier | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadRead]:
    leads = await list_leads(
        db,
        requester=current_user,
        owner_id=owner_id,
        source=source,
        tier=tier,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [LeadRead.model_validate(lead) for lead in leads]


@router.get("/{lead_id}", response_model=LeadRead)
async def get_lead_route(
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadRead:
    try:
        lead = await get_lead(db, lead_id, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return LeadRead.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadRead)
async def update_lead_route(
    lead_id: int,
    data: LeadUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadRead:
    try:
        lead = await update_lead(db, lead_id, data, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DuplicateLeadEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return LeadRead.model_validate(lead)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_route(
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_lead(db, lead_id, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()
