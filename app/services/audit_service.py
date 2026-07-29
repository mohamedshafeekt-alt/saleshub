"""Unified audit trail: log_audit is called by every mutating service
function (user/lead/account/deal/contact create-update-delete, login,
logout, deactivate); list_audit_logs backs the Admin-only Audit Log screen."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.enums import AuditAction


async def log_audit(
    db: AsyncSession,
    *,
    table_name: str,
    record_id: int,
    action: AuditAction,
    actor_id: int,
    description: str,
) -> None:
    db.add(
        AuditLog(
            table_name=table_name,
            record_id=record_id,
            action=action.value,
            actor_id=actor_id,
            description=description,
        )
    )
    await db.flush()


async def list_audit_logs(
    db: AsyncSession,
    *,
    table_name: str | None = None,
    action: AuditAction | None = None,
    actor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    filters = []
    if table_name is not None:
        filters.append(AuditLog.table_name == table_name)
    if action is not None:
        filters.append(AuditLog.action == action.value)
    if actor_id is not None:
        filters.append(AuditLog.actor_id == actor_id)
    if date_from is not None:
        filters.append(AuditLog.created_at >= date_from)
    if date_to is not None:
        filters.append(AuditLog.created_at <= date_to)

    count_query = select(func.count(AuditLog.id)).where(*filters)
    items_query = (
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    total = (await db.execute(count_query)).scalar_one()
    items = list((await db.execute(items_query)).scalars().all())
    return items, total
