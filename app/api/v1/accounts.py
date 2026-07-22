"""Account CRUD + role-scoped list/search."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.permission_codes import ACCOUNTS_ACCESS
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.contact import Contact
from app.models.enums import LeadTier
from app.models.user import User
from app.schemas.account import AccountCreate, AccountOverviewRead, AccountRead, AccountUpdate
from app.schemas.contact_account import AccountContactRead, AccountContactUpsert
from app.schemas.deal import DealRead
from app.schemas.generic_response import Page
from app.services.account_service import (
    AccountAccessForbiddenError,
    AccountNotFoundError,
    PrimaryContactAlreadyExistsError,
    create_account,
    delete_account,
    get_account,
    get_account_overview,
    list_accounts,
    update_account,
)
from app.services.contact_account_service import (
    ContactNotFoundError,
    create_account_contact,
    list_account_contacts,
    update_account_contact,
)
from app.services.deal_service import list_deals_for_account

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _to_account_contact_read(contact: Contact, is_primary: bool) -> AccountContactRead:
    return AccountContactRead(
        id=contact.id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        phone=contact.phone,
        alternate_phone=contact.alternate_phone,
        job_title=contact.job_title,
        linkedin_url=contact.linkedin_url,
        is_primary=is_primary,
    )


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
async def create_account_route(
    data: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountRead:
    account = await create_account(db, data)
    await db.commit()
    return AccountRead.model_validate(account)


@router.get("", response_model=Page[AccountRead])
async def list_accounts_route(
    owner_id: int | None = Query(None),
    tier: LeadTier | None = Query(None),
    industry: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[AccountRead]:
    accounts, total = await list_accounts(
        db,
        requester=current_user,
        owner_id=owner_id,
        tier=tier,
        industry=industry,
        search=search,
        limit=limit,
        offset=offset,
    )
    return Page[AccountRead](
        items=[AccountRead.model_validate(account) for account in accounts],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{account_id}", response_model=AccountRead)
async def get_account_route(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountRead:
    try:
        account = await get_account(db, account_id, requester=current_user)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return AccountRead.model_validate(account)


@router.get("/{account_id}/overview", response_model=AccountOverviewRead)
async def get_account_overview_route(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountOverviewRead:
    try:
        account, active_deals, open_deal_value = await get_account_overview(
            db, account_id, requester=current_user
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return AccountOverviewRead(
        id=account.id,
        company=account.company,
        domain=account.domain,
        tier=account.tier,
        owner_id=account.owner_id,
        owner_name=account.owner_name,
        industry=account.industry,
        city=account.city,
        description=account.description,
        linkedin_url=account.linkedin_url,
        open_deal_value=open_deal_value,
        key_contacts=[
            _to_account_contact_read(ca.contact, ca.is_primary) for ca in account.contact_accounts
        ],
        active_deals=[DealRead.model_validate(deal) for deal in active_deals],
    )


@router.patch("/{account_id}", response_model=AccountRead)
async def update_account_route(
    account_id: int,
    data: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountRead:
    try:
        account = await update_account(db, account_id, data, requester=current_user)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()
    return AccountRead.model_validate(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account_route(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_account(db, account_id, requester=current_user)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()


@router.get("/{account_id}/contacts", response_model=Page[AccountContactRead])
async def list_contacts_for_account_route(
    account_id: int,
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[AccountContactRead]:
    try:
        contacts, total = await list_account_contacts(
            db, account_id, requester=current_user, limit=limit, offset=offset
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return Page[AccountContactRead](
        items=[_to_account_contact_read(contact, is_primary) for contact, is_primary in contacts],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{account_id}/contacts", response_model=AccountContactRead)
async def upsert_account_contact_route(
    account_id: int,
    data: AccountContactUpsert,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountContactRead:
    """Single create-or-update route, same dispatch pattern as POST /leads:
    absent `contact_id` creates a new Contact + link (201); present
    `contact_id` updates that contact's fields and/or is_primary (200)."""
    try:
        if data.contact_id is None:
            contact, contact_account = await create_account_contact(
                db, account_id, data, requester=current_user
            )
            response.status_code = status.HTTP_201_CREATED
        else:
            contact, contact_account = await update_account_contact(
                db, account_id, data.contact_id, data, requester=current_user
            )
            response.status_code = status.HTTP_200_OK
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PrimaryContactAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return _to_account_contact_read(contact, contact_account.is_primary)


@router.get("/{account_id}/deals", response_model=list[DealRead])
async def list_deals_for_account_route(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DealRead]:
    try:
        deals = await list_deals_for_account(db, account_id, requester=current_user)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return [DealRead.model_validate(deal) for deal in deals]


tag_router_permissions(router, ACCOUNTS_ACCESS)
