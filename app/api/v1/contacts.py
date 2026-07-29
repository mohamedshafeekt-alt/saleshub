"""Standalone Contact CRUD -- role-gated only (Contact has no owner_id and
no single owning account; see contact_service.py's module docstring). Use
POST/PUT /accounts/{account_id}/contacts (app/api/v1/accounts.py) to create
or update a contact together with its account link and is_primary flag."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.permission_codes import CONTACTS_ACCESS
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.contact import Contact
from app.models.contact_account import ContactAccount
from app.models.user import User
from app.models.enums import LeadTier
from app.schemas.contact import (
    ContactCreate,
    ContactListItemRead,
    ContactOverviewRead,
    ContactRead,
    ContactUpdate,
)
from app.schemas.contact_import import ContactImportResult
from app.schemas.deal import DealRead
from app.schemas.generic_response import Page
from app.services.contact_import_service import (
    ContactImportFileError,
    build_contact_import_template,
    import_contacts,
)
from app.services.contact_service import (
    ContactNotFoundError,
    DuplicateContactEmailError,
    create_contact,
    delete_contact,
    export_contacts,
    get_contact,
    get_contact_overview,
    list_contacts,
    update_contact,
)
from app.services.deal_service import list_deals_for_contact
from app.services.export_service import field_value_sheet, rows_to_xlsx, sheets_to_xlsx

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CSV_MEDIA_TYPE = "text/csv"

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _to_contact_list_item(contact: Contact, account_link: ContactAccount | None) -> ContactListItemRead:
    account = account_link.account if account_link else None
    return ContactListItemRead(
        id=contact.id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        phone=contact.phone,
        job_title=contact.job_title,
        is_primary=account_link.is_primary if account_link else False,
        account_id=account.id if account else None,
        account_name=account.company if account else None,
    )


def _to_contact_overview(
    contact: Contact, account_link: ContactAccount | None, deal_count: int
) -> ContactOverviewRead:
    account = account_link.account if account_link else None
    return ContactOverviewRead(
        id=contact.id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        phone=contact.phone,
        alternate_phone=contact.alternate_phone,
        job_title=contact.job_title,
        linkedin_url=contact.linkedin_url,
        is_primary=account_link.is_primary if account_link else False,
        account_id=account.id if account else None,
        account_name=account.company if account else None,
        owner_id=account.owner_id if account else None,
        owner_name=account.owner_name if account else None,
        tier=account.tier if account else None,
        deal_count=deal_count,
    )


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact_route(
    data: ContactCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactRead:
    try:
        contact = await create_contact(db, data, requester=current_user)
    except DuplicateContactEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return ContactRead.model_validate(contact)


@router.get("", response_model=Page[ContactListItemRead])
async def list_contacts_route(
    owner_id: int | None = Query(None),
    account_id: int | None = Query(None),
    tier: LeadTier | None = Query(None),
    is_primary: bool | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    to_export: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Page[ContactListItemRead] | StreamingResponse:
    if to_export:
        rows = await export_contacts(
            db, owner_id=owner_id, account_id=account_id, tier=tier, is_primary=is_primary, search=search
        )
        buffer = rows_to_xlsx(
            ["Name", "Email", "Phone", "Job Title", "Account", "Owner", "Tier", "Primary"],
            [
                [
                    row["name"], row["email"], row["phone"], row["job_title"],
                    row["account"], row["owner"], row["tier"], row["is_primary"],
                ]
                for row in rows
            ],
            sheet_name="Contacts",
        )
        return StreamingResponse(
            buffer,
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": "attachment; filename=contacts.xlsx"},
        )

    items, total = await list_contacts(
        db,
        owner_id=owner_id,
        account_id=account_id,
        tier=tier,
        is_primary=is_primary,
        search=search,
        limit=limit,
        offset=offset,
    )
    return Page[ContactListItemRead](
        items=[_to_contact_list_item(contact, link) for contact, link in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/import/template")
async def download_contact_import_template_route(
    file_format: Literal["xlsx", "csv"] = Query("xlsx", alias="format"),
) -> Response:
    content = build_contact_import_template(file_format)
    media_type = _XLSX_MEDIA_TYPE if file_format == "xlsx" else _CSV_MEDIA_TYPE
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="contact_import_template.{file_format}"'},
    )


@router.post("/import", response_model=ContactImportResult)
async def import_contacts_route(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> ContactImportResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be .xlsx or .csv")

    content = await file.read()
    try:
        # import_contacts commits each successful row itself (see its module
        # docstring), so there's nothing left pending to commit here.
        return await import_contacts(db, content, file.filename)
    except ContactImportFileError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{contact_id}/overview", response_model=ContactOverviewRead)
async def get_contact_overview_route(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
) -> ContactOverviewRead:
    try:
        contact, account_link, deal_count = await get_contact_overview(db, contact_id)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return _to_contact_overview(contact, account_link, deal_count)


@router.get("/{contact_id}/deals", response_model=list[DealRead])
async def list_contact_deals_route(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[DealRead]:
    try:
        deals = await list_deals_for_contact(db, contact_id)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return [DealRead.model_validate(deal) for deal in deals]


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact_route(
    contact_id: int,
    to_export: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> ContactRead | StreamingResponse:
    try:
        contact = await get_contact(db, contact_id)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    detail = ContactRead.model_validate(contact)
    if not to_export:
        return detail

    contact_fields = {
        "ID": detail.id,
        "First Name": detail.first_name,
        "Last Name": detail.last_name,
        "Email": detail.email,
        "Phone": detail.phone,
        "Alternate Phone": detail.alternate_phone,
        "Job Title": detail.job_title,
        "LinkedIn URL": detail.linkedin_url,
    }
    deals = await list_deals_for_contact(db, contact_id)
    deal_rows = [
        [deal.deal_name, deal.value, deal.currency, deal.stage_id,
         deal.tier.value if deal.tier else None, deal.owner_id, deal.expected_close_date]
        for deal in deals
    ]
    buffer = sheets_to_xlsx(
        [
            field_value_sheet("Contact", contact_fields),
            ("Deals", ["Deal Name", "Value", "Currency", "Stage ID", "Tier", "Owner ID", "Expected Close Date"], deal_rows),
        ]
    )
    return StreamingResponse(
        buffer,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="contact_{contact_id}.xlsx"'},
    )


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact_route(
    contact_id: int,
    data: ContactUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactRead:
    try:
        contact = await update_contact(db, contact_id, data, requester=current_user)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateContactEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return ContactRead.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact_route(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_contact(db, contact_id, requester=current_user)
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()


tag_router_permissions(router, CONTACTS_ACCESS)
