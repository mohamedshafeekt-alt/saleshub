"""Lead create-or-update (single route) + role-scoped list/search."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_email_sender, require_role
from app.db.session import get_db
from app.models.enums import LeadSource, LeadStatus
from app.models.user import User, UserRole
from app.schemas.account import AccountRead
from app.schemas.generic_response import Page
from app.schemas.lead import LeadConvertRequest, LeadDetailRead, LeadRead, LeadUpsert
from app.schemas.lead_activity import LeadActivityCreate, LeadActivityRead
from app.services.account_service import (
    LeadAlreadyConvertedError,
    LeadMissingFieldsForConversionError,
    convert_lead_to_account,
)
from app.services.email.sender import EmailSender
from app.services.lead_activity_service import create_lead_activity
from app.services.lead_service import (
    DuplicateLeadEmailError,
    LeadAccessForbiddenError,
    LeadNotFoundError,
    create_lead,
    delete_lead,
    get_lead_detail,
    list_leads,
    update_lead,
)

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
    dependencies=[
        Depends(require_role(UserRole.SALES_REP, UserRole.DELIVERY_SME, UserRole.SALES_MANAGER, UserRole.ADMIN))
    ],
)


@router.post("", response_model=LeadRead)
async def upsert_lead_route(
    data: LeadUpsert,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> LeadRead:
    try:
        if data.id is None:
            lead = await create_lead(db, data, email_sender)
            response.status_code = status.HTTP_201_CREATED
        else:
            lead = await update_lead(db, data.id, data, requester=current_user)
            response.status_code = status.HTTP_200_OK
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DuplicateLeadEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return LeadRead.model_validate(lead)


@router.get("", response_model=Page[LeadRead])
async def list_leads_route(
    owner_id: int | None = Query(None),
    source: LeadSource | None = Query(None),
    lead_status: LeadStatus | None = Query(None, alias="status"),
    search: str | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[LeadRead]:
    leads, total = await list_leads(
        db,
        requester=current_user,
        owner_id=owner_id,
        source=source,
        status=lead_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return Page[LeadRead](
        items=[LeadRead.model_validate(lead) for lead in leads], total=total, limit=limit, offset=offset
    )


@router.get("/{lead_id}", response_model=LeadDetailRead)
async def get_lead_route(
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadDetailRead:
    try:
        lead = await get_lead_detail(db, lead_id, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return LeadDetailRead.model_validate(lead)


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


@router.post("/{lead_id}/convert", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
async def convert_lead_route(
    lead_id: int,
    data: LeadConvertRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountRead:
    try:
        account = await convert_lead_to_account(
            db,
            lead_id,
            requester=current_user,
            tier=data.tier if data else None,
            owner_id=data.owner_id if data else None,
        )
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LeadAlreadyConvertedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except LeadMissingFieldsForConversionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return AccountRead.model_validate(account)


@router.post(
    "/{lead_id}/activities", response_model=LeadActivityRead, status_code=status.HTTP_201_CREATED
)
async def create_lead_activity_route(
    lead_id: int,
    data: LeadActivityCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadActivityRead:
    try:
        activity = await create_lead_activity(db, lead_id, data, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()
    return LeadActivityRead.model_validate(activity)
