"""Lead create-or-update (single route) + role-scoped list/search."""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_email_sender
from app.core.permission_codes import LEADS_ACCESS
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from datetime import date

from app.models.enums import LeadActivityType, LeadSource, LeadStatus
from app.models.user import User
from app.schemas.account import AccountRead
from app.schemas.generic_response import Page
from app.schemas.lead import LeadConvertRequest, LeadDetailRead, LeadRead, LeadUpsert
from app.schemas.lead_activity import LeadActivityCreate, LeadActivityDetailRead, LeadActivityRead, LeadActivityUpdate
from app.schemas.lead_import import LeadImportResult
from app.services.account_service import (
    LeadAlreadyConvertedError,
    LeadMissingFieldsForConversionError,
    convert_lead_to_account,
)
from app.services.email.sender import EmailSender
from app.services.lead_import_service import LeadImportFileError, build_lead_import_template, import_leads
from app.services.export_service import field_value_sheet, rows_to_xlsx, sheets_to_xlsx
from app.services.lead_activity_service import (
    LeadActivityNotFoundError,
    create_lead_activity,
    delete_lead_activity,
    list_lead_activities,
    update_lead_activity,
)
from app.services.lead_service import (
    DuplicateLeadEmailError,
    LeadAccessForbiddenError,
    LeadNotFoundError,
    create_lead,
    delete_lead,
    export_leads,
    get_lead_detail,
    list_leads,
    update_lead,
)

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CSV_MEDIA_TYPE = "text/csv"

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("", response_model=LeadRead)
async def upsert_lead_route(
    data: LeadUpsert,
    response: Response,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> LeadRead:
    try:
        if data.id is None:
            lead = await create_lead(
                db, data, email_sender, requester=current_user, background_tasks=background_tasks
            )
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
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    to_export: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[LeadRead] | StreamingResponse:
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to must not be before date_from")
    if to_export:
        rows = await export_leads(
            db,
            requester=current_user,
            owner_id=owner_id,
            source=source,
            status=lead_status,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        buffer = rows_to_xlsx(
            ["Name", "Email", "Phone", "Company", "Source", "Status", "Owner"],
            [
                [
                    row["name"],
                    row["email"],
                    row["phone"],
                    row["company"],
                    row["source"],
                    row["status"],
                    row["owner"],
                ]
                for row in rows
            ],
            sheet_name="Leads",
        )
        return StreamingResponse(
            buffer,
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": "attachment; filename=leads.xlsx"},
        )

    leads, total = await list_leads(
        db,
        requester=current_user,
        owner_id=owner_id,
        source=source,
        status=lead_status,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return Page[LeadRead](
        items=[LeadRead.model_validate(lead) for lead in leads], total=total, limit=limit, offset=offset
    )


@router.get("/import/template")
async def download_lead_import_template_route(
    file_format: Literal["xlsx", "csv"] = Query("xlsx", alias="format"),
) -> Response:
    content = build_lead_import_template(file_format)
    media_type = _XLSX_MEDIA_TYPE if file_format == "xlsx" else _CSV_MEDIA_TYPE
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="lead_import_template.{file_format}"'},
    )


@router.post("/import", response_model=LeadImportResult)
async def import_leads_route(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    email_sender: EmailSender = Depends(get_email_sender),
) -> LeadImportResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be .xlsx or .csv")

    content = await file.read()
    try:
        # import_leads commits each successful row itself (see its module
        # docstring), so there's nothing left pending to commit here.
        return await import_leads(db, content, file.filename, current_user, email_sender)
    except LeadImportFileError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{lead_id}", response_model=LeadDetailRead)
async def get_lead_route(
    lead_id: int,
    to_export: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadDetailRead | StreamingResponse:
    try:
        lead = await get_lead_detail(db, lead_id, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    detail = LeadDetailRead.model_validate(lead)
    if not to_export:
        return detail

    lead_fields = {
        "ID": detail.id,
        "First Name": detail.first_name,
        "Last Name": detail.last_name,
        "Company": detail.company,
        "Domain": detail.domain,
        "Job Title": detail.job_title,
        "Email": detail.email,
        "Phone": detail.phone,
        "LinkedIn URL": detail.linkedin_url,
        "Source": detail.source.value,
        "Status": detail.status.value,
        "Owner": detail.owner_name,
        "Next Follow Up Date": detail.next_follow_up_date,
        "Follow Up Note": detail.follow_up_note,
        "Is Converted": detail.is_converted,
        "Created At": detail.created_at,
        "Updated At": detail.updated_at,
        "Activity Count": detail.activity_count,
        "Last Contact At": detail.last_contact_at,
    }
    activity_rows = [
        [activity.type.value if activity.type else "system", activity.note, activity.created_by_name, activity.created_at]
        for activity in detail.activities
    ]
    buffer = sheets_to_xlsx(
        [
            field_value_sheet("Lead", lead_fields),
            ("Activities", ["Type", "Note", "Created By", "Created At"], activity_rows),
        ]
    )
    return StreamingResponse(
        buffer,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="lead_{lead_id}.xlsx"'},
    )


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


@router.get("/{lead_id}/activities", response_model=list[LeadActivityDetailRead])
async def list_lead_activities_route(
    lead_id: int,
    types: list[LeadActivityType] | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadActivityDetailRead]:
    try:
        activities = await list_lead_activities(
            db, lead_id, current_user, types=types, date_from=date_from, date_to=date_to
        )
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return [LeadActivityDetailRead.model_validate(activity) for activity in activities]


@router.patch("/{lead_id}/activities/{activity_id}", response_model=LeadActivityDetailRead)
async def update_lead_activity_route(
    lead_id: int,
    activity_id: int,
    data: LeadActivityUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadActivityDetailRead:
    try:
        activity = await update_lead_activity(db, lead_id, activity_id, data, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LeadActivityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()
    return LeadActivityDetailRead.model_validate(activity)


@router.delete("/{lead_id}/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_activity_route(
    lead_id: int,
    activity_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_lead_activity(db, lead_id, activity_id, requester=current_user)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LeadAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LeadActivityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await db.commit()


tag_router_permissions(router, LEADS_ACCESS)
