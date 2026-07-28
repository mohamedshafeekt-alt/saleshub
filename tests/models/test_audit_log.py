import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.enums import AuditAction

pytestmark = pytest.mark.anyio


async def test_audit_log_row_persists_with_expected_fields(db_session, make_user):
    user = await make_user(email="audit-model@example.com")

    row = AuditLog(
        table_name="leads",
        record_id=42,
        action=AuditAction.CREATED.value,
        actor_id=user.id,
        description="Lead 'Acme Corp' created",
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(select(AuditLog).where(AuditLog.record_id == 42))
    saved = result.scalar_one()
    assert saved.table_name == "leads"
    assert saved.action == "created"
    assert saved.actor_id == user.id
    assert saved.description == "Lead 'Acme Corp' created"
    assert saved.created_at is not None
