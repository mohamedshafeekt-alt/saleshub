"""Deal CRUD + role-scoped list/search/sort (flat list or kanban board),
stage-history, xlsx export, and a generic allowlisted field-patch route."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.permission_codes import DEALS_ACCESS
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.enums import DealActivityType, LeadTier
from app.models.user import User
from app.schemas.deal import (
    DealBoardColumn,
    DealContactRead,
    DealCreate,
    DealRead,
    DealsListResponse,
    DealStageHistoryRead,
    DealUpdate,
)
from app.schemas.deal_activity import (
    DealActivityCreate,
    DealActivityDetailRead,
    DealActivityRead,
    DealActivityUpdate,
)
from app.schemas.deal_document import DealDocumentRead
from app.schemas.generic_patch import GenericPatchRequest, GenericPatchResponse
from app.services.account_service import AccountNotFoundError
from app.services.contact_service import ContactNotFoundError
from app.services.deal_activity_service import (
    DealActivityNotFoundError,
    create_deal_activity,
    delete_deal_activity,
    list_deal_activities,
    update_deal_activity,
)
from app.services.deal_document_service import (
    DealDocumentNotFoundError,
    delete_deal_document,
    list_deal_documents,
    upload_deal_document,
)
from app.services.deal_service import (
    ColdReasonRequiredError,
    DealAccessForbiddenError,
    DealNotFoundError,
    DealStageNotFoundError,
    create_deal,
    delete_deal,
    export_deals,
    get_deal,
    get_deal_contact_ids,
    get_deal_contact_ids_by_deal,
    list_deals,
    list_deals_board,
    list_stage_history,
    update_deal,
)
from app.services.export_service import field_value_sheet, rows_to_xlsx, sheets_to_xlsx
from app.services.file_upload_service import UnsupportedFileTypeError
from app.services.generic_patch_service import (
    GenericPatchFieldNotAllowedError,
    GenericPatchRecordNotFoundError,
    GenericPatchTableNotAllowedError,
    generic_patch,
)

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/deals", tags=["deals"])


def _deal_read(deal: object, contact_ids: list[tuple[int, str, str, str | None]]) -> DealRead:
    contacts = [
        DealContactRead(id=cid, name=name, email=email, phone=phone)
        for cid, name, email, phone in contact_ids
    ]
    return DealRead.model_validate(deal).model_copy(update={"contacts": contacts})


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
    except DealStageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ColdReasonRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
    contact_ids = await get_deal_contact_ids(db, deal.id)
    return _deal_read(deal, contact_ids)


# Not called by any UI screen: expects raw DB table/column names, which no
# frontend form should know about. Intended for internal/admin ad-hoc data
# fixes only, per the original spec ("db table name, field name, required
# change"). Prefer PATCH /deals/{deal_id} for anything a real screen edits.
@router.patch("/generic-patch", response_model=GenericPatchResponse)
async def generic_patch_route(
    data: GenericPatchRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenericPatchResponse:
    try:
        result = await generic_patch(
            db, table=data.table, record_id=data.record_id, field=data.field, value=data.value
        )
    except GenericPatchTableNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except GenericPatchFieldNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except GenericPatchRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
    return GenericPatchResponse(**result)


@router.get("", response_model=DealsListResponse)
async def list_deals_route(
    view: Literal["board", "list"] = Query("list"),
    owner_id: int | None = Query(None),
    account_id: int | None = Query(None),
    stage_id: int | None = Query(None),
    tier: list[LeadTier] | None = Query(None),
    search: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    sort_by: Literal["value", "expected_close_date", "created_at"] = Query("created_at"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    limit: int = Query(20),
    offset: int = Query(0),
    to_export: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealsListResponse | StreamingResponse:
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to must not be before date_from")
    if to_export:
        rows = await export_deals(
            db,
            requester=current_user,
            owner_id=owner_id,
            stage_id=stage_id,
            tier=tier,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        buffer = rows_to_xlsx(
            [
                "Deal Name", "Account", "Contact", "Value", "Currency",
                "Stage", "Tier", "Owner", "Expected Close Date", "Cold Reason",
            ],
            [
                [
                    row["deal_name"], row["account"], row["contact"], row["value"], row["currency"],
                    row["stage"], row["tier"], row["owner"], row["expected_close_date"], row["cold_reason"],
                ]
                for row in rows
            ],
            sheet_name="Deals",
        )
        return StreamingResponse(
            buffer,
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": "attachment; filename=deals.xlsx"},
        )

    if view == "board":
        columns = await list_deals_board(
            db,
            requester=current_user,
            owner_id=owner_id,
            account_id=account_id,
            stage_id=stage_id,
            tier=tier,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        all_deal_ids = [deal.id for _stage, deals in columns for deal in deals]
        contact_ids_by_deal = await get_deal_contact_ids_by_deal(db, all_deal_ids)
        return DealsListResponse(
            view="board",
            columns=[
                DealBoardColumn(
                    stage_id=stage.id,
                    stage_name=stage.name,
                    total_value=sum(deal.value or 0 for deal in deals),
                    deals=[_deal_read(deal, contact_ids_by_deal.get(deal.id, [])) for deal in deals],
                )
                for stage, deals in columns
            ],
        )

    deals, total = await list_deals(
        db,
        requester=current_user,
        owner_id=owner_id,
        account_id=account_id,
        stage_id=stage_id,
        tier=tier,
        search=search,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    contact_ids_by_deal = await get_deal_contact_ids_by_deal(db, [deal.id for deal in deals])
    return DealsListResponse(
        view="list",
        items=[_deal_read(deal, contact_ids_by_deal.get(deal.id, [])) for deal in deals],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{deal_id}", response_model=DealRead)
async def get_deal_route(
    deal_id: int,
    to_export: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealRead | StreamingResponse:
    try:
        deal = await get_deal(db, deal_id, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    contact_ids = await get_deal_contact_ids(db, deal.id)
    deal_read = _deal_read(deal, contact_ids)
    if not to_export:
        return deal_read

    deal_fields = {
        "ID": deal_read.id,
        "Deal Name": deal_read.deal_name,
        "Account": deal_read.account_name,
        "Contacts": ", ".join(contact.name for contact in deal_read.contacts),
        "Value": deal_read.value,
        "Currency": deal_read.currency,
        "Expected Close Date": deal_read.expected_close_date,
        "Stage": deal_read.stage_name,
        "Tier": deal_read.tier.value if deal_read.tier else None,
        "Cold Reason": deal_read.cold_reason,
        "Owner": deal_read.owner_name,
    }
    history = await list_stage_history(db, deal_id, requester=current_user)
    history_rows = [
        [row.from_stage_name, row.to_stage_name, row.changed_by, row.note, row.created_at]
        for row in history
    ]
    buffer = sheets_to_xlsx(
        [
            field_value_sheet("Deal", deal_fields),
            (
                "Stage History",
                ["From Stage", "To Stage", "Changed By", "Note", "Created At"],
                history_rows,
            ),
        ]
    )
    return StreamingResponse(
        buffer,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="deal_{deal_id}.xlsx"'},
    )


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
    except DealStageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ColdReasonRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
    contact_ids = await get_deal_contact_ids(db, deal.id)
    return _deal_read(deal, contact_ids)


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


@router.post(
    "/{deal_id}/activities", response_model=DealActivityRead, status_code=status.HTTP_201_CREATED
)
async def create_deal_activity_route(
    deal_id: int,
    data: DealActivityCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealActivityRead:
    try:
        activity = await create_deal_activity(db, deal_id, data, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()
    return DealActivityRead.model_validate(activity)


@router.get("/{deal_id}/activities", response_model=list[DealActivityDetailRead])
async def list_deal_activities_route(
    deal_id: int,
    types: list[DealActivityType] | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DealActivityDetailRead]:
    try:
        activities = await list_deal_activities(
            db, deal_id, current_user, types=types, date_from=date_from, date_to=date_to
        )
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return [DealActivityDetailRead.model_validate(activity) for activity in activities]


@router.patch("/{deal_id}/activities/{activity_id}", response_model=DealActivityDetailRead)
async def update_deal_activity_route(
    deal_id: int,
    activity_id: int,
    data: DealActivityUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealActivityDetailRead:
    try:
        activity = await update_deal_activity(db, deal_id, activity_id, data, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DealActivityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
    return DealActivityDetailRead.model_validate(activity)


@router.delete("/{deal_id}/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal_activity_route(
    deal_id: int,
    activity_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_deal_activity(db, deal_id, activity_id, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DealActivityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()


@router.post(
    "/{deal_id}/documents", response_model=DealDocumentRead, status_code=status.HTTP_201_CREATED
)
async def upload_deal_document_route(
    deal_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DealDocumentRead:
    content = await file.read()
    try:
        document = await upload_deal_document(
            db,
            deal_id,
            content=content,
            filename=file.filename or "document",
            content_type=file.content_type or "",
            requester=current_user,
        )
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return DealDocumentRead.model_validate(document)


@router.get("/{deal_id}/documents", response_model=list[DealDocumentRead])
async def list_deal_documents_route(
    deal_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DealDocumentRead]:
    try:
        documents = await list_deal_documents(db, deal_id, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return [DealDocumentRead.model_validate(document) for document in documents]


@router.delete("/{deal_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal_document_route(
    deal_id: int,
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_deal_document(db, deal_id, document_id, requester=current_user)
    except DealNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DealAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DealDocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()


tag_router_permissions(router, DEALS_ACCESS)
