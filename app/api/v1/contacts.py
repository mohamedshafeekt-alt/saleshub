"""Standalone Contact CRUD -- role-gated only (Contact has no owner_id and
no single owning account; see contact_service.py's module docstring). Use
POST/PUT /accounts/{account_id}/contacts (app/api/v1/accounts.py) to create
or update a contact together with its account link and is_primary flag."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permission_codes import CONTACTS_ACCESS
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.services.contact_service import (
    ContactNotFoundError,
    DuplicateContactEmailError,
    create_contact,
    delete_contact,
    get_contact,
    update_contact,
)

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact_route(
    data: ContactCreate,
    db: AsyncSession = Depends(get_db),
) -> ContactRead:
    try:
        contact = await create_contact(db, data)
    except DuplicateContactEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return ContactRead.model_validate(contact)


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact_route(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
) -> ContactRead:
    try:
        contact = await get_contact(db, contact_id)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ContactRead.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact_route(
    contact_id: int,
    data: ContactUpdate,
    db: AsyncSession = Depends(get_db),
) -> ContactRead:
    try:
        contact = await update_contact(db, contact_id, data)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateContactEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return ContactRead.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact_route(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_contact(db, contact_id)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()


tag_router_permissions(router, CONTACTS_ACCESS)
