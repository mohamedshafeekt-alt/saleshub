"""GET /api/v1/audit-log — Admin-only, filterable, paginated read of the
unified audit trail written by app.services.audit_service.log_audit."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permission_codes import AUDIT_LOG_VIEW
from app.core.rbac import tag_router_permissions
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction
from app.schemas.audit_log import AuditLogRead
from app.schemas.generic_response import Page
from app.services.audit_service import list_audit_logs

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


def _to_read(row: AuditLog) -> AuditLogRead:
    return AuditLogRead(
        id=row.id,
        table_name=row.table_name,
        record_id=row.record_id,
        action=row.action,
        actor_id=row.actor_id,
        actor_name=f"{row.actor.first_name} {row.actor.last_name or ''}".strip(),
        description=row.description,
        created_at=row.created_at,
    )


@router.get("", response_model=Page[AuditLogRead])
async def list_audit_log_route(
    table_name: str | None = Query(None),
    action: AuditAction | None = Query(None),
    actor_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> Page[AuditLogRead]:
    items, total = await list_audit_logs(
        db,
        table_name=table_name,
        action=action,
        actor_id=actor_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return Page[AuditLogRead](items=[_to_read(item) for item in items], total=total, limit=limit, offset=offset)


tag_router_permissions(router, AUDIT_LOG_VIEW)
