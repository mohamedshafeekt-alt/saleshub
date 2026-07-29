from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.enums import AuditAction
from app.services.audit_service import list_audit_logs, log_audit

pytestmark = pytest.mark.anyio


async def test_log_audit_inserts_a_row(db_session, make_user):
    user = await make_user(email="audit-svc-1@example.com")

    await log_audit(
        db_session,
        table_name="leads",
        record_id=7,
        action=AuditAction.CREATED,
        actor_id=user.id,
        description="Lead 'Acme' created",
    )
    await db_session.flush()

    result = await db_session.execute(select(AuditLog).where(AuditLog.record_id == 7))
    saved = result.scalar_one()
    assert saved.table_name == "leads"
    assert saved.action == "created"
    assert saved.actor_id == user.id


async def test_list_audit_logs_filters_and_paginates(db_session, make_user):
    user = await make_user(email="audit-svc-2@example.com")
    other = await make_user(email="audit-svc-3@example.com")

    await log_audit(db_session, table_name="leads", record_id=1, action=AuditAction.CREATED, actor_id=user.id, description="a")
    await log_audit(db_session, table_name="accounts", record_id=2, action=AuditAction.UPDATED, actor_id=user.id, description="b")
    await log_audit(db_session, table_name="leads", record_id=3, action=AuditAction.DELETED, actor_id=other.id, description="c")
    await db_session.flush()

    items, total = await list_audit_logs(db_session, table_name="leads")
    assert total == 2
    assert {item.record_id for item in items} == {1, 3}

    items, total = await list_audit_logs(db_session, actor_id=user.id)
    assert total == 2

    items, total = await list_audit_logs(db_session, action=AuditAction.DELETED)
    assert total == 1
    assert items[0].record_id == 3

    items, total = await list_audit_logs(db_session, limit=1, offset=0)
    assert total == 3
    assert len(items) == 1


async def test_list_audit_logs_date_range_filter(db_session, make_user):
    from datetime import date

    user = await make_user(email="audit-svc-4@example.com")
    await log_audit(db_session, table_name="leads", record_id=99, action=AuditAction.CREATED, actor_id=user.id, description="d")
    await db_session.flush()

    future = date.today() + timedelta(days=1)
    items, total = await list_audit_logs(db_session, date_from=future)
    assert total == 0
