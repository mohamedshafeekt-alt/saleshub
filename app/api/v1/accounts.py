"""Account CRUD + role-scoped list/search."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.permission_codes import ACCOUNTS_ACCESS
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.enums import LeadTier
from app.models.user import User
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate
from app.schemas.contact import ContactRead
from app.schemas.deal import DealRead
from app.schemas.generic_response import Page
from app.services.account_service import (
    AccountAccessForbiddenError,
    AccountNotFoundError,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)
from app.services.contact_service import list_contacts_for_account
from app.services.deal_service import list_deals_for_account

router = APIRouter(prefix="/accounts", tags=["accounts"])


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


@router.get("/{account_id}/contacts", response_model=Page[ContactRead])
async def list_contacts_for_account_route(
    account_id: int,
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[ContactRead]:
    try:
        contacts, total = await list_contacts_for_account(
            db, account_id, requester=current_user, limit=limit, offset=offset
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccountAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return Page[ContactRead](
        items=[ContactRead.model_validate(contact) for contact in contacts],
        total=total,
        limit=limit,
        offset=offset,
    )


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
